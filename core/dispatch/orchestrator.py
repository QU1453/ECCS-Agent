# -*- coding: utf-8 -*-
"""调度控制-编排器（Orchestrator）：Server 的 /api/ask 统一入口。

流程（一次完整回答 = 认知层流水线）：
  perception.input（清洗 + 意图初判）
  → perception.context（五模块记忆 → 上下文块注入）
  → supervisor.answer（规则路由 → 专职智能体 ReAct）
  → 失败时按路由落本地规则兜底（research/listing 各自 classic_reply）
  → output.validator / output.formatter（清洗 + {reply, intent, data, route}）

supervisor 仍可直接被调用（agents 层独立可用），本编排器是认知层整合入口。
"""
from __future__ import annotations

from memory import get_memory
from agents import classic_reply
from agents.research_agent import classic_research_reply
from agents.listing_agent import classic_listing_reply
from agents.supervisor import Supervisor
from core.output.formatter import wrap
from core.perception.context import assemble_context
from core.perception.input import clean_input, intent_score

__all__ = ["Orchestrator"]

# 路由 → 本地兜底函数（无 Key / LLM 失败时保证演示链路完整）
_FALLBACKS = {
    "research": classic_research_reply,
    "listing": classic_listing_reply,
    "customer_service": classic_reply,
    "presales": classic_reply,
}


class Orchestrator:
    """认知层编排入口：问答流水线 + 上下文组装 + 兜底闭环。"""

    def __init__(self, supervisor: Supervisor | None = None):
        self.supervisor = supervisor

    def answer(self, question: str, session_id: str = "default",
               user_id: str = "default") -> dict:
        """完整问答流水线；返回 {reply, intent, data, route}（永不抛错）。"""
        q = clean_input(question)
        if not q:
            return wrap({"reply": ""}, route="")

        # 1) 感知：意图初判（与 supervisor 规则路由同口径，供上下文组装与统计）
        scores = intent_score(q)
        route = (self.supervisor or Supervisor)._route(q)  # 规则路由唯一权威
        # 登记该谈话最近一轮由谁处理（LLM 路径 supervisor 内部会再记一次，幂等）
        try:
            from memory import get_short_term

            get_short_term().record_turn(session_id, route, user_id=user_id)
        except Exception:  # noqa: BLE001 - 注册表故障不影响本轮回复
            pass

        # 2) 上下文组装：五模块记忆 → 系统上下文块（任一模块故障只降级该块）
        extra: list[str] = []
        try:
            mm = get_memory()
            if mm is not None:
                ac = assemble_context(mm, user_id=user_id, session_id=session_id,
                                      agent_name=f"{route}_agent", question=q)
                for key in ("rules", "facts", "kb_index", "window_topics", "hot_skills"):
                    if ac["blocks"].get(key):
                        extra.append(ac["blocks"][key])
        except Exception:  # noqa: BLE001 - 上下文组装失败不影响本轮问答
            extra = []

        # 3) 思考：主控调度 → 专职智能体 ReAct（失败自动退客服再试）
        result = None
        try:
            if self.supervisor is not None and self.supervisor.available:
                # 会话空（无 Key 模式）由 supervisor 内部回落；回答挂 route 标签
                result = self.supervisor.answer(q, session_id, extra_system=extra)
        except Exception:  # noqa: BLE001 - 网络/额度异常 → 本地兜底
            result = None
        if not result or not (result.get("reply") or "").strip():
            result = self._fallback(q, route)  # 本地规则兜底
            # 兜底模式下也把本轮对话写入短期记忆线程，保证「结束谈话」总结有原文可依
            try:
                self._record_fallback_turn(route, session_id, q, result.get("reply", ""))
            except Exception:  # noqa: BLE001
                pass

        # 4) 输出：清洗 + 标准契约
        return wrap(result, route=route if result is None or not result.get("route") else result.get("route"))

    @staticmethod
    def _record_fallback_turn(route: str, session_id: str, question: str, reply: str) -> None:
        """把兜底模式的问答写入该智能体的 checkpoint 线程（与 LLM 模式同口径）。"""
        from memory import agent_session_id, get_short_term

        stm = get_short_term()
        sid = agent_session_id(route, session_id)
        stm.add_message(sid, "user", question)
        if reply:
            stm.add_message(sid, "assistant", reply)

    @staticmethod
    def _fallback(q: str, route: str) -> dict:
        """按路由取对应智能体的本地规则兜底（research/listing 有专属 classic_reply）。"""
        fn = _FALLBACKS.get(route) or classic_reply
        try:
            out = fn(q)
        except Exception:  # noqa: BLE001 - 兜底异常再退通用兜底
            out = classic_reply(q)
        out = dict(out)
        out.setdefault("route", route)
        return out