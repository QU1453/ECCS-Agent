# -*- coding: utf-8 -*-
"""约束层-循环守卫·agent 循环版（ToolLoopGuard）：防止工具调用在原地打转。

与 loop_guard.py（会话级：重复提问/回复/兜底熔断）互补，本守卫挂在工具调用链路上：
- 工具总调用量：单会话累计达上限 → 熔断，后续调用全部拒绝（硬终止）；
- 连续失败次数：连续抛错达阈值 → 熔断（硬终止）；
- 完全相同调用（触发粒度最精确）：保留最近 N 条调用记录，签名 =
  MD5(工具名+参数) 前 12 位 + 执行结果前 20 字符，拼接而成；同参数又同结果 = 真重复；
  第 2 次命中注入 system-reminder（软干预），第 3 次起直接拦截；
- 交替循环：工具名滑窗检测 [A,B]×3 二元模式（如 read→edit→read→edit→…），
  命中注入 system-reminder 提示先批量定位再统一修改（软干预）。

软干预实现：check/record 返回 message，由调用方以 <system-reminder> 形式追加到
工具结果（进入消息列表），agent 下一轮即读到；纯程序框架，不耗 token。
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict, deque

import config

__all__ = ["ToolLoopGuard"]

_IDENTICAL_HINT = (
    "检测到与最近完全相同的工具调用（同参数且同结果），请勿重复调用："
    "直接基于已有结果继续任务，或换一种方式推进。"
)
_ALTERNATE_HINT = (
    "检测到在工具 {a} 与 {b} 之间反复交替（[A,B]×3）。内容不足以一次完成任务——"
    "请先用检索/列表类工具（grep/glob 式批量查询）一次性定位全部目标，再统一执行修改。"
)
_MAX_CALLS_REPLY = (
    "工具调用量已达本会话上限（{n} 次），循环守卫已熔断后续调用。"
    "请直接基于已收集的信息作答。"
)
_MAX_FAILS_REPLY = (
    "工具连续失败 {n} 次，循环守卫已熔断。请检查参数后重试，或改用其他方式完成任务。"
)
_IDENTICAL_BLOCK_REPLY = (
    "检测到第 {n} 次发起完全相同的调用（同参数同结果），已被阻止。"
    "请勿原地重复，直接基于已有结果作答。"
)


def _signature(name: str, params: dict) -> str:
    """参数签名：MD5(工具名 + 规范化参数) 前 12 位。"""
    canonical = json.dumps(params or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(f"{name}{canonical}".encode("utf-8")).hexdigest()[:12]


def _reminder(message: str) -> str:
    """软干预消息的注入格式（追加在工具结果后，随 ToolMessage 进入消息列表）。"""
    return f"\n\n<system-reminder>{message}</system-reminder>"


class ToolLoopGuard:
    """agent 循环守卫：会话级计数 + 滚动签名窗口，纯内存、线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {session_key: {"calls", "fails", "recent": deque[(psig, full_sig)],
        #                "names": deque[str], "alt_flag", "stopped"}}
        self._state: dict[str, dict] = defaultdict(self._new_state)

    @staticmethod
    def _new_state() -> dict:
        window = max(int(config.TOOL_LOOP_IDENTICAL_WINDOW), 10)
        return {
            "calls": 0,
            "fails": 0,
            "recent": deque(maxlen=window),   # (参数签名, 完整签名)
            "names": deque(maxlen=12),        # 工具名滑窗（交替检测）
            "alt_flag": False,                # 交替模式提醒只发一次，模式打破后复位
            "stopped": False,                 # 熔断标记（总量/连败）
            "stop_reason": "",                # 熔断原因：calls / fails（决定话术）
        }

    # ---- 执行前检查：熔断 / 总量 / 连败 / 第三次相同调用 ------------------------------
    def check(self, name: str, params: dict, session_key: str) -> tuple[bool, str]:
        """返回 (blocked, message)。blocked=True 时调用方必须拒绝执行。"""
        with self._lock:
            st = self._state[str(session_key or "default")]
            if st["stopped"]:
                return True, self._stop_reply(st)
            if st["calls"] >= int(config.TOOL_LOOP_MAX_CALLS):
                st["stopped"], st["stop_reason"] = True, "calls"
                return True, self._stop_reply(st)
            if st["fails"] >= int(config.TOOL_LOOP_MAX_CONSEC_FAILS):
                st["stopped"], st["stop_reason"] = True, "fails"
                return True, self._stop_reply(st)
            psig = _signature(name, params)
            dup = sum(1 for p, _ in st["recent"] if p == psig)
            if dup >= 2:  # 窗口内已有 2 次同参调用（结果也相同）→ 第 3 次硬拦截
                return True, _IDENTICAL_BLOCK_REPLY.format(n=dup + 1)
            return False, ""

    # ---- 执行后记账：更新计数 / 签名窗口 / 生成软干预提醒 ------------------------------
    def record(self, name: str, params: dict, ok: bool, result: str,
               session_key: str) -> str:
        """记账并返回 system-reminder 文本（无干预时返回空串）。"""
        with self._lock:
            st = self._state[str(session_key or "default")]
            st["calls"] += 1
            st["fails"] = 0 if ok else st["fails"] + 1
            psig = _signature(name, params)
            full = psig + str(result or "")[:20]
            st["recent"].append((psig, full))
            st["names"].append(name or "")

            reminders: list[str] = []
            same = sum(1 for _, f in st["recent"] if f == full)
            if same >= 2:  # 本次 + 窗口内历史 1 次 = 完全相同的第 2 次 → 软提醒
                reminders.append(_IDENTICAL_HINT)
            alt = self._alternate_pair(st["names"])
            if alt and not st["alt_flag"]:
                st["alt_flag"] = True
                reminders.append(_ALTERNATE_HINT.format(a=alt[0], b=alt[1]))
            elif not alt:
                st["alt_flag"] = False
            if st["calls"] >= int(config.TOOL_LOOP_MAX_CALLS) and not st["stopped"]:
                st["stopped"], st["stop_reason"] = True, "calls"
            if st["fails"] >= int(config.TOOL_LOOP_MAX_CONSEC_FAILS) and not st["stopped"]:
                st["stopped"], st["stop_reason"] = True, "fails"
            return _reminder("；".join(reminders)) if reminders else ""

    @staticmethod
    def _stop_reply(st: dict) -> str:
        """按熔断原因返回对应话术（连败 ≠ 总量上限）。"""
        if st.get("stop_reason") == "fails":
            return _MAX_FAILS_REPLY.format(n=st["fails"])
        return _MAX_CALLS_REPLY.format(n=st["calls"])

    @staticmethod
    def _alternate_pair(names: deque) -> tuple[str, str] | None:
        """滑窗尾部 [A,B,A,B,A,B]（A≠B）二元交替模式检测。"""
        tail = [n for n in names if n][-6:]
        if len(tail) < 6 or tail[0] == tail[1]:
            return None
        if all(tail[i] == tail[i % 2] for i in range(6)):
            return tail[0], tail[1]
        return None

    # ---- 状态与复位 -------------------------------------------------------------------
    def session_status(self, session_key: str) -> dict:
        with self._lock:
            st = self._state.get(str(session_key or "default"), self._new_state())
            return {
                "tool_calls": st["calls"],
                "consecutive_failures": st["fails"],
                "max_calls": int(config.TOOL_LOOP_MAX_CALLS),
                "max_consecutive_failures": int(config.TOOL_LOOP_MAX_CONSEC_FAILS),
                "stopped": st["stopped"],
                "window_size": len(st["recent"]),
            }

    def reset(self, session_key: str) -> None:
        with self._lock:
            self._state.pop(str(session_key or "default"), None)
