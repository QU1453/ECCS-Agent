# -*- coding: utf-8 -*-
"""工具层-MCP server：工具提供方（Server）与使用方（Client/Agent）分离的独立一侧。

JSON-RPC 2.0 + stdio 传输，实现 MCP 的 3 个关键方法：
1. initialize           —— Client 发协议版本/能力声明，Server 回版本、名称、capabilities；
2. tools/list           —— 返回工具数组（name / description / inputSchema），运行时动态发现；
3. tools/call           —— 执行工具，返回 content 数组（type + 数据字段，预留多模态）+ 状态码 + 元信息。

可独立进程运行（stdio 一行一个 JSON-RPC）：
    python -m core.toolkit.server

Server 侧也会做一次参数校验（类型/必填/范围）作为防御；工具内部任何异常都被捕获，
转成 isError=true 的结果返回（错误始终对模型可见），不让异常穿透协议层。
"""
from __future__ import annotations

import json
import sys

import config

from .schema import MCP_PROTOCOL_VERSION, mcp_tools_payload
from .types import AgentConfig, Status
from .validation import validate_arguments

__all__ = ["MCPServer", "main"]

# agentConfig 允许透传的字段（其余忽略）
_AGENT_CFG_KEYS = {"role", "round_index", "planning_rounds", "read_only_mode",
                   "session_id", "timeout_s", "max_retries"}

# JSON-RPC 2.0 标准错误码
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


class MCPServer:
    """MCP 工具服务端：持有工具注册表，按 JSON-RPC 请求分发。"""

    def __init__(self, registry, name: str | None = None, version: str | None = None):
        self.registry = registry
        self.name = name or config.MCP_SERVER_NAME
        self.version = version or config.MCP_SERVER_VERSION
        self.initialized = False

    # ---- JSON-RPC 分发 -----------------------------------------------------------------
    def handle(self, request: dict):
        """处理一条 JSON-RPC 请求；返回响应 dict，通知类请求返回 None。"""
        if not isinstance(request, dict):
            return self._error(None, _INVALID_REQUEST, "Invalid Request：请求必须是 JSON 对象")
        rid = request.get("id")
        try:
            if request.get("jsonrpc") != "2.0":
                return self._error(rid, _INVALID_REQUEST, "Invalid Request：jsonrpc 必须为 2.0")
            method = request.get("method") or ""
            params = request.get("params") or {}

            if method == "initialize":
                return self._result(rid, self._initialize(params))
            if method in ("notifications/initialized", "initialized"):
                self.initialized = True
                return None
            if method == "ping":
                return self._result(rid, {})
            if method == "tools/list":
                return self._result(rid, {"tools": mcp_tools_payload(self.registry.all_tools())})
            if method == "tools/call":
                return self._result(rid, self._tools_call(params))
            return self._error(rid, _METHOD_NOT_FOUND, f"Method not found：{method}")
        except Exception as exc:  # noqa: BLE001 - 协议层兜底，绝不让异常穿透
            return self._error(rid, _INTERNAL_ERROR,
                               f"Internal error：{exc.__class__.__name__}: {exc}")

    # ---- initialize：版本 / 名称 / capabilities ----------------------------------------
    def _initialize(self, params: dict) -> dict:
        self.initialized = True
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }

    # ---- tools/call：校验 → 执行 → content + 状态码 + 元信息 ----------------------------
    def _tools_call(self, params: dict) -> dict:
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        tool = self.registry.get(name)
        if tool is None:
            return self._content(f"未注册的工具：{name}", is_error=True,
                                 status=Status.INVALID_ARGS, tool=name)

        ok, msg = validate_arguments(tool.get_schema(), args)
        if not ok:
            return self._content(msg, is_error=True,
                                 status=Status.INVALID_ARGS, tool=name)

        cfg = self._agent_config(params.get("_meta") or {})
        try:
            okr, text = tool.execute(args, cfg)
        except Exception as exc:  # noqa: BLE001 - 工具内部异常原样交给模型
            okr, text = False, f"工具内部异常（{exc.__class__.__name__}）：{exc}"
        return self._content(text, is_error=not okr,
                             status=Status.OK if okr else Status.INTERNAL_ERROR,
                             tool=name, read_only=bool(tool.read_only))

    # ---- 独立进程模式：stdio 主循环（一行一个 JSON-RPC）--------------------------------
    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = self._error(None, _PARSE_ERROR, "Parse error：非法 JSON")
            else:
                response = self.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()

    # ---- 响应构造 ---------------------------------------------------------------------
    @staticmethod
    def _result(rid, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def _error(rid, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    @staticmethod
    def _content(text: str, *, is_error: bool, status: str, **meta) -> dict:
        """MCP tools/call 结果：content 数组（预留多模态）+ isError + _meta。"""
        return {
            "content": [{"type": "text", "text": text or ""}],
            "isError": bool(is_error),
            "_meta": {"status": status, **meta},
        }

    @staticmethod
    def _agent_config(meta: dict) -> AgentConfig:
        raw = (meta or {}).get("agentConfig") or {}
        data = {k: v for k, v in raw.items() if k in _AGENT_CFG_KEYS}
        try:
            return AgentConfig(**data)
        except Exception:  # noqa: BLE001 - 非法配置回落到默认
            return AgentConfig()


def main() -> None:
    """独立进程入口：装配默认注册表并以 stdio 服务。"""
    from .defaults import build_default_registry

    MCPServer(build_default_registry()).serve_stdio()


if __name__ == "__main__":
    main()
