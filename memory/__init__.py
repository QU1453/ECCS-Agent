# -*- coding: utf-8 -*-
"""记忆包：短期会话记忆（LangGraph checkpointer）。

职责边界：
- short_term：多轮会话记忆，MemorySaver 按 thread_id（= session_id）隔离，进程内有效；
- 长期记忆（用户画像 / 跨会话偏好 / RAG 知识）规划中，届时新增 long_term.py。
"""
from .short_term import get_checkpointer, thread_id_for

__all__ = ["get_checkpointer", "thread_id_for"]
