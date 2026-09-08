# -*- coding: utf-8 -*-
"""约束层-框架约束（FrameworkGuard）：结构性预算守卫，不关心内容只关心“量”。

守卫项（会话级状态）：
- 单轮输入长度：超长直接截断/拒绝（防 token 灌注与费用失控）；
- 会话频率：单位时间内的请求次数上限（防刷）；
- 会话总轮次预算：超预算后转“礼貌降级”回复（提示开新会话）。

状态为进程内存（会话粒度），与短期记忆 checkpoint 互不依赖；重启即清零（守卫语义允许）。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from memory.access import MemoryCaller

import config

__all__ = ["FrameworkGuard", "FrameworkVerdict"]

# 上限默认值（config 槽位可覆盖：约束层统一从 config 取参数）
_MAX_INPUT_CHARS = getattr(config, "CONSTRAINT_MAX_INPUT_CHARS", 4000)
_MAX_TURNS = getattr(config, "CONSTRAINT_MAX_SESSION_TURNS", 200)
_MAX_QPS_WINDOW = 10.0          # 频率窗口：10 秒
_MAX_QPS_COUNT = 20             # 窗口内最多 20 次

_OVERLONG_REPLY = (
    "您的输入过长（{length} 字，上限 {limit} 字），为保护服务稳定性已拦截。"
    "请精简后再发送，或分多轮描述您的需求。"
)
_OVERBUDGET_REPLY = (
    "本会话已累计 {turns} 轮对话，超出单会话预算（{limit} 轮）。"
    "建议点击「结束谈话」归档本会话后开启新会话继续。"
)
_TOO_FAST_REPLY = "您的发送频率过快，请稍作等待后再试（约束层·频率守卫）。"


class FrameworkVerdict:
    """框架约束结论：passed=False 时带 reason + 替代回复。"""

    def __init__(self, passed: bool, reason: str = "", reply: str = ""):
        self.passed = passed
        self.reason = reason
        self.reply = reply


class FrameworkGuard:
    """框架约束子智能体：长度 / 频率 / 轮次预算三道结构性守卫。"""

    name = "framework_guard"
    caller = MemoryCaller("framework_guard", "L3")

    def __init__(self) -> None:
        # 会话级状态：{session_id: deque[timestamp]} / {session_id: 轮次计数}
        self._hits: dict[str, deque] = defaultdict(deque)
        self._turns: dict[str, int] = defaultdict(int)

    # ---- 输入前置：三道守卫依次判定 ------------------------------------------------
    def check_input(self, text: str, session_id: str) -> FrameworkVerdict:
        # 1) 长度守卫
        if len(text or "") > _MAX_INPUT_CHARS:
            return FrameworkVerdict(
                False, "input_overlong",
                _OVERLONG_REPLY.format(length=len(text or ""), limit=_MAX_INPUT_CHARS),
            )
        # 2) 频率守卫（滑动窗口）
        now = time.monotonic()
        window = self._hits[session_id]
        while window and now - window[0] > _MAX_QPS_WINDOW:
            window.popleft()
        if len(window) >= _MAX_QPS_COUNT:
            return FrameworkVerdict(False, "rate_limited", _TOO_FAST_REPLY)
        window.append(now)
        # 3) 会话轮次预算
        if self._turns[session_id] >= _MAX_TURNS:
            return FrameworkVerdict(
                False, "turns_overbudget",
                _OVERBUDGET_REPLY.format(turns=self._turns[session_id], limit=_MAX_TURNS),
            )
        return FrameworkVerdict(True)

    # ---- 轮次记账：每完成一轮有效问答调用一次（由编排器回调）-----------------------
    def record_turn(self, session_id: str) -> int:
        self._turns[session_id] += 1
        return self._turns[session_id]

    def session_status(self, session_id: str) -> dict:
        """会话约束状态快照（局部工具 get_constraint_status 的数据源）。"""
        return {
            "session_id": session_id,
            "turns": self._turns.get(session_id, 0),
            "turns_limit": _MAX_TURNS,
            "input_limit": _MAX_INPUT_CHARS,
            "recent_rate": len(self._hits.get(session_id, ())),
        }

    def reset(self, session_id: str) -> None:
        """清空某会话的守卫状态（会话被真清空时同步调用）。"""
        self._hits.pop(session_id, None)
        self._turns.pop(session_id, None)
