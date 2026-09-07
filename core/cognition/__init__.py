# -*- coding: utf-8 -*-
"""认知层-思考推理子包：ReAct 引擎（后续多智能体编排算法的落位）。"""
from .react import (
    _HAS_LANGGRAPH,
    _JA_REPLY_HINT,
    JA_REPLY_HINT,
    _build_react_agent,
    create_react_agent,
    is_japanese,
)
from .react import ChatOpenAI

__all__ = [
    "_HAS_LANGGRAPH",
    "_JA_REPLY_HINT",
    "JA_REPLY_HINT",
    "_build_react_agent",
    "create_react_agent",
    "is_japanese",
    "ChatOpenAI",
]