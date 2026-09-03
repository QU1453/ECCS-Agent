# -*- coding: utf-8 -*-
"""ECCS Agent：LangGraph ReAct 智能体（OpenAI 兼容接口）。

结构：
- 配置了 OPENAI_API_KEY 时：走真实 LLM，Agent 自主调用订单/物流/售后/推荐工具后生成回复；
- 未配置 Key 或调用失败时：自动退回本地规则引擎（tools + classic_reply），保证演示不断线。

安全约定：本模块从不保存密钥，OPENAI_API_KEY 只从环境变量 / .env 读取。
"""
from __future__ import annotations

import re

from tools import (
    handle_return,
    lookup_order,
    query_order_info,
    recommend_for,
    recommend_products,
    register_return,
    track_logistics,
)

# ---- LangGraph 相关为可选依赖：装不上也能以"本地兜底模式"运行 -------------------
try:
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover - 离线环境 / 未安装依赖时
    _HAS_LANGGRAPH = False
    create_react_agent = None
    ChatOpenAI = None


def _build_react_agent(llm, tools):
    """兼容不同 langgraph 版本：1.x 用 prompt=，旧版用 messages_modifier/state_modifier=。"""
    try:
        return create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
    except TypeError:
        try:
            return create_react_agent(model=llm, tools=tools, messages_modifier=SYSTEM_PROMPT)
        except TypeError:
            return create_react_agent(model=llm, tools=tools, state_modifier=SYSTEM_PROMPT)

SYSTEM_PROMPT = """你是「ECCS」跨境电商智能客服 Agent，面向海外（日本）消费者、当前以中文演示。

工作方式：根据用户问题，自主决定是否调用工具获取事实，再用自然语言作答：
- 查订单/物流 → 先调用 query_order_info / track_logistics（订单号形如 2026081200012）；
- 办退换货/退款 → 先调用 handle_return；
- 求推荐商品 → 调用 recommend_products，并结合工具返回的商品特点给出理由；
- 用户没说订单号：礼貌询问，不要编造单号。

回复要求：
1. 简洁、友好、像真人客服；使用与用户相同的语言（中文或日本語）；
2. 引用工具返回的金额、地点、时间等事实，不得虚构；
3. 若工具返回未找到，如实说明并引导用户核对订单号；
4. 不要向用户暴露工具名称、JSON 等内部实现细节。"""


class Agent:
    """LangGraph 客服智能体。graph 为 None 表示运行在本地兜底模式。"""

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
    ):
        self.model = model
        self.reason = None  # 初始化失败/未配置的原因（供日志展示）
        self._graph = None
        if not api_key:
            self.reason = "未配置 OPENAI_API_KEY，运行于本地规则兜底模式"
            return
        if not _HAS_LANGGRAPH:
            self.reason = "未安装 langgraph/langchain-openai，运行于本地规则兜底模式"
            return
        try:
            llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url or None, temperature=0.3)
            tools = [query_order_info, track_logistics, handle_return, recommend_products]
            self._graph = _build_react_agent(llm, tools)
        except Exception as exc:  # noqa: BLE001
            self.reason = f"Agent 初始化失败（{exc.__class__.__name__}: {exc}）"

    @property
    def available(self) -> bool:
        return self._graph is not None

    def answer(self, question: str, history: list[dict] | None = None) -> dict | None:
        """调用 LLM Agent，返回 {reply, intent, data}；失败返回 None（交由兜底）。"""
        if not self.available:
            return None
        try:
            messages = [m for m in (history or []) if m.get("content")]
            messages.append({"role": "user", "content": question})
            result = self._graph.invoke({"messages": messages})
            return self._format_result(result)
        except Exception:  # noqa: BLE001 - 网络/额度/格式异常都交给兜底
            return None

    # ---------- 内部：把 Agent 运行结果整理为结构化回复 ----------
    @staticmethod
    def _format_result(result: dict) -> dict:
        msgs = result.get("messages") or []
        reply = ""
        intent, data = "none", None
        for m in reversed(msgs):
            if getattr(m, "content", ""):
                reply = m.content or ""
                break

        # 从本轮工具调用中还原"卡片信息"，让前端渲染订单 / 推荐卡片
        for m in msgs:
            calls = getattr(m, "tool_calls", None) or []
            for c in calls:
                name, args = c.get("name", ""), c.get("args") or {}
                if name == "recommend_products":
                    intent = "recommend"
                    data = {
                        "items": [
                            {"name": p["name"], "price": p["price"], "img": p["img"]}
                            for p in recommend_for(args.get("keywords") or [])
                        ]
                    }
                elif name in ("query_order_info", "track_logistics"):
                    order = lookup_order(args.get("order_no", ""))
                    if order:
                        intent = "order"
                        data = {
                            "order_no": order["order_no"],
                            "carrier": order["carrier"],
                            "paid_at": order["paid_at"],
                            "qty": order["qty"],
                            "total": order["total"],
                            "steps": order["steps"],
                            "product": {
                                "name": order["product"]["name"],
                                "price": order["product"]["price"],
                                "img": order["product"]["img"],
                            },
                        }
        return {"reply": reply, "intent": intent, "data": data}


# ============================================================================
# 本地兜底路由：未配置 Key / 后端异常 / 纯静态预览时，给出与前端演示一致的体验
# ============================================================================
def classic_reply(q: str) -> dict:
    """关键词路由 + 结构化卡片数据，返回 {reply, intent, data}。"""
    s = q.lower()

    if re.search(r"物流|快递|到哪|发货|订单|单号|签收", s):
        order = lookup_order("2026081200012")
        p = order["product"]
        reply = (
            f"您的订单当前处于 <span class='em'>「{order['location']}」</span>，"
            f"预计{order['eta']}，到达派送点会有短信提醒～"
        )
        return {"reply": reply, "intent": "order", "data": _order_card(order)}

    if re.search(r"退|换|退款|售后|质量|坏了", s):
        r = register_return("2026081200012", "质量问题")
        reply = (
            f"可以的～该订单在 <span class='em'>7 天无理由</span> 期限内，"
            f"已为您登记售后单 <span class='em'>{r['receipt']}</span>。<br>"
            "① 仅退款（原路退回）　② 换新（免运费优先发）　③ 退货退款"
        )
        return {"reply": reply, "intent": "none", "data": None}

    if re.search(r"推荐|耳机|键盘|保温杯|充电宝|什么好|哪款", s):
        items = recommend_for(["耳机", "键盘", "充电宝"])
        reply = "根据您的需求推荐这 3 款高口碑好物，最推荐第一款，支持主动降噪、佩戴很舒适："
        return {"reply": reply, "intent": "recommend", "data": {"items": _card_items(items)}}

    if re.search(r"在吗|你好|哈喽|hi|hello|こんにちは", s):
        return {
            "reply": "您好呀～我是 ECCS 的 AI 智能客服，可以帮您查物流、办退换、挑商品，请直接告诉我需求即可～",
            "intent": "none",
            "data": None,
        }

    return {
        "reply": "收到～这个问题我可以处理。<br>您可以试试问我：<span class='em'>订单到哪了 / 怎么退货 / 推荐一款耳机</span>。",
        "intent": "none",
        "data": None,
    }


# ---- 卡片数据结构化（与 ui/app.js 的渲染约定保持一致）-------------------------
def _card_items(items: list[dict]) -> list[dict]:
    return [{"name": p["name"], "price": p["price"], "img": p["img"]} for p in items]


def _order_card(order: dict) -> dict:
    p = order["product"]
    return {
        "order_no": order["order_no"],
        "carrier": order["carrier"],
        "paid_at": order["paid_at"],
        "qty": order["qty"],
        "total": order["total"],
        "steps": order["steps"],
        "product": {"name": p["name"], "price": p["price"], "img": p["img"]},
    }
