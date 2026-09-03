# -*- coding: utf-8 -*-
"""ECCS 客服工具集 + 演示数据（订单 / 物流 / 售后 / 推荐）。

这些函数同时承担两种角色：
1. 作为 LangGraph Agent 的"工具"，供 LLM 在对话中调用；
2. 作为"卡片数据源"，供服务端在返回结构化卡片时复用。

真实上线时：仅需把下方演示数据替换为订单 / 物流 / 售后 API 与商品库检索即可，
工具的调用签名保持不变，Agent 无需改动。
"""
from __future__ import annotations

import json
from urllib.parse import quote

# ---- 演示商品库（图片地址与 ui/app.js 保持一致）--------------------------------
_IMG_TEMPLATE = "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt={prompt}&image_size=square"


def _img(raw_prompt: str) -> str:
    return _IMG_TEMPLATE.format(prompt=quote(raw_prompt))


PRODUCTS = {
    "earbuds": {
        "code": "earbuds",
        "name": "云感无线蓝牙耳机 Pro · 半入耳",
        "price": 299,
        "img": _img("studio product photo minimalist white wireless earbuds open charging case soft warm beige background"),
        "feature": "主动降噪、佩戴舒适、续航 36 小时",
    },
    "keyboard": {
        "code": "keyboard",
        "name": "奶糖机械键盘 87 键 · 奶油橙",
        "price": 459,
        "img": _img("studio product photo retro cream mechanical keyboard warm orange keycaps soft beige background"),
        "feature": "奶油轴手感软弹、三模连接、支持 Windows/Mac",
    },
    "tumbler": {
        "code": "tumbler",
        "name": "山雾保温杯 450ml · 燕麦奶",
        "price": 129,
        "img": _img("studio product photo cream matte insulated tumbler with lid warm beige background"),
        "feature": "316 不锈钢、保温 12h / 保冷 24h",
    },
    "power": {
        "code": "power",
        "name": "珊瑚移动电源 10000mAh · 快充",
        "price": 189,
        "img": _img("studio product photo slim coral orange power bank warm neutral background"),
        "feature": "22.5W 快充、双口输出、可上飞机",
    },
}

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

_REFUND_SEQ = [2033]  # 售后单号自增，演示用


# ---- 纯数据查询（服务端组卡片 / 兜底路由用）------------------------------------
def lookup_order(order_no: str) -> dict | None:
    """按订单号查订单，不存在返回 None。"""
    order = ORDERS.get(str(order_no).strip())
    if order is None:
        return None
    return {**order, "product": PRODUCTS[order["product_code"]]}


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


# ---- Agent 工具（返回 JSON 字符串，供 LLM 阅读理解）----------------------------
def query_order_info(order_no: str) -> str:
    """查询订单基本信息：商品、金额、下单时间与当前状态。order_no：订单号字符串。"""
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
    """查询订单物流轨迹与预计送达时间。order_no：订单号字符串。"""
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


def handle_return(order_no: str, reason: str = "") -> str:
    """办理退换货 / 退款：登记售后单并给出可选方案。order_no：订单号；reason：退货原因。"""
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


def recommend_products(keywords: list[str]) -> str:
    """根据用户需求关键词推荐合适商品。keywords：需求关键词列表，例如 [\"耳机\", \"降噪\"]。"""
    items = recommend_for(keywords)
    return json.dumps(
        [{"name": p["name"], "price": p["price"], "feature": p["feature"]} for p in items],
        ensure_ascii=False,
    )
