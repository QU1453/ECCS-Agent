# -*- coding: utf-8 -*-
"""订单 / 物流工具：查询订单信息与物流轨迹（数据源：data/shop.db，真实版对接订单与物流 API）。"""
from __future__ import annotations

import json

from .catalog import get_product
from .db import STATUS_SCENE, STATUS_TEXT, get_conn, order_steps


def _gen_order_no() -> str:
    """生成新订单号：YYYYMMDD + 5 位当日序号（如 2026090400001）。"""
    from datetime import datetime

    conn = get_conn()
    try:
        date_prefix = datetime.now().strftime("%Y%m%d")
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE order_no LIKE ?", (f"{date_prefix}%",)
        ).fetchone()
        return f"{date_prefix}{row['n'] + 1:05d}"
    finally:
        conn.close()


def lookup_order(order_no: str) -> dict | None:
    """按订单号查订单（实时查库），不存在返回 None。返回结构与原演示版一致。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_no = ?", (str(order_no).strip(),)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    order = dict(row)
    product = get_product(order["product_code"])
    if product is None:
        return None
    order["product"] = product
    order["location"], order["eta"] = STATUS_SCENE.get(order["status"], ("", ""))
    order["steps"] = order_steps(order["status"])
    return order


def create_order(product_code: str, qty: int = 1, carrier: str = "顺丰速运") -> dict:
    """新建订单（admin.py 录单用）：状态 paid，自动算总价与订单号。供录单工具调用。"""
    product = get_product(product_code)
    if product is None:
        raise ValueError(f"商品编码不存在：{product_code}")
    order_no = _gen_order_no()
    from datetime import datetime

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO orders(order_no, product_code, qty, total, paid_at, status, carrier)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                order_no,
                product_code,
                qty,
                round(product["price"] * qty, 2),
                f"今天 {datetime.now().strftime('%H:%M')} 付款",
                "paid",
                carrier,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return lookup_order(order_no)


def advance_order(order_no: str) -> dict | None:
    """推进订单到下一状态（paid→transporting→delivering→done，admin.py 用）。"""
    from .db import STATUS_FLOW

    order = lookup_order(order_no)
    if order is None:
        return None
    idx = STATUS_FLOW.index(order["status"])
    if idx >= len(STATUS_FLOW) - 1:
        return order  # 已签收，不能再推进
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE orders SET status = ? WHERE order_no = ?",
            (STATUS_FLOW[idx + 1], str(order_no).strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return lookup_order(order_no)


def list_orders() -> list[dict]:
    """全部订单（admin.py 列表用，按下单时间倒序）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT order_no, product_code, qty, total, paid_at, status, carrier"
            " FROM orders ORDER BY created_at DESC, order_no DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_order_info(order_no: str) -> str:
    """查询订单基本信息：商品、金额、下单时间与当前状态。

    何时使用：用户询问订单详情（买了什么、多少钱、什么时候下的单、订单状态如何）时调用；仅凭订单号查状态，不包含物流轨迹（轨迹请用 track_logistics）。

    调用格式（JSON）：
    {"tool": "query_order_info", "parameters": {"order_no": "<订单号，字符串类型>"}}

    参数说明：
    - order_no：订单号，字符串类型（string），例如 "2026081200012"，用户消息中形如 2026xxxxxxxx 的连续数字。
    """
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
            "status": STATUS_TEXT.get(order["status"], order["status"]),
        },
        ensure_ascii=False,
    )


def track_logistics(order_no: str) -> str:
    """查询订单物流轨迹与预计送达时间。

    何时使用：用户询问包裹/订单到哪了、物流进度、快递状态、什么时候送到时调用；需要物流轨迹（承运商、当前位置、预计送达）时用本工具，而不是 query_order_info。

    调用格式（JSON）：
    {"tool": "track_logistics", "parameters": {"order_no": "<订单号，字符串类型>"}}

    参数说明：
    - order_no：订单号，字符串类型（string），例如 "2026081200012"，用户消息中形如 2026xxxxxxxx 的连续数字。
    """
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
