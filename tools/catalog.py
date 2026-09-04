# -*- coding: utf-8 -*-
"""商品库：SQLite 数据源 + 关键词推荐匹配（真实版替换为商品中心 API）。

- 商品数据存 data/shop.db 的 products 表，admin.py 可现场加商品；
- PRODUCTS_COMPAT 仅为兼容保留（首次播种前的静态引用已移除），
  推荐与订单一律实时查库，录完商品立刻可被 agent 推荐。
"""
from __future__ import annotations

from .db import get_conn


def get_products() -> dict[str, dict]:
    """实时读取全部商品，返回 {code: {code,name,price,img,feature,category}}。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT code, name, price, img, feature, category FROM products"
        ).fetchall()
        return {r["code"]: dict(r) for r in rows}
    finally:
        conn.close()


def get_product(code: str) -> dict | None:
    """按商品编码取单个商品。"""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT code, name, price, img, feature FROM products WHERE code = ?", (code,)
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()
