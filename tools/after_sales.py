# -*- coding: utf-8 -*-
"""售后工具：退换货 / 退款受理登记（演示数据，真实版对接售后工单系统）。"""
from __future__ import annotations

import json

from .order import lookup_order

_REFUND_SEQ = [2033]  # 售后单号自增，演示用


def register_return(order_no: str, reason: str) -> dict:
    """登记售后单，返回受理信息（演示）。"""
    n = _REFUND_SEQ[-1] + 1
    _REFUND_SEQ.append(n)
    order = lookup_order(order_no)
    return {
        "receipt": f"#SA-{n}",
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
