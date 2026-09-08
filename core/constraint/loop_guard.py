# -*- coding: utf-8 -*-
"""约束层-循环守卫（LoopGuard）：检测“智能体/用户在原地转圈”并主动打断。

三类循环信号（会话级，滚动窗口）：
1. 重复提问：用户连续 N 轮发送语义相同的输入（归一化后一致）；
2. 重复兜底：同一会话连续多轮命中本地兜底且路由不变（LLM 反复失败）；
3. 重复回复：连续 N 轮回复内容高度雷同（模型复读机）。

命中后不打断整条链路，而是给编排器一个“打断指令”：
- 重复提问/回复 → 返回固定提示（引导换问法 / 提供已答过的结论）；
- 重复兜底 → 标记该会话进入“LLM 熔断”状态，本轮直接走兜底（不再浪费调用）。

状态为进程内存；会话被清空时由编排器回调 reset()。
"""
from __future__ import annotations

from collections import defaultdict, deque

from memory.access import MemoryCaller

import config

__all__ = ["LoopGuard", "LoopSignal"]

# 参数槽位（config 可覆盖）
_REPEAT_Q = getattr(config, "CONSTRAINT_LOOP_REPEAT_Q", 3)      # 连续重复提问阈值
_REPEAT_A = getattr(config, "CONSTRAINT_LOOP_REPEAT_A", 3)      # 连续雷同回复阈值
_FALLBACK_TRIP = getattr(config, "CONSTRAINT_LOOP_FALLBACK_TRIP", 4)  # 连续兜底熔断阈值
_WINDOW = 6                                                             # 滚动窗口轮数

_LOOP_REPLY = (
    "注意到您已连续 {n} 轮发送相同的问题。刚才的结论仍然有效：{last}\n"
    "如果结果不符合预期，请换个说法或补充细节（例如具体品类、订单号），我会重新分析。"
)
_ECHO_REPLY = (
    "检测到本轮回复与前几轮高度重复（约束层·循环守卫）。"
    "请尝试换个问法，或提供更多背景信息以获得差异化回答。"
)
_TRIPPED_REPLY = (
    "当前会话的智能体链路多次失败已触发熔断，本轮使用离线规则答复。"
    "建议检查 API Key / 网络后重试，或点击「结束谈话」开启新会话。"
)


class LoopSignal:
    """循环守卫结论：tripped=False 时 pass；否则带 kind + 替代回复。"""

    def __init__(self, passed: bool, kind: str = "", reply: str = ""):
        self.passed = passed
        self.kind = kind     # repeat_question / repeat_reply / fallback_tripped
        self.reply = reply


def _normalize(text: str) -> str:
    """归一化：去空白/标点、转小写——判断“语义相同”的粗口径。"""
    import re

    return re.sub(r"[\s，。？！,.?!、·~～]+", "", str(text or "")).lower()


def _similar(a: str, b: str) -> bool:
    """雷同判断：归一化后前 80 字完全一致（客服回复通常开头固定，粗口径够用）。"""
    na, nb = _normalize(a)[:80], _normalize(b)[:80]
    return bool(na) and na == nb


class LoopGuard:
    """循环守卫子智能体：会话级滚动窗口，检测重复提问 / 雷同回复 / 兜底熔断。"""

    name = "loop_guard"
    caller = MemoryCaller("loop_guard", "L3")

    def __init__(self) -> None:
        # {session_id: {"q": deque[归一化问题], "a": deque[回复], "fb": 连续兜底次数}}
        self._state: dict[str, dict] = defaultdict(
            lambda: {"q": deque(maxlen=_WINDOW), "a": deque(maxlen=_WINDOW), "fb": 0}
        )
        self._tripped: set[str] = set()

    # ---- 输入前置：重复提问检测（LLM 调用之前，省一次无效推理）-------------------
    def check_input(self, question: str, session_id: str) -> LoopSignal:
        st = self._state[session_id]
        nq = _normalize(question)
        repeat = sum(1 for q in st["q"] if q == nq)
        if repeat >= _REPEAT_Q - 1:  # 窗口内已有 (阈值-1) 条相同 → 本轮是第 N 次
            last_reply = st["a"][-1] if st["a"] else "（本轮之前暂无回复）"
            return LoopSignal(False, "repeat_question",
                              _LOOP_REPLY.format(n=_REPEAT_Q, last=last_reply[:120]))
        return LoopSignal(True)

    # ---- 兜底熔断：是否已熔断（编排器在调 LLM 前询问）----------------------------
    def is_tripped(self, session_id: str) -> bool:
        return session_id in self._tripped

    def trip_reply(self) -> str:
        return _TRIPPED_REPLY

    # ---- 轮次记账：每轮完成后回调（问题 + 回复 + 是否走了兜底）-------------------
    def observe(self, session_id: str, question: str, reply: str, fallback: bool) -> LoopSignal:
        """记账并即时检测雷同回复 / 兜底熔断（返回信号供下一轮使用）。"""
        st = self._state[session_id]
        st["q"].append(_normalize(question))
        st["a"].append(str(reply or ""))
        if fallback:
            st["fb"] += 1
        else:
            st["fb"] = 0

        signal = LoopSignal(True)
        # 雷同回复检测（连续 _REPEAT_A 条相同开头）
        if len(st["a"]) >= _REPEAT_A:
            tail = list(st["a"])[-_REPEAT_A:]
            if all(_similar(tail[0], t) for t in tail[1:]):
                signal = LoopSignal(False, "repeat_reply", _ECHO_REPLY)
        # 兜底熔断（连续失败次数达阈值）
        if st["fb"] >= _FALLBACK_TRIP:
            self._tripped.add(session_id)
            signal = LoopSignal(False, "fallback_tripped", _TRIPPED_REPLY)
        return signal

    def session_status(self, session_id: str) -> dict:
        st = self._state.get(session_id, {})
        return {
            "session_id": session_id,
            "tripped": session_id in self._tripped,
            "consecutive_fallbacks": st.get("fb", 0) if st else 0,
            "window_questions": len(st.get("q", ())) if st else 0,
        }

    def reset(self, session_id: str) -> None:
        """会话清空时同步复位（熔断解除、窗口清空）。"""
        self._state.pop(session_id, None)
        self._tripped.discard(session_id)
