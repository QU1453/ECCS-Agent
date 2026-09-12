# -*- coding: utf-8 -*-
"""工具层（core/toolkit/）：MCP 格式的工具注册 / 参数校验 / 调用框架。

定位：让 LLM 更精确地调用工具——接口描述统一用 MCP 口径，调用链路可校验、可管控、可观测。

一次调用的完整时序：
    ToolRegistry 暴露 tool schema（MCP tools/list 条目 / OpenAI TOOL_SCHEMAS）
      → 模型发起调用
      → Registry 参数校验（类型 / 必填 / 范围）——失败即把错误提示返回模型
      → Registry 交给 MCPClient（JSON-RPC 2.0 协议封装 / 连接管理 / 重试≤5 / 超时）
      → MCPServer 执行工具（独立进程可经 stdio 传输）
      → Server 回传 结果数据 + 状态码 + 元信息 → 模型
      （期间：约束层验证层四道检查 + 循环守卫照常生效；全流程 try/except 兜底）

模块地图：
- types.py        AgentConfig / ToolResult / Status / 规划轮数估算
- base.py         BaseTool（类继承方案）+ FunctionTool（既有函数零重写适配）
- validation.py   参数校验（类型/必填/范围/enum/长度/元素）
- schema.py       MCP 条目 与 OpenAI function 两种接口描述格式
- registry.py     ToolRegistry：注册/查询/分阶段动态暴露/统一调用
- client.py       MCPClient + InProcessTransport / StdioTransport（重试与超时）
- server.py       MCPServer：initialize / tools/list / tools/call（可独立进程 stdio）
- builtin_tools.py planning_tool / read_file
- defaults.py     build_default_registry：内置 + 既有业务工具装配
- bridge.py       to_langchain_tools：挂载进 LangGraph 智能体
"""
from .base import BaseTool, FunctionTool, schema_from_signature
from .bridge import to_langchain_tools
from .builtin_tools import PlanningTool, ReadFileTool
from .client import InProcessTransport, MCPClient, StdioTransport, TransportError
from .defaults import (build_default_registry, get_default_registry, reset_default_registry)
from .registry import ToolRegistry
from .schema import MCP_PROTOCOL_VERSION, mcp_tools_payload, openai_tools_payload
from .server import MCPServer
from .types import AgentConfig, Status, ToolResult, estimate_planning_rounds
from .validation import validate_arguments

__all__ = [
    "BaseTool", "FunctionTool", "schema_from_signature",
    "ToolRegistry", "AgentConfig", "ToolResult", "Status", "estimate_planning_rounds",
    "validate_arguments", "MCP_PROTOCOL_VERSION", "mcp_tools_payload", "openai_tools_payload",
    "MCPClient", "InProcessTransport", "StdioTransport", "TransportError", "MCPServer",
    "PlanningTool", "ReadFileTool",
    "build_default_registry", "get_default_registry", "reset_default_registry",
    "to_langchain_tools",
]
