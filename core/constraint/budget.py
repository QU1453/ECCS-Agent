# -*- coding: utf-8 -*-
"""约束层-预算熔断（BudgetGuard）：token 分段预算 + 会话累计消耗 + 熔断。

两块职责：
1. 上下文五段分配（每次组装上下文时按比例封顶，避免某一段吃满窗口）：
      输出预留 15% ｜ 系统提示词 10% ｜ 长期记忆 5% ｜ 当前任务 20% ｜ 历史会话 50%
   （历史会话 = 短期记忆话题 + 知识库索引；checkpoint 历史另由短期记忆压缩器守卫）
2. 会话累计预算：每次 LLM 调用后记账真实 usage（token + 估算金额），
   超出 SESSION_TOKEN_BUDGET / SESSION_COST_BUDGET_CNY 即熔断——
   编排器在调 LLM 前询问 is_over，命中则跳过 LLM 转离线答复。

纯内存记账 + 字符估算，无 LLM 调用、不耗 token；旁路容错由调用方保证。
"""
from __future__ import annotations

import threading
from collections import defaultdict

from memory.long_term.chunker import estimate_tokens

import config

__all__ = ["BudgetGuard"]

# 上下文块 → 五段预算的归属映射（在两段间拆分比例）
_LONG_SPLIT = (0.6, 0.4)     # facts / hot_skills
_HIST_SPLIT = (0.4, 0.6)     # kb_index / window_topics

_OVER_REPLY = (
    "本会话的 token 预算已耗尽（已用 {used:,} / 预算 {budget:,} token），"
    "为控制成本本轮改用离线规则答复。建议点击「结束谈话」后开启新会话继续。"
)


class BudgetGuard:
    """预算守卫：分段封顶 + 会话累计记账 + 熔断判定。线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage: dict[str, dict] = defaultdict(
            lambda: {"input": 0, "output": 0, "cost": 0.0, "llm_calls": 0})

    # ---- 五段分配：返回各段 token 上限 ------------------------------------------------
    @staticmethod
    def allocation(total: int | None = None) -> dict[str, int]:
        total = int(total or config.CONTEXT_TOKEN_GUARD)
        pct = {
            "output": config.BUDGET_PCT_OUTPUT,
            "system": config.BUDGET_PCT_SYSTEM,
            "long_term": config.BUDGET_PCT_LONG_TERM,
            "task": config.BUDGET_PCT_TASK,
            "history": config.BUDGET_PCT_HISTORY,
        }
        return {seg: max(0, int(total * p / 100)) for seg, p in pct.items()}

    # ---- 上下文块封顶：按归属映射裁剪（超限从尾部截断，宁短勿超）------------------------
    def trim_context_blocks(self, blocks: dict[str, str]) -> dict[str, str]:
        caps = self.allocation()
        limits = {
            "rules": caps["system"],
            "hot_skills": int(caps["long_term"] * _LONG_SPLIT[1]),
            "facts": int(caps["long_term"] * _LONG_SPLIT[0]),
            "kb_index": int(caps["history"] * _HIST_SPLIT[0]),
            "window_topics": int(caps["history"] * _HIST_SPLIT[1]),
        }
        out = dict(blocks)
        for name, cap in limits.items():
            text = out.get(name) or ""
            if text and estimate_tokens(text) > cap:
                out[name] = _trim_to_cap(text, cap)
        return out

    # ---- 会话记账：LLM 调用后写入真实 usage（agents/base._telemetry 的口径）------------
    def record(self, session_id: str, input_tokens: int, output_tokens: int) -> dict:
        with self._lock:
            u = self._usage[str(session_id or "default")]
            u["input"] += max(0, int(input_tokens or 0))
            u["output"] += max(0, int(output_tokens or 0))
            u["llm_calls"] += 1
            u["cost"] = (
                u["input"] / 1e6 * config.PRICE_INPUT_CNY_PER_M
                + u["output"] / 1e6 * config.PRICE_OUTPUT_CNY_PER_M
            )
            return dict(u)

    # ---- 熔断判定：编排器在调 LLM 前询问 ------------------------------------------------
    def is_over(self, session_id: str) -> bool:
        u = self.status(str(session_id or "default"))
        if u["tokens"] >= int(config.SESSION_TOKEN_BUDGET):
            return True
        cost_budget = float(config.SESSION_COST_BUDGET_CNY)
        return cost_budget > 0 and u["cost"] >= cost_budget

    def over_reply(self, session_id: str) -> str:
        u = self.status(str(session_id or "default"))
        return _OVER_REPLY.format(used=u["tokens"], budget=int(config.SESSION_TOKEN_BUDGET))

    def status(self, session_id: str) -> dict:
        with self._lock:
            u = dict(self._usage.get(str(session_id or "default"),
                                     {"input": 0, "output": 0, "cost": 0.0, "llm_calls": 0}))
        u["tokens"] = u["input"] + u["output"]
        u["token_budget"] = int(config.SESSION_TOKEN_BUDGET)
        u["cost_budget"] = float(config.SESSION_COST_BUDGET_CNY)
        return u

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._usage.pop(str(session_id or "default"), None)


def _trim_to_cap(text: str, cap_tokens: int) -> str:
    """按估算 token 截断到上限内（按行保留；首行即超限时逐字符硬截断，宁短勿超）。"""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = estimate_tokens(line)
        if used + cost <= cap_tokens:
            kept.append(line)
            used += cost
            continue
        if not kept:
            kept.append(_cut_line_to_cap(line, cap_tokens))
        break
    return "".join(kept).rstrip() + "\n…（预算封顶截断）"


def _cut_line_to_cap(line: str, cap_tokens: int) -> str:
    """单行超过上限时的硬截断：增量计数（CJK 记 1、拉丁记 1/4），O(n)。"""
    cjk = non = 0
    for idx, ch in enumerate(line):
        if ("\u2e80" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff"
                or "\uff00" <= ch <= "\uffef"):
            cjk += 1
        else:
            non += 1
        if cjk + non // 4 >= cap_tokens:
            return line[:idx]
    return line
