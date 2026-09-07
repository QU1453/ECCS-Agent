# -*- coding: utf-8 -*-
"""智能体包：supervisor 主控 + 专职智能体（多智能体协作）。

新增智能体：在本目录加一个文件（继承 base.py 的 ReActAgentBase），
并在 supervisor.py 的 specialists 注册。
"""
from .base import ReActAgentBase, is_japanese
from .customer_service import CustomerServiceAgent, classic_reply
from .listing_agent import ListingAgent, classic_listing_reply
from .presales import PreSalesAgent, classic_presales_reply
from .research_agent import ResearchAgent, classic_research_reply
from .supervisor import Supervisor

__all__ = [
    "ReActAgentBase",
    "is_japanese",
    "CustomerServiceAgent",
    "PreSalesAgent",
    "ResearchAgent",
    "ListingAgent",
    "Supervisor",
    "classic_reply",
    "classic_presales_reply",
    "classic_research_reply",
    "classic_listing_reply",
]
