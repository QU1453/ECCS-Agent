# -*- coding: utf-8 -*-
"""推荐工具：按需求关键词匹配推荐商品（数据源：data/shop.db 实时读取，真实版替换为商品库 RAG）。"""
from __future__ import annotations

import json

from .catalog import get_products


# 品类别名表：用户口语（含日语）→ products.category。
# 先按品类整类命中，未命中再走关键词打分——商品名里没有"书"字也能被「推荐一本书」命中
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "book": ("书", "书籍", "图书", "读物"),
    "audio": ("耳机", "イヤホン", "ヘッドホン"),
    "keyboard": ("键盘", "キーボード"),
    "tumbler": ("保温杯", "杯子", "マグボトル", "水筒"),
    "power": ("充电宝", "移动电源", "バッテリー"),
}


def recommend_for(keywords: list[str]) -> list[dict]:
    """推荐商品：先品类命中（实时查库，录完商品立即可推荐），再关键词打分，最后回落 top3。"""
    text = " ".join(keywords or []).lower()
    catalog = list(get_products().values())
    if not text:
        return catalog[:3]

    # 1) 品类优先：需求词里出现品类别名 → 返回该品类全部商品（最多 3 个）
    for cat, aliases in CATEGORY_ALIASES.items():
        if any(alias in text for alias in aliases):
            hits = [p for p in catalog if p.get("category") == cat]
            if hits:
                return hits[:3]

    # 2) 关键词打分：商品名 + 卖点包含关键词则计分
    scored = []
    for p in catalog:
        hay = (p["name"] + p["feature"]).lower()
        score = sum(1 for kw in text.split() if kw in hay) + (1 if any(c in p["name"] for c in text) else 0)
        if score:
            scored.append((score, p))
    if scored:
        return [p for _, p in sorted(scored, key=lambda x: -x[0])][:3]

    # 3) 兜底：无任何命中时回落前 3 个商品
    return catalog[:3]


def recommend_products(keywords: list[str]) -> str:
    """根据用户需求关键词推荐合适商品。

    何时使用：用户想挑商品、求推荐（如"推荐一款耳机""有没有保温的杯子""哪款充电宝好"）时调用；把用户需求拆成关键词列表传入。

    调用格式（JSON）：
    {"tool": "recommend_products", "parameters": {"keywords": ["<关键词1，字符串类型>", "<关键词2，字符串类型>"]}}

    参数说明：
    - keywords：需求关键词数组，字符串数组类型（array of string），例如 ["耳机", "降噪"] 或 ["保温杯"]；没有明确品类时可传 ["推荐"]。
    """
    items = recommend_for(keywords)
    return json.dumps(
        [{"name": p["name"], "price": p["price"], "feature": p["feature"]} for p in items],
        ensure_ascii=False,
    )
