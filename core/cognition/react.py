# -*- coding: utf-8 -*-
"""认知层-思考推理：ReAct 引擎（LangGraph create_react_agent 兼容封装）。

从 agents/base.py 提炼而来，通用部分统一收口在此：
- _build_react_agent：兼容 langgraph 1.x（prompt=）与旧版（messages_modifier/state_modifier=）；
- is_japanese / _JA_REPLY_HINT：日语识别（假名即日语）与日语敬体回复提示；
- 各专职智能体（agents/）与未来认知模块均从此导入，避免重复实现。

依赖约定：langgraph / langchain-openai 为可选依赖，缺依赖时
_HAS_LANGGRAPH=False，create_react_agent=None，上层走本地规则兜底。
"""
from __future__ import annotations

import re

__all__ = [
    "is_japanese", "_JA_REPLY_HINT", "JA_REPLY_HINT",
    "_build_react_agent", "create_react_agent", "_HAS_LANGGRAPH", "ChatOpenAI",
]

# ---- 日语识别与回复提示：命中假名即视为日语用户，LLM 回复切换为日语敬体 --------------
_JA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")  # 平假名 / 片假名
# 仅汉字无法区分中日（如"注文"），假名是日语的强特征；纯中文/英文不命中
_JA_REPLY_HINT = (
    "本次对话用户使用日语。请用日语回复，并遵守日本电商客服敬语规范：\n"
    "- 全程使用丁寧語・敬語（です・ます調），称呼顾客为「お客様」；\n"
    "- 常用服务用语：「かしこまりました」「恐れ入りますが」「お問い合わせいただきありがとうございます」；\n"
    "- 金额用「円」、日期用日本书写习惯；专有名词（商品名、配送公司）保持原文。"
)
# 兼容别名（旧代码可能直接引用）
JA_REPLY_HINT = _JA_REPLY_HINT


def is_japanese(text: str) -> bool:
    """是否日语用户输入（含假名即视为日语；供 LLM 提示与兜底双语回复共用）。"""
    return bool(_JA_RE.search(text or ""))


# ---- LangGraph 相关为可选依赖：装不上也能以"本地兜底模式"运行 -------------------
try:
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover - 离线环境 / 未安装依赖时
    _HAS_LANGGRAPH = False
    create_react_agent = None
    ChatOpenAI = None


def _build_react_agent(llm, tools, prompt, checkpointer=None):
    """兼容不同 langgraph 版本：1.x 用 prompt=，旧版用 messages_modifier/state_modifier=。

    prompt 可为 str 或 callable：callable 接收当前 state（dict 或消息列表，视版本而定），
    返回完整模型输入消息列表（固定系统提示 + 每轮动态上下文 + 历史消息）。
    """
    for prompt_kw in ("prompt", "messages_modifier", "state_modifier"):
        try:
            return create_react_agent(
                model=llm, tools=tools, checkpointer=checkpointer, **{prompt_kw: prompt}
            )
        except TypeError:
            continue
    raise TypeError("create_react_agent 参数签名不兼容")