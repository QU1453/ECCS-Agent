# -*- coding: utf-8 -*-
"""短期会话记忆：LangGraph MemorySaver（进程级单例，按 thread_id 隔离会话）。

- 所有智能体共享同一 checkpointer，多轮上下文由 LangGraph 托管；
- 进程内有效：重启即清空。需要重启不丢时替换为 SqliteSaver（落盘 data/chat.db）。
"""
from __future__ import annotations

try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - 未安装 langgraph 时（兜底模式不需要记忆）
    MemorySaver = None

_checkpointer = None


def get_checkpointer():
    """进程级单例 checkpointer；langgraph 不可用时返回 None（智能体将退回兜底模式）。"""
    global _checkpointer
    if _checkpointer is None and MemorySaver is not None:
        _checkpointer = MemorySaver()
    return _checkpointer


def thread_id_for(session_id: str) -> str:
    """会话 ID → checkpointer thread_id（预留命名空间，便于多智能体记忆隔离扩展）。"""
    return f"session:{session_id}"
