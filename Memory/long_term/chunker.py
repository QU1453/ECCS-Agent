# -*- coding: utf-8 -*-
"""RAG 分块（Chunking）：句子/段落优先切分 + 固定窗口重叠，参数可配。

策略：
1. 先按段落（换行）与句子边界（。！？!?；; 等）切，保持语义单元完整；
2. 连续句子贪心打包到 max_tokens；块间携带 overlap 的尾部句子，边界语义不断裂；
3. 单句超限时按字符窗口硬切（CJK 1 字≈1 token 的保守窗口）。

token 估算：CJK 字符（含假名）按 1、拉丁字符按 0.25 计，够分块用；接入真 tokenizer 只需改 estimate_tokens。
"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def estimate_tokens(text: str) -> int:
    cjk = sum(
        1 for c in text
        if "\u2e80" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff" or "\uff00" <= c <= "\uffef"
    )
    return cjk + (len(text) - cjk) // 4


def _sentences(text: str) -> list[str]:
    text = text.replace("\r", "")
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    return parts if parts else ([text.strip()] if text.strip() else [])


def _hard_split(s: str, max_tokens: int, overlap: int, min_tokens: int) -> list[str]:
    win, step = max_tokens, max(1, max_tokens - overlap)
    out = [s[i:i + win] for i in range(0, len(s), step)]
    if len(out) > 1 and estimate_tokens(out[-1]) < min_tokens:  # 尾部过短并入前块
        out[-2] += out[-1]
        out.pop()
    return out


def chunk_text(text: str, max_tokens: int = 300, overlap: int = 50, min_tokens: int = 10) -> list[str]:
    """把长文本切成带重叠的块；空文本返回 []。"""
    if not text or not text.strip():
        return []
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for sent in _sentences(text):
        slen = estimate_tokens(sent)
        if slen > max_tokens:  # 超长单句：先落袋已打包内容，再硬切
            if cur:
                chunks.append("".join(cur))
                cur, cur_len = [], 0
            chunks.extend(_hard_split(sent, max_tokens, overlap, min_tokens))
            continue
        if cur and cur_len + slen > max_tokens:
            chunks.append("".join(cur))
            tail: list[str] = []  # overlap：取上一块尾部若干句
            tail_len = 0
            for prev in reversed(cur):
                plen = estimate_tokens(prev)
                if tail_len + plen > overlap:
                    break
                tail.insert(0, prev)
                tail_len += plen
            cur, cur_len = list(tail), tail_len
        cur.append(sent)
        cur_len += slen
    if cur:
        chunks.append("".join(cur))
    merged: list[str] = []  # 过短块并入前块，避免碎片
    for c in chunks:
        if merged and estimate_tokens(c) < min_tokens:
            merged[-1] += c
        else:
            merged.append(c)
    return merged
