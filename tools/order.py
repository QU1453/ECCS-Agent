# -*- coding: utf-8 -*-
"""订单 / 物流工具：查询订单信息与物流轨迹（演示数据，真实版对接订单与物流 API）。"""
from __future__ import annotations

import json

from .catalog import PRODUCTS

# ---- 演示订单（步骤 state：done=已完成 / cur=进行中 / ""=未到）------------------
ORDERS = {
    "2026081200012": {
        "order_no": "2026081200012",
        "product_code": "earbuds",
        "qty": 1,
        "total": 299,
        "paid_at": "昨天 15:02 付款",
        "carrier": "顺丰速运",
        "status": "transporting",  # paid / transporting / delivering / done
        "location": "广州转运中心",
        "eta": "明天 18:00 前送达",
        "steps": [
            {"label": "已付款", "state": "done"},
            {"label": "运输中", "state": "cur"},
            {"label": "派送中", "state": ""},
            {"label": "已签收", "state": ""},
        ],
    }
}


def lookup_order(order_no: str) -> dict | None:
    """按订单号查订单，不存在返回 None。"""
    order = ORDERS.get(str(order_no).strip())
    if order is None:
        return None
    return {**order, "product": PRODUCTS[order["product_code"]]}


def query_order_info(order_no: str) -> str:
    """查询订单基本信息：商品、金额、下单时间与当前状态。调用格式 [query_order_info:order_no]，order_no：订单号字符串。"""
    order = lookup_order(order_no)
    if order is None:
        return json.dumps({"found": False, "hint": "未查到该订单，请先核对订单号"}, ensure_ascii=False)
    p = order["product"]
    return json.dumps(
        {
            "found": True,
            "order_no": order["order_no"],
            "product_name": p["name"],
            "qty": order["qty"],
            "total": order["total"],
            "paid_at": order["paid_at"],
            "status": {"paid": "已付款", "transporting": "运输中", "delivering": "派送中", "done": "已签收"}.get(order["status"], order["status"]),
        },
        ensure_ascii=False,
    )


def track_logistics(order_no: str) -> str:
    """查询订单物流轨迹与预计送达时间。调用格式 [track_logistics:order_no]，order_no：订单号字符串。"""
    order = lookup_order(order_no)
    if order is None:
        return json.dumps({"found": False, "hint": "未查到该订单的物流信息，请先核对订单号"}, ensure_ascii=False)
    return json.dumps(
        {
            "found": True,
            "order_no": order["order_no"],
            "carrier": order["carrier"],
            "current_location": order["location"],
            "eta": order["eta"],
            "progress": [s["label"] for s in order["steps"]],
        },
        ensure_ascii=False,
    )
