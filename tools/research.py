# -*- coding: utf-8 -*-
"""选品研究工具（tools.research）：需求 / 竞争 / 利润 / 四步合验。

演示数据版本：内置 5 个类目的模拟市场数据（搜索量/BSR/售价/重量），
真实版替换为卖家精灵 / Jungle Scout 等数据源 API 调用（接入点见各函数注释）。
所有工具经 P0 双层注册表登记：模块局部表 tools.research + 全局表同步。
"""
from __future__ import annotations

import json

from core.dispatch.registry import LocalRegistry

# ---- 局部注册表（owner=tools.research；high 频直连 + 全局登记）----------------------
registry = LocalRegistry("tools.research")

# ---- 演示市场库：类目 → 需求与成本参数（真实版换数据源 API）-----------------------
_MARKET = {
    "charger": {"category": "充电宝", "search_volume": 8500, "bsr": 320, "avg_price": 37.5,
                "weight_lb": 0.9, "purchase": 25.0, "compet_rating": 4.2, "compet_reviews": 386},
    "earphone": {"category": "蓝牙耳机", "search_volume": 12000, "bsr": 210, "avg_price": 45.0,
                 "weight_lb": 0.5, "purchase": 30.0, "compet_rating": 4.4, "compet_reviews": 612},
    "tumbler": {"category": "保温杯", "search_volume": 6200, "bsr": 450, "avg_price": 28.0,
                "weight_lb": 1.1, "purchase": 18.0, "compet_rating": 4.1, "compet_reviews": 298},
    "keyboard": {"category": "机械键盘", "search_volume": 4100, "bsr": 780, "avg_price": 89.0,
                 "weight_lb": 2.6, "purchase": 60.0, "compet_rating": 4.3, "compet_reviews": 941},
    "earbuds": {"category": "云感耳机", "search_volume": 3900, "bsr": 260, "avg_price": 52.0,
                "weight_lb": 0.6, "purchase": 33.0, "compet_rating": 4.0, "compet_reviews": 254},
}

# 判定阈值（选品四步标准，可调）
DEMAND_MIN = 3000            # 月搜索量下限
PRICE_RANGE = (20.0, 70.0)   # 售价美元区间
WEIGHT_MAX_LB = 2.0          # 重量上限（控制头程成本）
MARGIN_MIN = 0.30            # 净利率下限

# ---- 成本费率（演示值；真实版接物流/费率 API）----------------------------------
_FREIGHT_PER_LB = 15.0   # 头程
_FBA_FEE_MIN = 2.9       # FBA 配送费下限
_FBA_RATE = 0.08         # FBA 配送费率
_COMMISSION = 0.15       # 平台佣金
_AD_RATE = 0.10          # 广告预算占比
_RETURN_RATE = 0.04      # 退货损耗
_STORAGE_RATE = 0.03     # 仓储占比


def _find(keyword: str) -> dict | None:
    """关键词 → 命中一个演示类目（未命中返回 None）。"""
    for data in _MARKET.values():
        name = data["category"]
        if name in keyword or keyword in name:
            return dict(data)
    return None


@registry.register(
    name="check_demand",
    description=(
        "何时使用：选品第一步——判断某个品类的市场需求是否达标（搜索量、"
        "价格区间、重量）。用户问“这个类目好不好做/需求大不大”时调用。\n"
        '调用格式：{"tool": "check_demand", "parameters": {"keyword": "<品类关键词，字符串类型>"}}\n'
        "参数说明：\n"
        '- keyword：品类/商品关键词，字符串类型（string），如 "充电宝"、"蓝牙耳机"。'
    ),
    schema={"keyword": "string 品类关键词（中文）"},
    level="L0",
    cost="medium",
)
def check_demand(keyword: str) -> str:
    """需求验证：搜索量 / BSR / 售价 / 重量 四指标判定。"""
    hit = _find(str(keyword or "").strip())
    if hit is None:
        return json.dumps({"found": False, "hint": "演示库暂无该类目数据（含：充电宝/蓝牙耳机/保温杯/机械键盘/云感耳机）"},
                          ensure_ascii=False)
    p = hit
    price_ok = PRICE_RANGE[0] <= p["avg_price"] <= PRICE_RANGE[1]
    weight_ok = p["weight_lb"] < WEIGHT_MAX_LB
    demand_ok = p["search_volume"] >= DEMAND_MIN
    return json.dumps({
        "found": True,
        "category": p["category"],
        "search_volume": p["search_volume"],
        "bsr": p["bsr"],
        "avg_price_usd": p["avg_price"],
        "weight_lb": p["weight_lb"],
        "checks": {
            "搜索量≥3000": demand_ok,
            "售价$20~$70": price_ok,
            "重量<2lb": weight_ok,
        },
        "passed": demand_ok and price_ok and weight_ok,
    }, ensure_ascii=False)


@registry.register(
    name="check_competition",
    description=(
        "何时使用：选品第二步——判断该关键词首页前 10 名竞品的竞争强度"
        "（平均评分/评论数）。用户问“竞争激烈吗/好入场吗”时调用。\n"
        '调用格式：{"tool": "check_competition", "parameters": {"keyword": "<品类关键词，字符串类型>"}}\n'
        "参数说明：\n"
        '- keyword：品类/商品关键词，字符串类型（string），如 "充电宝"。'
    ),
    schema={"keyword": "string 品类关键词（中文）"},
    level="L0",
    cost="medium",
)
def check_competition(keyword: str) -> str:
    """竞争验证：首页前 10 平均评分 / 评论数 → 低竞争判定（≤4.3 且 ≤500）。"""
    hit = _find(str(keyword or "").strip())
    if hit is None:
        return json.dumps({"found": False, "hint": "演示库暂无该类目数据"}, ensure_ascii=False)
    rating, reviews = hit["compet_rating"], hit["compet_reviews"]
    low_rating = rating <= 4.3
    low_reviews = reviews <= 500
    return json.dumps({
        "found": True,
        "category": hit["category"],
        "avg_rating_top10": rating,
        "avg_reviews_top10": reviews,
        "checks": {"首页评分≤4.3": low_rating, "平均评论≤500": low_reviews},
        "passed": low_rating and low_reviews,
    }, ensure_ascii=False)


@registry.register(
    name="calc_profit",
    description=(
        "何时使用：选品第三步——按采购/头程/FBA/佣金/广告/退货/仓储全链路"
        "费率测算给定售价的净利率，判断是否≥30%。用户问“卖多少钱有利润/这单赚多少”时调用。\n"
        '调用格式：{"tool": "calc_profit", "parameters": {"category": "<品类名，字符串类型>",'
        ' "sell_price": "<售价美元，浮点数类型>"}}\n'
        "参数说明：\n"
        "- category：品类名，字符串类型（string），如“充电宝”；\n"
        "- sell_price：计划售价（美元），浮点数类型（float），如 37.5。"
    ),
    schema={"category": "string 品类名", "sell_price": "float 售价（美元）"},
    level="L0",
    cost="low",
)
def calc_profit(category: str, sell_price: float) -> str:
    """利润测算：全链路费率逐项扣减 → 净利率。"""
    hit = _find(str(category or "").strip())
    if hit is None:
        return json.dumps({"found": False, "hint": "演示库暂无该类目数据"}, ensure_ascii=False)
    try:
        price = float(sell_price)
    except (TypeError, ValueError):
        price = hit["avg_price"]
    freight = hit["weight_lb"] * _FREIGHT_PER_LB
    fba = max(_FBA_FEE_MIN, price * _FBA_RATE)
    commission = price * _COMMISSION
    ads = price * _AD_RATE
    ret = price * _RETURN_RATE
    storage = price * _STORAGE_RATE
    cost = hit["purchase"] + freight + fba + commission + ads + ret + storage
    profit = price - cost
    margin = round(profit / price, 4) if price else 0.0
    return json.dumps({
        "found": True,
        "category": hit["category"],
        "sell_price": price,
        "cost_breakdown": {
            "采购": round(hit["purchase"], 2),
            "头程": round(freight, 2),
            "FBA配送": round(fba, 2),
            "佣金": round(commission, 2),
            "广告": round(ads, 2),
            "退货损耗": round(ret, 2),
            "仓储": round(storage, 2),
        },
        "total_cost": round(cost, 2),
        "profit_per_unit": round(profit, 2),
        "margin": margin,
        "passed": margin >= MARGIN_MIN,
    }, ensure_ascii=False)


@registry.register(
    name="run_product_research",
    description=(
        "何时使用：选品四步合验——需求 + 竞争 + 利润一步出结论。用户直接问"
        "“帮我选个品/这个产品能不能做/帮我看看XX类目”时优先调用本工具（代替分步调用）。\n"
        '调用格式：{"tool": "run_product_research", "parameters": {"keyword": "<品类关键词，字符串类型>"}}\n'
        "参数说明：\n"
        "- keyword：品类/商品关键词，字符串类型（string），如“充电宝”。"
    ),
    schema={"keyword": "string 品类关键词（中文）"},
    level="L0",
    cost="medium",
)
def run_product_research(keyword: str) -> str:
    """四步选品编排：需求 + 竞争 + 利润 + 总分结论。"""
    hit = _find(str(keyword or "").strip())
    if hit is None:
        return json.dumps({"found": False, "hint": "演示库暂无该类目数据（含：充电宝/蓝牙耳机/保温杯/机械键盘/云感耳机）"},
                          ensure_ascii=False)
    demand = json.loads(check_demand(hit["category"]))
    competition = json.loads(check_competition(hit["category"]))
    profit = json.loads(calc_profit(hit["category"], hit["avg_price"]))
    score = sum([demand["passed"], competition["passed"], profit["passed"]])
    return json.dumps({
        "found": True,
        "category": hit["category"],
        "steps": {
            "需求": {"passed": demand["passed"], **demand["checks"]},
            "竞争": {"passed": competition["passed"], **competition["checks"]},
            "利润": {"passed": profit["passed"], "margin": profit["margin"],
                    "profit_per_unit": profit["profit_per_unit"]},
        },
        "score": f"{score}/3",
        "verdict": (
            "建议推进（需求/竞争/利润全部达标）" if score == 3
            else "谨慎推进（部分指标未达标，见 steps 明细）"
        ),
    }, ensure_ascii=False)


__all__ = ["check_demand", "check_competition", "calc_profit", "run_product_research",
           "registry", "DEMAND_MIN", "PRICE_RANGE", "WEIGHT_MAX_LB", "MARGIN_MIN"]