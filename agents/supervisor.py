# -*- coding: utf-8 -*-
"""主控智能体（Supervisor）：对外统一入口，对内调度专职智能体。

当前注册：
- customer_service：客服智能体（订单 / 物流 / 售后）；
- presales：售前导购智能体（商品咨询 / 推荐）。

多智能体扩展方法：
1. 在 agents/ 下新增专职智能体文件（参考 presales.py，继承 agents/base.py）；
2. 在下方 specialists 注册表加一行；
3. 在 _route() 中补充该智能体的路由规则（现为规则路由，后续可升级 LLM 路由）。
"""
from __future__ import annotations

import re

from config import MODEL_ID

from .customer_service import CustomerServiceAgent, classic_reply
from .presales import PreSalesAgent

# 售前导购的路由关键词（中日双语）：命中即分流给 presales
# 注意：订单 / 物流 / 售后关键词要放在客服路由里优先判断（见 _route），
# 避免"订单多少钱""商品什么时候发货"这类混合问句被误分给导购
_PRE_SALES_PATTERN = re.compile(
    r"推荐|想买|哪款|什么好|好物|比价|耳机|键盘|保温杯|充电宝"
    r"|おすすめ|推薦|薦め|どれ|いくら|価格|値段|商品案内|イヤホン|ヘッドホン|キーボード|マグボトル|水筒|バッテリー"
)
# 客服关键词优先级更高（中日双语）：含订单 / 物流 / 售后语义时一律先走客服
_CS_PATTERN = re.compile(
    r"物流|快递|到哪|发货|订单|单号|签收|退|换|退款|售后|质量|坏了"
    r"|配送|荷物|注文|追跡|届く|返品|交換|返金|キャンセル|不良"
)


class Supervisor:
    """多智能体协作主控。available/reason/model 透传主智能体（客服）状态。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = MODEL_ID,  # 默认值统一来自 config.py（glm-5.3-flash），不在各处硬编码
    ):
        # 专职智能体注册表：新增智能体在此登记
        self.customer_service = CustomerServiceAgent(api_key=api_key, base_url=base_url, model=model)
        self.presales = PreSalesAgent(api_key=api_key, base_url=base_url, model=model)
        self.specialists: dict[str, CustomerServiceAgent | PreSalesAgent] = {
            "customer_service": self.customer_service,
            "presales": self.presales,
        }

    @property
    def available(self) -> bool:
        """任一专职智能体可用（LLM 模式）即视为可用。"""
        return any(agent.available for agent in self.specialists.values())

    @property
    def reason(self) -> str | None:
        return self.customer_service.reason

    @property
    def model(self) -> str:
        return self.customer_service.model

    def answer(self, question: str, session_id: str = "default") -> dict | None:
        """按意图路由到专职智能体作答；多轮记忆由 memory/ 的 checkpointer 托管。

        被选智能体不可用 / 失败时，退而尝试客服智能体；仍失败返回 None，
        由调用方（server）走本地规则兜底。
        """
        name = self._route(question)
        # 会话 ID 按智能体隔离（presales:xxx / customer_service:xxx），
        # 避免两个智能体共享同一 thread_id 导致记忆互相串台
        result = self.specialists[name].answer(question, session_id=f"{name}:{session_id}")
        if result is None and name != "customer_service":
            # 主选智能体不可用（如未配 Key），退回客服智能体再试一次
            result = self.customer_service.answer(question, session_id=f"customer_service:{session_id}")
        return result

    @staticmethod
    def _route(question: str) -> str:
        """规则意图路由：订单/物流/售后 → customer_service（优先）；售前咨询 → presales。

        客服关键词优先判断，防止"订单多少钱"这类混合问句被误分给导购；
        后续可替换为 LLM 路由（Roadmap），对外接口不变。
        """
        s = question.lower()
        if _CS_PATTERN.search(s):
            return "customer_service"
        if _PRE_SALES_PATTERN.search(s):
            return "presales"
        return "customer_service"
