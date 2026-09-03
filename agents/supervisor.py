# -*- coding: utf-8 -*-
"""主控智能体（Supervisor）：对外统一入口，对内调度专职智能体。

当前注册：客服智能体。多智能体扩展方法：
1. 在 agents/ 下新增专职智能体文件（参考 customer_service.py）；
2. 在下方 specialists 注册表加一行；
3. 需要分流时，在 answer() 里接入意图路由（LLM 路由或规则路由）。
"""
from __future__ import annotations

from .customer_service import CustomerServiceAgent


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
        self.specialists: dict[str, CustomerServiceAgent] = {
            "customer_service": self.customer_service,
        }

    @property
    def available(self) -> bool:
        """主智能体是否可用（LLM 模式）。"""
        return self.customer_service.available

    @property
    def reason(self) -> str | None:
        return self.customer_service.reason

    @property
    def model(self) -> str:
        return self.customer_service.model

    def answer(self, question: str, session_id: str = "default") -> dict | None:
        """调度专职智能体作答；多轮记忆由 memory/ 的 checkpointer 按 session_id 托管。

        不可用/失败返回 None，由调用方走本地兜底。
        """
        return self.customer_service.answer(question, session_id)
