# -*- coding: utf-8 -*-
"""智能体包：supervisor 主控 + 专职智能体（多智能体协作）。

新增智能体：在本目录加一个文件，并在 supervisor.py 的 specialists 注册。
"""
from .customer_service import CustomerServiceAgent, classic_reply
from .supervisor import Supervisor

__all__ = ["CustomerServiceAgent", "Supervisor", "classic_reply"]
