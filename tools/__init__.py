# -*- coding: utf-8 -*-
"""客服工具包：商品库 / 订单物流 / 售后 / 推荐，供各智能体共享调用。

新增工具：在包内加一个模块文件，并在下方 re-export，即可被所有智能体使用。
"""
from .after_sales import handle_return, register_return
from .catalog import PRODUCTS
from .order import ORDERS, lookup_order, query_order_info, track_logistics
from .recommend import recommend_for, recommend_products

__all__ = [
    "PRODUCTS",
    "ORDERS",
    "lookup_order",
    "query_order_info",
    "track_logistics",
    "register_return",
    "handle_return",
    "recommend_for",
    "recommend_products",
]
