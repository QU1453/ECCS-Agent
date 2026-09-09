# -*- coding: utf-8 -*-
"""约束层聚合（ConstraintLayer）：规则 + 框架 + 循环守卫 + 验证层 + 预算熔断的统一门面。

编排器 / 注册表只与本类交互，子守卫内部细节被收口：

    layer = get_constraint_layer()
    v = layer.pre_check(question, session_id)          # 输入前置：三道守卫
    if not v.passed: return v.reply                     # 否决：直接返回拒绝话术
    tv = layer.check_tool_call(name, params, caller)    # 工具前置：验证层 + 循环守卫
    if not tv.allowed: raise RegistryError(tv.message)  # block：错误提示返回 agent
    result = 执行工具(...)
    remind = layer.record_tool_result(...)              # 循环守卫记账 → system-reminder
    reply = layer.post_check(reply, session_id)         # 输出复查：脱敏 + 记账
    layer.llm_blocked(session_id)                       # 调 LLM 前问一次（熔断/预算）

整个约束层是纯程序框架：无 LLM 调用、不耗 token、单次检查微秒级；
旁路容错：约束层自身任何异常都不阻断问答（降级为"无约束"继续）。
"""
from __future__ import annotations

import threading

from memory.access import MemoryCaller

from .budget import BudgetGuard
from .framework import FrameworkGuard
from .loop_guard import LoopGuard
from .rules import RuleGuard
from .tool_loop import ToolLoopGuard
from .validator import ToolValidator

__all__ = ["ConstraintLayer", "ConstraintVerdict", "get_constraint_layer",
           "set_current_session", "get_current_session"]

# ---- 当前会话线程变量：agent 直连工具包装器据此归并循环守卫状态 ----------------------
_session_ctx = threading.local()


def set_current_session(session_id: str) -> None:
    _session_ctx.session = str(session_id or "")


def ensure_current_session(session_id: str) -> None:
    """仅在线程变量为空时兜底设置（编排器已设置原始 session_id 时不覆盖）。"""
    if not getattr(_session_ctx, "session", ""):
        _session_ctx.session = str(session_id or "")


def get_current_session() -> str:
    return getattr(_session_ctx, "session", "") or "default"


class ConstraintVerdict:
    """约束层统一结论：passed=False 时 reply 为可直接返回的替代回复。"""

    def __init__(self, passed: bool, kind: str = "", reply: str = ""):
        self.passed = passed
        self.kind = kind      # redline / input_overlong / rate_limited / turns_overbudget / repeat_question
        self.reply = reply


class ToolCallVerdict:
    """工具调用验证结论：allowed=False 时 message 是返回给 agent 的错误提示。"""

    def __init__(self, allowed: bool, kind: str = "ok", message: str = ""):
        self.allowed = allowed
        self.kind = kind      # ok / permission / path / network / danger / hook / loop_guard
        self.message = message

    def __repr__(self) -> str:
        return f"ToolCallVerdict(allowed={self.allowed}, kind={self.kind!r})"


class ConstraintLayer:
    """约束层门面：输入前置 → 工具验证 → LLM 熔断 → 输出复查 + 状态复位。"""

    name = "constraint_layer"
    caller = MemoryCaller("constraint_layer", "L3")  # 约束层自身 = L3（只做拦截，不写业务记忆）

    def __init__(self) -> None:
        self.rules = RuleGuard()
        self.framework = FrameworkGuard()
        self.loop = LoopGuard()
        self.validator = ToolValidator()
        self.tool_loop = ToolLoopGuard()
        self.budget = BudgetGuard()

    # ---- 输入前置：规则红线 → 框架预算 → 重复提问（顺序 = 便宜规则优先）------------
    def pre_check(self, question: str, session_id: str) -> ConstraintVerdict:
        try:
            v = self.rules.check_input(question)
            if not v.passed:
                return ConstraintVerdict(False, "redline", v.reply)
            f = self.framework.check_input(question, session_id)
            if not f.passed:
                return ConstraintVerdict(False, f.reason, f.reply)
            l = self.loop.check_input(question, session_id)
            if not l.passed:
                return ConstraintVerdict(False, l.kind, l.reply)
        except Exception:  # noqa: BLE001 - 约束层故障不阻断问答（旁路容错）
            return ConstraintVerdict(True)
        return ConstraintVerdict(True)

    # ---- 工具前置：验证层四道检查 + 循环守卫（agent 直连与全局注册表共用）------------
    def check_tool_call(self, name: str, params: dict,
                        caller: MemoryCaller | None = None) -> ToolCallVerdict:
        try:
            # 系统内部调用（L9）可信，跳过验证；循环守卫也不记（初始化/演示数据不占预算）
            if caller is not None and caller.level == "L9":
                return ToolCallVerdict(True)
            v = self.validator.check(name, params, caller)
            if not v.allowed:
                return ToolCallVerdict(False, v.kind, v.message)
            blocked, message = self.tool_loop.check(name, params, self._loop_key(caller))
            if blocked:
                return ToolCallVerdict(False, "loop_guard", message)
        except Exception:  # noqa: BLE001 - 验证层故障放行（不阻断主链路）
            return ToolCallVerdict(True)
        return ToolCallVerdict(True)

    # ---- 工具后置：记账 + 软干预提醒（返回空串或 <system-reminder> 文本）--------------
    def record_tool_result(self, name: str, params: dict, ok: bool, result: str,
                           caller: MemoryCaller | None = None) -> str:
        try:
            if caller is not None and caller.level == "L9":
                return ""
            return self.tool_loop.record(name, params, ok, result, self._loop_key(caller))
        except Exception:  # noqa: BLE001
            return ""

    def _loop_key(self, caller: MemoryCaller | None) -> str:
        return (caller.session_id if caller and caller.session_id else "") \
            or get_current_session()

    # ---- 输出复查：脱敏 + 会话记账（返回净化后的回复）-----------------------------
    def post_check(self, reply: str, session_id: str, question: str = "",
                   fallback: bool = False) -> str:
        try:
            clean = self.rules.sanitize_output(reply)
            # 兜底熔断 / 雷同回复信号：下一轮 pre_check / is_tripped 生效
            self.loop.observe(session_id, question, clean, fallback=fallback)
            self.framework.record_turn(session_id)
            return clean
        except Exception:  # noqa: BLE001
            return reply

    # ---- LLM 熔断询问：编排器在调 LLM 前问一次（循环熔断 / token 预算耗尽）----------
    def llm_blocked(self, session_id: str) -> bool:
        try:
            return self.loop.is_tripped(session_id) or self.budget.is_over(session_id)
        except Exception:  # noqa: BLE001
            return False

    # ---- 预算记账：编排器拿到真实 usage（input/output token）后调用 -------------------
    def record_llm_usage(self, session_id: str, input_tokens: int, output_tokens: int) -> None:
        try:
            self.budget.record(session_id, input_tokens, output_tokens)
        except Exception:  # noqa: BLE001
            pass

    def blocked_reply(self, session_id: str) -> str:
        """熔断时的提示语：预算耗尽给出用量明细，否则给循环熔断话术。"""
        try:
            if self.budget.is_over(session_id):
                return self.budget.over_reply(session_id)
        except Exception:  # noqa: BLE001
            pass
        return self.loop.trip_reply()

    # ---- LLM 注入块：规则约束的"软约束"版本（硬拦截之外的提示）--------------------
    def extra_system(self) -> str:
        try:
            return self.rules.extra_system()
        except Exception:  # noqa: BLE001
            return ""

    # ---- 会话复位：真清空时由编排器回调 -------------------------------------------
    def reset(self, session_id: str) -> None:
        try:
            self.framework.reset(session_id)
            self.loop.reset(session_id)
            self.tool_loop.reset(session_id)
            self.budget.reset(session_id)
        except Exception:  # noqa: BLE001
            pass

    # ---- 全量状态快照（约束层状态工具 / 调试后台用）----------------------------------
    def session_snapshot(self, session_id: str) -> dict:
        try:
            return {
                "framework": self.framework.session_status(session_id),
                "loop": self.loop.session_status(session_id),
                "tool_loop": self.tool_loop.session_status(session_id),
                "budget": self.budget.status(session_id),
                "permission_mode": str(__import__("config").AGENT_PERMISSION_MODE),
            }
        except Exception:  # noqa: BLE001
            return {}


# 进程级单例（与约束层局部工具共享实例语义一致）
_LAYER: ConstraintLayer | None = None


def get_constraint_layer() -> ConstraintLayer:
    """约束层单例入口（orchestrator / registry / tools / agent 包装器统一从这里取）。"""
    global _LAYER
    if _LAYER is None:
        _LAYER = ConstraintLayer()
    return _LAYER
