# -*- coding: utf-8 -*-
"""工具层-公共类型：状态码 / 工具结果 / Agent 配置 / 规划轮数估算。

本模块是整个工具层（core/toolkit/）的类型底座，不依赖任何外部服务：
- Status：工具执行结果状态码（返回给模型的状态 + 协议错误分类）；
- ToolResult：工具调用统一返回（数据 + 状态码 + 元信息），可序列化为 MCP content 数组；
- AgentConfig：一次工具会话的上下文（角色 / 阶段 / 轮次 / 黑名单 / 超时重试）；
- estimate_planning_rounds：规划阶段轮数估算（与任务结构复杂度正相关）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config

__all__ = ["Status", "ToolResult", "AgentConfig", "estimate_planning_rounds"]


class Status:
    """工具调用状态码（写入 MCP 响应 _meta.status，供模型与遥测消费）。"""

    OK = "ok"                      # 执行成功
    INVALID_ARGS = "invalid_args"  # 参数校验失败（类型/必填/范围）
    BLOCKED = "blocked"            # 约束层拦截（权限/路径/网络/危险/hook/循环）
    NOT_EXPOSED = "not_exposed"    # 当前阶段/角色未开放该工具（动态加载管控）
    TIMEOUT = "timeout"            # 调用超时（重试耗尽）
    TRANSPORT_ERROR = "transport_error"  # 传输层故障（连接/进程/协议帧）
    PROTOCOL_ERROR = "protocol_error"    # JSON-RPC 错误响应
    INTERNAL_ERROR = "internal_error"    # 工具内部异常（原样转给模型）


@dataclass
class ToolResult:
    """工具调用结果：text 是返回给模型的文本，meta 是状态码/元信息。"""

    ok: bool
    text: str
    status: str = Status.OK
    meta: dict = field(default_factory=dict)

    def content(self) -> list[dict]:
        """MCP tools/call 的 content 数组（type + 数据字段，预留多模态扩展）。"""
        return [{"type": "text", "text": self.text or ""}]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text, "status": self.status, "meta": dict(self.meta)}


@dataclass
class AgentConfig:
    """一次工具会话的配置：决定「暴露哪些工具」与「怎么调用」。

    - role / round_index / planning_rounds：分阶段动态加载（阶段一按轮次，阶段二按角色）；
    - disabled_tools：配置黑名单（开发者显式禁用，优先级最高）；
    - read_only_mode：与约束层权限模式对应（plan=True 只读；写工具元数据供权限控制）；
    - max_retries / timeout_s：交给 MCP client（重试上限含首次，超时秒）。
    """

    role: str = "general"
    round_index: int = 0
    planning_rounds: int = 0
    disabled_tools: set[str] = field(default_factory=set)
    read_only_mode: bool = True
    max_retries: int = int(config.TOOL_CALL_MAX_RETRIES)
    timeout_s: float = float(config.TOOL_CALL_TIMEOUT_S)
    session_id: str = ""

    def __post_init__(self) -> None:
        # 未显式传黑名单时回落到系统配置（环境变量 TOOL_DISABLED）
        if not self.disabled_tools:
            self.disabled_tools = set(config.TOOL_DISABLED)

    def in_planning(self) -> bool:
        """是否仍处于阶段一（规划阶段）：前 planning_rounds 轮只暴露规划工具。"""
        return int(self.round_index) < int(self.planning_rounds)

    def visible_phase(self) -> str:
        return "planning" if self.in_planning() else "execution"


def estimate_planning_rounds(complexity: int | float) -> int:
    """按任务结构复杂度估算规划阶段轮数（原则二：正相关，且封顶防过度规划）。

    complexity 建议取任务结构步数/关键动作数（如拆解出的子任务个数）。
    公式：base + min(complexity, 8)；base 来自 config.TOOL_PLANNING_ROUNDS_BASE。
    """
    base = int(config.TOOL_PLANNING_ROUNDS_BASE)
    c = max(0, int(complexity or 0))
    return base + min(c, 8)
