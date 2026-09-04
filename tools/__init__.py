# -*- coding: utf-8 -*-
"""客服工具包：商品库 / 订单物流 / 售后 / 推荐（数据源 data/shop.db），供各智能体共享调用。

- 数据统一存 SQLite（data/shop.db），admin.py 可现场录单 / 推进物流 / 加商品；
- 新增工具：在包内加一个模块文件，并在下方 re-export，即可被所有智能体使用。
"""
from .after_sales import handle_return, register_return
from .catalog import get_product, get_products
from .order import (
    advance_order,
    create_order,
    list_orders,
    lookup_order,
    query_order_info,
    track_logistics,
)
from .recommend import recommend_for, recommend_products

__all__ = [
    "get_product",
    "get_products",
    "lookup_order",
    "create_order",
    "advance_order",
    "list_orders",
    "query_order_info",
    "track_logistics",
    "register_return",
    "handle_return",
    "recommend_for",
    "recommend_products",
]
