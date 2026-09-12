# -*- coding: utf-8 -*-
"""工具层-智能体桥接：把 ToolRegistry 暴露的工具转成 LangGraph/LangChain 可挂载的工具。

阶段过滤（规划/角色/黑名单/只读模式）在 registry.exposed 里完成，
桥接层只做格式转换：JSON Schema → pydantic 入参模型 → StructuredTool，
并在调用时统一走 registry.call（参数校验 + MCP client + 结果/状态码）。
"""
from __future__ import annotations

from .types import AgentConfig

__all__ = ["to_langchain_tools"]

_JSON_TO_PY = {"string": str, "integer": int, "number": float,
               "boolean": bool, "array": list, "object": dict}


def to_langchain_tools(registry, cfg: AgentConfig | None = None) -> list:
    """当前阶段/角色下可见的工具 → LangChain StructuredTool 列表（依赖缺失返回 []）。"""
    cfg = cfg or AgentConfig()
    try:
        from langchain_core.tools import StructuredTool
        from pydantic import create_model
    except Exception:  # noqa: BLE001 - 未安装依赖时退回空列表（上层走无工具模式）
        return []

    tools: list = []
    for tool in registry.exposed(cfg):
        schema = tool.get_schema() or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        fields: dict = {}
        for pname, pspec in props.items():
            py_type = _JSON_TO_PY.get((pspec or {}).get("type"), str)
            fields[pname] = (py_type, ... if pname in required else None)
        try:
            args_model = create_model(f"{tool.name}_Args", **fields)
        except Exception:  # noqa: BLE001 - schema 异常的工具跳过，不影响其它工具
            continue

        def _invoke(_name: str = tool.name, **kwargs):
            # 统一入口：参数校验 → 约束层 → MCP client → server；错误文本直接给模型
            return registry.call(_name, kwargs, cfg).text

        _invoke.__name__ = tool.name
        _invoke.__doc__ = tool.description
        try:
            tools.append(StructuredTool.from_function(
                func=_invoke, name=tool.name, description=tool.description,
                args_schema=args_model,
            ))
        except Exception:  # noqa: BLE001
            continue
    return tools
