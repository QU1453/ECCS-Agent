# -*- coding: utf-8 -*-
"""ECCS 工具包：客服（商品库/订单物流/售后/推荐）+ 卖家工作台（选品/供应商/Listing）。

新增工具：在包内加一个模块文件（可用 P0 双层注册表 register），并在下方 re-export。
"""
from .after_sales import handle_return, register_return
from .catalog import PRODUCTS
from .order import ORDERS, lookup_order, query_order_info, track_logistics
from .recommend import recommend_for, recommend_products
from .research import calc_profit, check_competition, check_demand, run_product_research
from .supplier import compare_supplier, search_supplier
from .listing import check_images, draft_listing, price_strategy, recommend_fulfillment

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
    "check_demand",
    "check_competition",
    "calc_profit",
    "run_product_research",
    "search_supplier",
    "compare_supplier",
    "draft_listing",
    "check_images",
    "price_strategy",
    "recommend_fulfillment",
]
