# -*- coding: utf-8 -*-
"""输出校验：sanitize_reply——把 LLM 回复里的内部实现痕迹清洗掉。

目标（死规则之一：不向用户暴露工具内部 JSON）：
- 去掉 {"tool": ...} 形式的工具调用 JSON（LangChain 偶发把工具调用漏进正文）；
- 拦截 [工具名称] 括号引用泄露（如 [track_logistics] [query_order_info]）；
- 兜底：白名单未匹配的裸 JSON 片段一并截断风险串。

原则：宁可多洗，不可漏洗；清洗失败时返回原文本（不阻断回复链路）。
"""
from __future__ import annotations

import re

__all__ = ["sanitize_reply"]

# 工具名泄露：常见括号引用形式（中英文括号）
_TOOL_CALL_RE = re.compile(r"\{\s*\"tool\"\s*:\s*\"[^\"]+\".*?\}", re.S)
_TOOL_BRACKET_RE = re.compile(
    r"[\[【]\s*(track_logistics|query_order_info|handle_return|register_return"
    r"|recommend_products|check_demand|check_competition|calc_profit|run_product_research"
    r"|search_supplier|compare_supplier|draft_listing|check_images|price_strategy"
    r"|recommend_fulfillment|fetch_knowledge)\s*[\]】]", re.S,
)
# 偶发裸露的工具参数 JSON（保守：>32 字符的 {..} 块中含 "parameters"/"order_no" 等关键词才删）
_RAW_JSON_RE = re.compile(r"\{[^{}]{32,}\}", re.S)
_JSON_KEYS = ("parameters", "order_no", "product_code", "keywords", "chunk_id")


def sanitize_reply(text: str) -> str:
    """清洗回复文本；异常时不抛错、原样返回。"""
    try:
        s = str(text or "")
        s = _TOOL_CALL_RE.sub("", s)
        s = _TOOL_BRACKET_RE.sub("", s)
        s = _clean_raw_json(s)
        return s.strip()
    except Exception:  # noqa: BLE001 - 清洗失败不阻断回复
        return str(text or "")


def _clean_raw_json(s: str) -> str:
    """去残留裸 JSON 片段：仅当块内出现敏感 key 才移除，避免误伤正常文本。"""
    def _repl(m: re.Match) -> str:
        block = m.group(0)
        return "" if any(k in block for k in _JSON_KEYS) else block

    return _RAW_JSON_RE.sub(_repl, s)