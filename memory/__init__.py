# -*- coding: utf-8 -*-
"""记忆包（memory）：短期 + 长期记忆，LangGraph checkpointer + ANN-RAG + 记忆压缩。

职责边界：
- short_term/：多轮会话记忆，SqliteSaver 按 thread_id（= "session:{session_id}"）隔离，
  SQLite 落盘持久化（重启不丢），超阈值自动压缩（LLM 滚动摘要，无 Key 降级纯裁剪）；
- long_term/：长期记忆，facts 精确 KV + documents/chunks 分块 + hnswlib ANN 语义召回；
- manager.py：MemoryManager 统一入口（LLM 输入接口 / 后端数据输入接口 / build_context）。

兼容层（保持 agents/ 原有用法不变）：
- get_checkpointer()：进程级单例 checkpointer（由 MemorySaver 升级为 SQLite 持久化 SqliteSaver）；
- thread_id_for(session_id)：会话 ID → 线程命名空间（"session:{id}"）。

快速上手：

    from memory import MemoryManager
    mm = MemoryManager()                                  # 数据落 ./short_term/data 与 ./long_term/data
    mm.add_message("s1", "user", "你好")                   # LLM 输入接口（对话消息）
    mm.save_fact("u1", "last_order_no", "2026081200012")   # 后端数据输入接口（结构化事实）
    mm.add_document("u1", "退货政策：……")                   # 后端数据输入接口（长文本→分块→ANN）
    hits = mm.recall("u1", "退货流程")                      # ANN 速度优先 + 精确重排
    ctx = mm.build_context("s1", "u1", query="退货流程")     # summary/history/facts/recalled 四段组装

一键演示：python -m memory.demo
"""
from pathlib import Path

from .long_term.ann import AnnIndex
from .long_term.chunker import chunk_text
from .long_term.rag import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from .manager import MemoryManager
from .short_term import thread_id_for
from .short_term.compress import Compressor

__all__ = [
    "MemoryManager",
    "Compressor",
    "AnnIndex",
    "chunk_text",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_checkpointer",
    "thread_id_for",
]

_compat_stm = None  # 兼容层懒加载单例（只建短期记忆，长期记忆按需另建 MemoryManager）


def get_checkpointer():
    """兼容旧 API：进程级单例 checkpointer（现升级为 SQLite 持久化的 SqliteSaver）。"""
    global _compat_stm
    if _compat_stm is None:
        from .short_term.memory import ShortTermMemory

        _compat_stm = ShortTermMemory(
            Path(__file__).resolve().parent / "short_term" / "data" / "short_term.sqlite"
        )
    return _compat_stm.saver
