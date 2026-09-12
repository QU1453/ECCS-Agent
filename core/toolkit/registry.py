# -*- coding: utf-8 -*-
"""工具层-注册分发：ToolRegistry（注册 / 查询 / 动态暴露 / 统一调用）。

一次工具调用的完整流程（用户规范）：
    registry 暴露 tool schema
      → 模型发起调用
      → registry 参数校验（类型 / 必填 / 范围）——失败则返回错误提示给模型
      → registry 把「工具 + 参数」交给 MCP client（协议封装 / 连接管理 / 重试 / 超时）
      → MCP client 转发给 MCP server → 工具运行
      → server 回传 结果数据 + 状态码 + 元信息 → registry → 模型

分阶段动态加载（三原则）：
1. 只暴露任务需要的工具——阶段一（前 N 轮）只暴露规划工具，阶段二按角色 role 过滤；
2. 规划阶段轮数与任务结构复杂度正相关（见 types.estimate_planning_rounds）；
3. 写入权限与修改范围匹配——read_only 元数据 + read_only_mode（只读模式隐藏写工具）。
另有配置黑名单 configuration disabled_tools（开发者可显式禁用某些工具）。

异常兜底：call() 用 try/except 包裹整个执行过程，任何异常都转成文本返回给模型，
保证工具内部的错误（含参数错误、网络超时、工具抛错）全部由大模型可见、可自愈。
"""
from __future__ import annotations

import config

from .base import BaseTool
from .schema import mcp_tools_payload, openai_tools_payload
from .types import AgentConfig, Status, ToolResult
from .validation import validate_arguments

__all__ = ["ToolRegistry"]


def _constraint_layer():
    """约束层门面（延迟导入：constraint 包反向注册工具，防循环导入）；故障时返回 None。"""
    try:  # noqa: BLE001 - 约束层故障不阻断工具层
        from core.constraint import get_constraint_layer

        return get_constraint_layer()
    except Exception:  # noqa: BLE001
        return None


class ToolRegistry:
    """工具注册表：注册 / 查询 / 动态暴露 / 统一调用（MCP 语义）。"""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._client = None  # MCPClient（延迟装配，避免与 server 循环导入）
        self._server = None

    # ---- 注册与查询 -------------------------------------------------------------------
    def register(self, tool: BaseTool) -> None:
        """注册工具（同名覆盖 = 更新）。"""
        if not getattr(tool, "name", ""):
            raise ValueError("注册工具必须提供非空 name")
        self._tools[tool.name] = tool

    def register_all(self, *tools: BaseTool) -> None:
        for t in tools:
            self.register(t)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all_tools(self) -> list[BaseTool]:
        """全部已注册工具（MCP server 的 tools/list 用：server 返回全量，暴露过滤由 agent 侧做）。"""
        return list(self._tools.values())

    # ---- 动态暴露：阶段一（轮次）/ 阶段二（角色）/ 黑名单 / 只读模式 --------------------
    @staticmethod
    def _is_exposed(tool: BaseTool, cfg: AgentConfig) -> bool:
        if tool.name in cfg.disabled_tools:          # 配置黑名单：永不暴露
            return False
        if cfg.in_planning():
            return bool(tool.planning_only)          # 阶段一：只暴露规划工具
        if tool.planning_only:
            return False                             # 阶段二：规划工具退场
        if tool.roles and cfg.role not in tool.roles:  # 阶段二：按角色过滤
            return False
        if cfg.read_only_mode and not tool.read_only:  # 只读模式：隐藏写工具
            return False
        return True

    def exposed(self, cfg: AgentConfig) -> list[BaseTool]:
        """当前阶段/角色/权限下可见的工具列表（只暴露任务需要的）。"""
        return [t for t in self._tools.values() if self._is_exposed(t, cfg)]

    def list_mcp_tools(self, cfg: AgentConfig) -> list[dict]:
        """暴露工具的 MCP tools/list 条目（交给模型协商）。"""
        return mcp_tools_payload(self.exposed(cfg))

    def to_openai_schemas(self, cfg: AgentConfig) -> list[dict]:
        """暴露工具的 OpenAI function-calling TOOL_SCHEMAS。"""
        return openai_tools_payload(self.exposed(cfg))

    # ---- 统一调用入口：校验 → MCP client → server → 结果 + 状态码 + 元信息 --------------
    def call(self, name: str, args: dict, config_: AgentConfig | None = None) -> ToolResult:
        """全流程 try/except：任何异常都变成给模型的错误文本（绝不外抛）。"""
        cfg = config_ or AgentConfig()
        try:
            tool = self._tools.get(name)
            if tool is None:
                return ToolResult(False, f"未注册的工具：{name}",
                                  Status.INVALID_ARGS, {"tool": name})

            # 1) 动态加载管控：模型可能凭记忆调用未暴露的工具，这里二次拦截
            if not self._is_exposed(tool, cfg):
                return ToolResult(
                    False,
                    f"当前阶段（{cfg.visible_phase()}，角色 {cfg.role}）未开放工具 {name}，"
                    "请改用已开放的工具。",
                    Status.NOT_EXPOSED, {"tool": name, "phase": cfg.visible_phase()},
                )

            # 2) 约束层（验证层四道检查 + 循环守卫）：与 registry/base 双挂载点同源
            layer = _constraint_layer()
            caller = None
            if layer is not None:
                from memory.access import MemoryCaller

                caller = MemoryCaller(f"toolkit:{name}", "L1",
                                      session_id=cfg.session_id or "")
                verdict = layer.check_tool_call(name, args or {}, caller)
                if not verdict.allowed:
                    return ToolResult(False, verdict.message, Status.BLOCKED,
                                      {"tool": name, "kind": verdict.kind})

            # 3) 参数校验（类型 / 必填 / 范围）：失败即返回错误提示给模型
            ok, msg = validate_arguments(tool.get_schema(), args or {})
            if not ok:
                return ToolResult(False, msg, Status.INVALID_ARGS, {"tool": name})

            # 4) 交给 MCP client（协议封装 / 连接管理 / 重试 / 超时）→ MCP server 执行
            res = self._ensure_client().call_tool(name, args or {}, cfg)

            # 5) 记账 + 软干预提醒（相同调用 / [A,B]×3 交替 → system-reminder）
            if layer is not None and caller is not None:
                reminder = layer.record_tool_result(name, args or {}, res.ok, res.text, caller)
                if reminder and res.ok:
                    res.text += reminder
            return res
        except Exception as exc:  # noqa: BLE001 - 全流程兜底：任何异常都丢给大模型
            return ToolResult(False, f"工具调用异常（{exc.__class__.__name__}）：{exc}",
                              Status.INTERNAL_ERROR, {"tool": name})

    # ---- 与 MCP server 的装配（延迟导入避免循环）--------------------------------------
    def _ensure_client(self):
        if self._client is None:
            from .client import InProcessTransport, MCPClient
            from .server import MCPServer

            self._server = MCPServer(self)
            self._client = MCPClient(
                InProcessTransport(self._server),
                max_retries=int(config.TOOL_CALL_MAX_RETRIES),
            )
        return self._client

    def set_client(self, client) -> None:
        """注入外部 MCP client（如 StdioTransport 的独立 server 进程）。"""
        self._client = client
