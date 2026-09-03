# -*- coding: utf-8 -*-
"""智能体公共基类（ReActAgentBase）：封装 LangGraph ReAct 智能体的通用脚手架。

各专职智能体（agents/ 下文件）继承本类，只需提供：
- system_prompt：本智能体的系统提示词；
- tools：本智能体可调用的工具列表（来自 tools/ 包）；
- fallback(question)：无 Key / 调用失败时的本地规则兜底回复。

通用能力（本类实现）：
- LLM 初始化与失败降级（无 Key / 未装依赖 / 异常 → 记录 reason，退兜底模式）；
- 多轮记忆挂载：memory/ 提供的 checkpointer 按 thread_id 隔离会话；
- answer()：调用 LLM 并把运行结果整理为 {reply, intent, data}（含卡片信息提取）。
"""
from __future__ import annotations

from memory import get_checkpointer, thread_id_for
from tools import lookup_order, recommend_for

# ---- LangGraph 相关为可选依赖：装不上也能以"本地兜底模式"运行 -------------------
try:
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover - 离线环境 / 未安装依赖时
    _HAS_LANGGRAPH = False
    create_react_agent = None
    ChatOpenAI = None


def _build_react_agent(llm, tools, system_prompt: str, checkpointer=None):
    """兼容不同 langgraph 版本：1.x 用 prompt=，旧版用 messages_modifier/state_modifier=。"""
    for prompt_kw in ("prompt", "messages_modifier", "state_modifier"):
        try:
            return create_react_agent(
                model=llm, tools=tools, checkpointer=checkpointer, **{prompt_kw: system_prompt}
            )
        except TypeError:
            continue
    raise TypeError("create_react_agent 参数签名不兼容")


class ReActAgentBase:
    """ReAct 智能体基类。graph 为 None 表示运行在本地兜底模式。"""

    # 子类需覆盖：系统提示词 / 工具列表（类属性声明，构造时传入）
    system_prompt: str = ""
    tools: list = []

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
            # 多轮记忆：memory/ 提供的 checkpointer 按 thread_id 隔离会话
            self._graph = _build_react_agent(
                llm, self.tools, self.system_prompt, checkpointer=get_checkpointer()
            )
        except Exception as exc:  # noqa: BLE001
            self.reason = f"Agent 初始化失败（{exc.__class__.__name__}: {exc}）"

    @property
    def available(self) -> bool:
        """LLM 模式是否可用。"""
        return self._graph is not None

    def answer(self, question: str, session_id: str = "default") -> dict | None:
        """调用 LLM Agent，返回 {reply, intent, data}；失败返回 None（交由兜底）。

        多轮记忆：checkpointer 按 thread_id（= session_id）自动携带历史上下文，
        无需手动拼接 history。
        """
        if not self.available:
            return None
        try:
            config = {"configurable": {"thread_id": thread_id_for(session_id)}}
            # 记录本轮前的消息数：invoke 返回的是整条 thread 的全量消息，
            # 卡片提取只看本轮新增部分，避免把旧轮工具调用误当卡片
            state = self._graph.get_state(config)
            prev_count = len(state.values.get("messages", [])) if (state and state.values) else 0
            result = self._graph.invoke({"messages": [{"role": "user", "content": question}]}, config)
            return self._format_result(result, prev_count)
        except Exception:  # noqa: BLE001 - 网络/额度/格式异常都交给兜底
            return None

    # ---------- 内部：把 Agent 运行结果整理为结构化回复 ----------
    @staticmethod
    def _format_result(result: dict, prev_count: int = 0) -> dict:
        msgs = (result.get("messages") or [])[prev_count:]
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
                    data = {"items": card_items(recommend_for(args.get("keywords") or []))}
                elif name in ("query_order_info", "track_logistics"):
                    order = lookup_order(args.get("order_no", ""))
                    if order:
                        intent = "order"
                        data = order_card(order)
        return {"reply": reply, "intent": intent, "data": data}


# ---- 卡片数据结构化（与 ui/app.js 的渲染约定保持一致，各智能体兜底共用）-------------
def card_items(items: list[dict]) -> list[dict]:
    """商品列表 → 前端推荐卡片结构。"""
    return [{"name": p["name"], "price": p["price"], "img": p["img"]} for p in items]


def order_card(order: dict) -> dict:
    """订单详情 → 前端订单卡片结构。"""
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
