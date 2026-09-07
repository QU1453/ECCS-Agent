# -*- coding: utf-8 -*-
"""感知-输入管理：清洗 / 语言检测 / 意图初判（规则词表打分）。

意图打分是 supervisor 规则路由的"前置粗判"：给出各候选智能体的命中评分，
供编排层（orchestrator）在 LLM 路由不可用时兜底决策，或做路由合理性校验。
词表与 agents/supervisor.py 的路由正则保持一致口径（supervisor 为准，
本模块只做打分初判，二者可独立演进）。
"""
from __future__ import annotations

import re

from core.cognition.react import is_japanese

__all__ = ["clean_input", "detect_lang", "intent_score"]

# ---- 意图词表（每命中一处 +1，分数高者优先；与 supervisor 路由正则同口径）----------
_LISTING_WORDS = [
    "listing", "上架", "标题", "五点", "描述", "图片", "主图", "定价", "售价",
    "fba", "fbm", "关键词布局", "search terms", "五点描述",
]
_RESEARCH_WORDS = [
    "选品", "热销", "爆款", "搜索量", "利润", "竞争", "供应商", "1688", "阿里",
    "采购", "起订量", "moq", "货源", "进货", "比价", "需求",
]
_CS_WORDS = [
    "物流", "快递", "到哪", "发货", "订单", "单号", "签收", "退", "换", "退款",
    "售后", "质量", "坏了", "配送", "荷物", "注文", "追跡", "届く", "返品",
    "交換", "返金", "キャンセル", "不良",
]
_PRESALES_WORDS = [
    "推荐", "想买", "哪款", "什么好", "比价", "耳机", "键盘", "保温杯", "充电宝",
    "おすすめ", "どれ", "いくら", "価格", "値段", "商品案内",
]


def clean_input(text: str) -> str:
    """输入清洗：strip 空白、压缩连续换行、去首尾重复（保持语义不变）。"""
    s = str(text or "").strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def detect_lang(text: str) -> str:
    """语言检测（粗判）：ja=含假名；zh=含汉字；否则按拉丁字母视为 en/other。"""
    s = text or ""
    if is_japanese(s):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", s):
        return "zh"
    return "en" if re.search(r"[a-zA-Z]", s) else "other"


def intent_score(text: str) -> dict[str, int]:
    """意图初判打分：{agent_name: 命中分}，0 分即未命中；未命中键不出现。

    候选：customer_service / presales / research / listing。
    """
    s = str(text or "").lower()
    scores: dict[str, int] = {}
    for name, words in (
        ("listing", _LISTING_WORDS),
        ("research", _RESEARCH_WORDS),
        ("customer_service", _CS_WORDS),
        ("presales", _PRESALES_WORDS),
    ):
        score = sum(1 for w in words if w in s)
        if score:
            scores[name] = score
    return scores