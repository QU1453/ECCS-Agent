# -*- coding: utf-8 -*-
"""推荐工具：按需求关键词匹配推荐商品（演示数据，真实版替换为商品库 RAG）。"""
from __future__ import annotations

import json

from .catalog import PRODUCTS


def recommend_for(keywords: list[str]) -> list[dict]:
    """按关键词粗匹配推荐商品（真实版替换为商品库 RAG）。"""
    text = " ".join(keywords or []).lower()
    catalog = list(PRODUCTS.values())
    if not text:
        return catalog[:3]
    scored = []
    for p in catalog:
        hay = (p["name"] + p["feature"]).lower()
        score = sum(1 for kw in text.split() if kw in hay) + (1 if any(c in p["name"] for c in text) else 0)
        if score:
            scored.append((score, p))
    if not scored:
        return catalog[:3]
    return [p for _, p in sorted(scored, key=lambda x: -x[0])][:3]


def recommend_products(keywords: list[str]) -> str:
    """根据用户需求关键词推荐合适商品。keywords：需求关键词列表，例如 ["耳机", "降噪"]。"""
    items = recommend_for(keywords)
    return json.dumps(
        [{"name": p["name"], "price": p["price"], "feature": p["feature"]} for p in items],
        ensure_ascii=False,
    )
