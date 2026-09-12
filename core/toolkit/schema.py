# -*- coding: utf-8 -*-
"""工具层-接口描述与模型协商：把注册表里的工具转成模型可直接消费的 schema。

三个格式约定（同一份 BaseTool 元数据，多格式协商）：
1. MCP tools/list 条目：{name, description, inputSchema, annotations}；
2. OpenAI function-calling：{type:"function", function:{name, description, parameters}}；
3. 规划阶段：只暴露规划工具（阶段一），见 registry.ToolRegistry.exposed。

TOOL_SCHEMAS 即第 2 种格式的清单，直接塞进 chat.completions / responses 的 tools 参数。
"""
from __future__ import annotations

import config

__all__ = ["MCP_PROTOCOL_VERSION", "mcp_tools_payload", "openai_tools_payload"]

# MCP 协议版本（initialize 握手里声明；2024-11-05 为当前广泛实现的稳定版本）
MCP_PROTOCOL_VERSION: str = config.MCP_PROTOCOL_VERSION


def mcp_tools_payload(tools) -> list[dict]:
    """tools 列表 → MCP tools/list 响应元素数组。"""
    return [t.mcp_entry() for t in tools]


def openai_tools_payload(tools) -> list[dict]:
    """tools 列表 → OpenAI function-calling 的 TOOL_SCHEMAS 数组。"""
    return [t.openai_entry() for t in tools]
