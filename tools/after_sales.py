# -*- coding: utf-8 -*-
"""售后工具：退换货 / 退款受理登记（数据源：data/shop.db，真实版对接售后工单系统）。"""
from __future__ import annotations

import json

from .db import get_conn
from .order import lookup_order

# 售后单号口径：#SA-{id + 2032}，与原演示序列（首单 #SA-2034）衔接
_SEQ_OFFSET = 2032


def register_return(order_no: str, reason: str) -> dict:
    """登记售后单：落库持久化（重启不丢），返回受理信息。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO after_sales(order_no, reason) VALUES(?,?)",
            (str(order_no).strip(), reason or "未填写"),
        )
        conn.commit()
        receipt_id = cur.lastrowid
    finally:
        conn.close()
    order = lookup_order(order_no)
    return {
        "receipt": f"#SA-{receipt_id + _SEQ_OFFSET}",
        "order_no": str(order_no).strip(),
        "product_name": order["product"]["name"] if order else None,
        "refund_amount": order["total"] if order else None,
        "reason": reason or "未填写",
        "options": ["仅退款（原路退回）", "换新（免运费优先发）", "退货退款"],
    }


def handle_return(order_no: str, reason: str = "") -> str:
    """办理退换货 / 退款：登记售后单并给出可选方案。

    何时使用：用户想退货、换货、退款、报质量问题、商品坏了需要售后时调用；仅做意向咨询而未确认办理时，可先说明政策再调用本工具登记。

    调用格式（JSON）：
    {"tool": "handle_return", "parameters": {"order_no": "<订单号，字符串类型>", "reason": "<退货原因，字符串类型，可省略，默认空字符串>"}}

    参数说明：
    - order_no：订单号，字符串类型（string），例如 "2026081200012"，用户消息中形如 2026xxxxxxxx 的连续数字。
    - reason：退货原因，字符串类型（string），可省略；用户未说明时传空字符串 ""。
    """
    r = register_return(order_no, reason)
    return json.dumps(
        {
            "ok": True,
            "receipt": r["receipt"],
            "order_no": r["order_no"],
            "refund_amount": r["refund_amount"],
            "message": f"售后单 {r['receipt']} 已登记",
            "options": r["options"],
        },
        ensure_ascii=False,
    )
