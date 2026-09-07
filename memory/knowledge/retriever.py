# -*- coding: utf-8 -*-
"""知识库检索（两阶段）：get_index 先看索引简述 → fetch_knowledge 只取选中的块正文。

对 KnowledgeBase 的便捷封装：让调用方（感知层 / 编排器）拿到熟悉的函数形态。
"""
from __future__ import annotations

from .indexer import KnowledgeBase


def get_index(kb: KnowledgeBase, user_id: str | None = None,
              filter_keywords: list[str] | None = None, limit: int = 50) -> list[dict]:
    """第一步：只返回索引（brief/keywords/title/chunk_id），供 Agent 判断哪些块相关。"""
    return kb.get_index(user_id=user_id, filter_keywords=filter_keywords, limit=limit)


def fetch_knowledge(kb: KnowledgeBase, chunk_ids: list[int]) -> list[dict]:
    """第二步：只取被选中块的全文（[{chunk_id, text, title, seq}]）。"""
    return kb.fetch_knowledge(chunk_ids)