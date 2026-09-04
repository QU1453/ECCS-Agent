# -*- coding: utf-8 -*-
"""智能体公共基类（ReActAgentBase）：封装 LangGraph ReAct 智能体的通用脚手架。

各专职智能体（agents/ 下文件）继承本类，只需提供：
- system_prompt：本智能体的系统提示词；
- tools：本智能体可调用的工具列表（来自 tools/ 包）。

兜底说明：无 Key / 调用失败时各智能体模块提供模块级兜底函数
（如 customer_service.classic_reply），由 supervisor / server 调用，
不走本基类。

通用能力（本类实现）：
- LLM 初始化与失败降级（无 Key / 未装依赖 / 异常 → 记录 reason，退兜底模式）；
- 多轮记忆挂载：memory/ 提供的 checkpointer 按 thread_id 隔离会话；
- answer()：调用 LLM 并把运行结果整理为 {reply, intent, data}（含卡片信息提取）。
"""
from __future__ import annotations

import re

from config import MODEL_ID
from memory import get_short_term, thread_id_for
from tools import lookup_order, recommend_for

# ---- 日语识别与回复提示：命中假名即视为日语用户，LLM 回复切换为日语敬体 --------------
_JA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")  # 平假名 / 片假名
# 仅汉字无法区分中日（如"注文"），假名是日语的强特征；纯中文/英文不命中
_JA_REPLY_HINT = (
    "本次对话用户使用日语。请用日语回复，并遵守日本电商客服敬语规范：\n"
    "- 全程使用丁寧語・敬語（です・ます調），称呼顾客为「お客様」；\n"
    "- 常用服务用语：「かしこまりました」「恐れ入りますが」「お問い合わせいただきありがとうございます」；\n"
    "- 金额用「円」、日期用日本书写习惯；专有名词（商品名、配送公司）保持原文。"
)


def is_japanese(text: str) -> bool:
    """是否日语用户输入（含假名即视为日语；供 LLM 提示与兜底双语回复共用）。"""
    return bool(_JA_RE.search(text or ""))

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
        model: str = MODEL_ID,  # 默认值统一来自 config.py（glm-5.3-flash），不在各处硬编码
    ):
        self.model = model
        self.reason = None  # 初始化失败/未配置的原因（供日志展示）
        self._graph = None
        self._stm = None    # 进程级单例短期记忆（压缩与推理共享同一 saver）
        if not api_key:
            self.reason = "未配置 OPENAI_API_KEY，运行于本地规则兜底模式"
            return
        if not _HAS_LANGGRAPH:
            self.reason = "未安装 langgraph/langchain-openai，运行于本地规则兜底模式"
            return
        try:
            llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url or None, temperature=0.3)
            # 多轮记忆：memory/ 提供的 checkpointer 按 thread_id 隔离会话；
            # 压缩器注入同一 llm，超阈值裁剪时滚动摘要会回流进线程（不丢上下文）
            self._stm = get_short_term(llm=llm)
            self._graph = _build_react_agent(
                llm, self.tools, self.system_prompt, checkpointer=self._stm.saver
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
            # 日语用户：注入一条系统提示，要求本轮及后续以日语敬体回复（中文/英文不受影响）
            if is_japanese(question):
                result = self._graph.invoke(
                    {"messages": [{"role": "system", "content": _JA_REPLY_HINT},
                                  {"role": "user", "content": question}]},
                    config,
                )
                # 系统提示已随历史持久化，后续轮次无需重复注入
            else:
                result = self._graph.invoke({"messages": [{"role": "user", "content": question}]}, config)
            formatted = self._format_result(result, prev_count)
            try:
                # 每轮推理后触发压缩检查：阈值内只多一次 get_state，零 LLM 开销；
                # 超阈值时裁剪旧消息并把滚动摘要回流进线程，下一轮自动携带
                self._stm.maybe_compress(session_id)
            except Exception:  # noqa: BLE001 - 压缩失败不影响本轮回复
                pass
            return formatted
        except Exception as exc:  # noqa: BLE001 - 网络/额度/格式异常都交给兜底
            # 降级必须可见：余额不足 / Key 失效 / 网络异常时在服务端日志里给出原因，
            # 避免表现为"智能体说固定话术"却查不到为什么（如 GLM 余额用完 → 401/429）
            print(f"[Agent] LLM 调用失败，转本地兜底（{exc.__class__.__name__}: {exc}）")
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
