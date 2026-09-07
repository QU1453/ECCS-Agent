# -*- coding: utf-8 -*-
"""Listing 创建与上架工具（tools.listing）：文案起草 / 图片合规 / 定价 / 履约建议。

演示数据版本：内置 Listing 规则（标题 75 字符新规 / 五点 / Search Terms / 图片白底规则），
真实版替换为 Amazon SP-API 等上架接口（接入槽位见函数注释）。
所有工具经 P0 双层注册表登记：模块局部表 tools.listing + 全局表同步。
"""
from __future__ import annotations

import json

from core.dispatch.registry import LocalRegistry

# ---- 局部注册表（owner=tools.listing）---------------------------------------------
registry = LocalRegistry("tools.listing")

# 标题 / 关键词 / 五点 演示模板（真实版接 Listing 优化 AI 服务）
_LISTING_DRAFT = {
    "云感耳机": {
        "brand": "ECCS",
        "core": "Wireless Earbuds with ANC",
        "attrs": "HiFi Stereo / 36H Playtime / IPX5",
        "scene": "for Sports & Commuting",
        "bullets": [
            "主动降噪，通勤地铁一戴安静：双馈 ANC 降噪深度 -35dB，专注不被打扰。",
            "36 小时长续航：单次 8h + 充电盒再续 28h，出差一周不用带线。",
            "云感半入耳，久戴不痛：单耳仅 3.8g，人体工学贴合，跑步也不掉。",
            "HiFi 双单元：10mm 动圈 + 高解析解码，低音有量、人声清晰。",
            "IPX5 防水：运动流汗、小雨天都可以放心用。",
        ],
        "search_terms": "bluetooth earphones anc wireless earbuds sport headset true wireless ipx5",
    },
}


def _draft_for(product_name: str) -> dict:
    for key, draft in _LISTING_DRAFT.items():
        if key in product_name or product_name in key:
            return draft
    # 未命中模板：用通用构件兜底（结果可继续人工修改）
    return {
        "brand": "ECCS",
        "core": (product_name or "Product").strip(),
        "attrs": "High Quality / Durable / Easy to Use",
        "scene": "for Daily Use",
        "bullets": [
            "高品质选材，做工扎实，细节到位。",
            "设计简洁易用，开箱即用，无需学习成本。",
            "多场景适用：家里、办公室、出行都合适。",
            "轻巧便携，收纳方便，不占空间。",
            "品质保障：支持 7 天无理由退换，售后无忧。",
        ],
        "search_terms": "best seller gift high quality durable portable multifunctional",
    }


@registry.register(
    name="draft_listing",
    description=(
        "何时使用：用户要写 Listing（标题/五点描述/Search Terms）时调用。"
        "卖点标题文案、五点怎么写、搜索关键词怎么埋，都走本工具。\n"
        '调用格式：{"tool": "draft_listing", "parameters": {"product_name": "<商品名，字符串类型>",'
        ' "keywords": "<核心关键词列表，字符串数组类型>"}}\n'
        "参数说明：\n"
        "- product_name：商品名，字符串类型（string），如“云感耳机”；\n"
        "- keywords：核心关键词列表，字符串数组类型（list[string]），如 [\"无线耳机\", \"降噪耳机\"]。"
    ),
    schema={"product_name": "string 商品名", "keywords": "list[string] 核心关键词"},
    level="L0",
    cost="medium",
)
def draft_listing(product_name: str, keywords: list | None = None) -> str:
    """起草 Listing：标题（≤75 字符新规）+ 五点（问答式卖点）+ Search Terms。"""
    d = _draft_for(str(product_name or "").strip())
    kws = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    title = " ".join(x for x in [d["brand"], d["core"], d["attrs"], d["scene"]] if x)
    title = title[:75].strip()  # 75 字符新规：品牌+核心词+属性+场景，超长截断
    search_terms = d["search_terms"]
    if kws:
        search_terms = search_terms + " " + " ".join(kws[:5])
    return json.dumps({
        "found": True,
        "title": title,
        "title_len": len(title),
        "bullets": d["bullets"],
        "search_terms": search_terms,
        "tips": ["标题 ≤75 字符（亚马逊 2025 新规）", "五点每点首词大写、先答核心问题",
                "Search Terms 不要重复标题词、不要竞品品牌词"],
    }, ensure_ascii=False)


@registry.register(
    name="check_images",
    description=(
        "何时使用：上架前检查主图/附图是否合规（白底、占比、文字水印）时调用，"
        "用户问“图片合不合规/主图能不能过审”时调用本工具。\n"
        '调用格式：{"tool": "check_images", "parameters": {"image_urls": "<图片地址列表，字符串数组类型>"}}\n'
        "参数说明：\n"
        "- image_urls：要检查的图片 URL 列表，字符串数组类型（list[string]），每项是 http(s) 图片地址。"
    ),
    schema={"image_urls": "list[string] 图片地址"},
    level="L0",
    cost="low",
)
def check_images(image_urls: list | None = None) -> str:
    """图片合规自检：白底 RGB255 / 主体占比 ≥85% / 无文字水印（演示规则）。"""
    urls = [str(u).strip() for u in (image_urls or []) if str(u).strip()]
    if not urls:
        return json.dumps({"found": False, "hint": "请提供至少一个图片 URL"}, ensure_ascii=False)
    checks = []
    for i, url in enumerate(urls, start=1):
        # 演示规则：以 URL 特征模拟检测结果（真实版接机器视觉检测服务）
        clean = "text" not in url.lower() and "watermark" not in url.lower()
        checks.append({
            "image_no": i,
            "url": url[:80],
            "white_bg": "rgb255" in url.lower() or "white" in url.lower(),
            "ratio_ok": True,
            "no_text_watermark": clean,
            "passed": clean,
        })
    passed = sum(1 for c in checks if c["passed"])
    return json.dumps({
        "found": True,
        "total": len(urls),
        "passed_count": passed,
        "detail": checks,
        "hint": "主图必须纯白底(255,255,255)、商品占比≥85%、无文字/水印/Logo；未通过项请修图后重检。",
    }, ensure_ascii=False)


@registry.register(
    name="price_strategy",
    description=(
        "何时使用：给 Listing 做定价决策时调用——按竞品价与 ≥30% 净利率反推"
        "最低可售价格。用户问“定多少价合适/最低卖多少不亏”时调用。\n"
        '调用格式：{"tool": "price_strategy", "parameters": {"product_code": "<商品编码，字符串类型>"}}\n'
        "参数说明：\n"
        "- product_code：商品库编码，字符串类型（string），如 \"earbuds\"、\"keyboard\"、\"tumbler\"、\"power\"。"
    ),
    schema={"product_code": "string 商品库编码"},
    level="L0",
    cost="low",
)
def price_strategy(product_code: str) -> str:
    """定价建议：竞品参考价 + 保底 30% 毛利最低售价。"""
    from tools import PRODUCTS

    code = str(product_code or "").strip()
    product = PRODUCTS.get(code)
    if product is None:
        return json.dumps({"found": False, "hint": "商品库无此编码（可用：earbuds/keyboard/tumbler/power）"},
                          ensure_ascii=False)
    ref = product["price"]
    min_price = round(ref * 0.78, 2)   # 演示口径：成本约价盘 78%，保 30% 净利
    suggested = round(ref * 0.95, 2)
    return json.dumps({
        "found": True,
        "product": product["name"],
        "competitor_ref": ref,
        "suggested": suggested,
        "min_break_even": min_price,
        "hint": f"建议售价 {suggested} 元（略低于竞品做首发优势）；"
                f"低于 {min_price} 元将跌破 30% 净利率红线。",
    }, ensure_ascii=False)


@registry.register(
    name="recommend_fulfillment",
    description=(
        "何时使用：上架前决定 FBA / FBM 履约方式时调用，"
        "用户问“走FBA还是自发货/首批发多少合适”时调用本工具。\n"
        '调用格式：{"tool": "recommend_fulfillment", "parameters": {"product_code": "<商品编码，字符串类型>",'
        ' "stock": "<首批备货数量，整数类型>"}}\n'
        "参数说明：\n"
        "- product_code：商品库编码，字符串类型（string），如 \"earbuds\"；\n"
        "- stock：首批备货数量，整数类型（int），如 80。"
    ),
    schema={"product_code": "string 商品库编码", "stock": "int 首批备货数量"},
    level="L0",
    cost="low",
)
def recommend_fulfillment(product_code: str, stock: int) -> str:
    """履约建议：首批 ≤100 件试水口径，轻小件 FBA、重/低价件 FBM。"""
    from tools import PRODUCTS

    code = str(product_code or "").strip()
    product = PRODUCTS.get(code)
    if product is None:
        return json.dumps({"found": False, "hint": "商品库无此编码（可用：earbuds/keyboard/tumbler/power）"},
                          ensure_ascii=False)
    try:
        n = int(stock)
    except (TypeError, ValueError):
        n = 80
    lightweight = code in ("earbuds", "tumbler")
    mode = "FBA" if lightweight else "FBM"
    return json.dumps({
        "found": True,
        "product": product["name"],
        "suggested_mode": mode,
        "first_batch": n,
        "hint": (
            f"首批 {n} 件建议 {mode}（轻小件走 FBA 提升转化；重/低价件先 FBM 控仓储成本）。"
            "试水期控制在 100 件以内，动销稳定后再补货。"
        ),
    }, ensure_ascii=False)


__all__ = ["draft_listing", "check_images", "price_strategy", "recommend_fulfillment",
           "registry"]