# -*- coding: utf-8 -*-
"""约束层聚合（ConstraintLayer）：规则约束 + 框架约束 + 循环守卫的统一门面。

编排器只与本类交互，三个子智能体的内部细节被收口：

    layer = get_constraint_layer()
    v = layer.pre_check(question, session_id)      # 输入前置：三道守卫 + 循环检测
    if not v.passed: return v.reply                 # 否决：直接返回拒绝话术
    ... 正常流水线（LLM / 兜底）...
    reply = layer.post_check(reply, session_id)     # 输出复查：脱敏 + 记账
    layer.extra_system()                            # 注入 LLM 的约束提示块

旁路容错：约束层自身任何异常都不阻断问答（降级为“无约束”继续），守卫失败不是故障。
"""
from __future__ import annotations

from memory.access import MemoryCaller

from .framework import FrameworkGuard
from .loop_guard import LoopGuard
from .rules import RuleGuard

__all__ = ["ConstraintLayer", "ConstraintVerdict", "get_constraint_layer"]


class ConstraintVerdict:
    """约束层统一结论：passed=False 时 reply 为可直接返回的替代回复。"""

    def __init__(self, passed: bool, kind: str = "", reply: str = ""):
        self.passed = passed
        self.kind = kind      # redline / input_overlong / rate_limited / turns_overbudget / repeat_question
        self.reply = reply


class ConstraintLayer:
    """约束层门面：pre_check（输入）→ 流水线 → post_check（输出）+ 状态复位。"""

    name = "constraint_layer"
    caller = MemoryCaller("constraint_layer", "L3")  # 约束层自身 = L3（只做拦截，不写业务记忆）

    def __init__(self) -> None:
        self.rules = RuleGuard()
        self.framework = FrameworkGuard()
        self.loop = LoopGuard()

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

    # ---- LLM 熔断询问：编排器在调 LLM 前问一次 ------------------------------------
    def llm_blocked(self, session_id: str) -> bool:
        try:
            return self.loop.is_tripped(session_id)
        except Exception:  # noqa: BLE001
            return False

    def trip_reply(self) -> str:
        return self.loop.trip_reply()

    # ---- LLM 注入块：规则约束的“软约束”版本（硬拦截之外的提示）--------------------
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
        except Exception:  # noqa: BLE001
            pass


# 进程级单例（与约束层局部工具共享实例语义一致）
_LAYER: ConstraintLayer | None = None


def get_constraint_layer() -> ConstraintLayer:
    """约束层单例入口（orchestrator / tools / 未来模块统一从这里取）。"""
    global _LAYER
    if _LAYER is None:
        _LAYER = ConstraintLayer()
    return _LAYER
