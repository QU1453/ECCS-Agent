# -*- coding: utf-8 -*-
"""知识库内部分块：优先复用 long_term.chunker（语义分块），缺依赖时内置简单分段兜底。"""
from __future__ import annotations

import re

try:  # pragma: no cover - 依赖分支
    from ..long_term.chunker import chunk_text as _semantic_chunks

    def default_chunker(text: str, size: int = 300, overlap: int = 50) -> list[str]:
        """语义分块（句子/段落优先 + 重叠；hnswlib 可用时走此路径）。"""
        return _semantic_chunks(text, max_tokens=size, overlap=overlap)
except Exception:  # noqa: BLE001 - Windows 无 hnswlib 时
    def default_chunker(text: str, size: int = 300, overlap: int = 50) -> list[str]:
        """简单兜底分块：按字符窗口切、带步进重叠，保证知识库在无重型依赖时可用。"""
        return _simple_chunks(text, size, overlap)


def _simple_chunks(text: str, size: int = 300, overlap: int = 50) -> list[str]:
    """兜底分块：优先按段落聚合，超限按字符窗口硬切（步进 = size - overlap）。"""
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) + 1 > size:
            chunks.append(cur)
            cur = ""
        while len(p) > size:  # 单段超限：字符窗口硬切
            chunks.append(p[:size])
            p = p[size - overlap:]
        cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks