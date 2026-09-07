# -*- coding: utf-8 -*-
"""知识库子包：索引先行、两阶段检索（docs/chunks/index 三表）。"""
from .indexer import KnowledgeBase
from .retriever import fetch_knowledge, get_index

__all__ = ["KnowledgeBase", "get_index", "fetch_knowledge"]