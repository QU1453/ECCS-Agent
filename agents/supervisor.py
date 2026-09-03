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

from .customer_service import CustomerServiceAgent, classic_reply
from .presales import PreSalesAgent

# 售前导购的路由关键词：命中即分流给 presales，其余默认给客服
_PRE_SALES_PATTERN = re.compile(r"推荐|想买|哪款|什么好|好物|比价|多少钱|价格|耳机|键盘|保温杯|充电宝|商品")


class Supervisor:
    """多智能体协作主控。available/reason/model 透传主智能体（客服）状态。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
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
        result = self.specialists[name].answer(question, session_id)
        if result is None and name != "customer_service":
            # 主选智能体不可用（如未配 Key），退回客服智能体再试一次
            result = self.customer_service.answer(question, session_id)
        return result

    @staticmethod
    def _route(question: str) -> str:
        """规则意图路由：售前咨询 → presales；其余（订单/物流/售后/闲聊）→ customer_service。

        后续可替换为 LLM 路由（Roadmap），对外接口不变。
        """
        if _PRE_SALES_PATTERN.search(question.lower()):
            return "presales"
        return "customer_service"
