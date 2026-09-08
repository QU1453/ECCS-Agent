# -*- coding: utf-8 -*-
"""智能体配置槽：API Key / 请求地址 / 模型 ID 统一在此配置，所有智能体共用。

填写方式（二选一，推荐 .env）：
1. 复制 .env.example 为 .env，填写三个槽位（.env 已被 .gitignore 拦截，绝不入库）；
2. 直接设置同名环境变量（Docker / 云环境常用）。

各智能体（agents/）不要自行读环境变量，一律从本模块取值，
保证换模型 / 换服务商时只改这一处。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # 读取本地密钥配置（已被 .gitignore 拦截）

# ===== LLM 配置槽（所有智能体共用，OpenAI 兼容协议）=====
# API Key：真实密钥只放 .env / 环境变量，代码与仓库中不出现
API_KEY: str | None = os.getenv("OPENAI_API_KEY", "").strip() or None

# 请求地址：默认智谱 GLM 开放平台（与默认模型 glm-5.3-flash 配套，OpenAI 兼容协议）；
# 改用 OpenAI 官方时显式设为 https://api.openai.com/v1
_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
BASE_URL: str = os.getenv("OPENAI_BASE_URL", "").strip() or _DEFAULT_BASE_URL

# 模型 ID：本项目默认 GLM-5.3-Flash（智谱开放平台），兼容 OpenAI 协议
MODEL_ID: str = os.getenv("OPENAI_MODEL", "glm-5.3-flash").strip() or "glm-5.3-flash"

# ===== 服务配置 =====
HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
PORT: int = int(os.getenv("SERVER_PORT", "8623"))

# ===== 记忆系统配置槽（见 docs/memory-system-design.md §8）=====
# 短期窗口内的谈话数 K（可调高 8/10）
SHORT_TERM_CONVERSATIONS: int = int(os.getenv("SHORT_TERM_CONVERSATIONS", "5"))

# 每 M 个谈话触发一次二级总结（滚动合并进长期记忆）
L2_SUMMARY_INTERVAL: int = int(os.getenv("L2_SUMMARY_INTERVAL", "5"))

# 窗口组装 token 上限：超限按最新优先丢最旧谈话原文（绝不丢一级总结）
CONTEXT_TOKEN_GUARD: int = int(os.getenv("CONTEXT_TOKEN_GUARD", "24000"))

# 状态记忆（死规则）注入开关：False 时不再向 LLM 上下文注入铁律块
STATE_MEMORY_INJECT: bool = os.getenv("STATE_MEMORY_INJECT", "1") == "1"

# 热技能（评分最高）预注入条数
SKILL_HOT_INJECT_TOP: int = int(os.getenv("SKILL_HOT_INJECT_TOP", "3"))

# 总结智能体模型（默认跟随主模型 glm-5.3-flash）
SUMMARIZER_MODEL: str = os.getenv("SUMMARIZER_MODEL", "").strip() or MODEL_ID

# ===== 约束层配置槽（core/constraint/，见 README 约束层章节）=====
# 单轮输入长度上限（字符数；超长否决，防 token 灌注）
CONSTRAINT_MAX_INPUT_CHARS: int = int(os.getenv("CONSTRAINT_MAX_INPUT_CHARS", "4000"))

# 单会话轮次预算（超出后建议结束谈话开新会话）
CONSTRAINT_MAX_SESSION_TURNS: int = int(os.getenv("CONSTRAINT_MAX_SESSION_TURNS", "200"))

# 循环守卫：连续重复提问阈值（第 N 次相同问题时打断引导）
CONSTRAINT_LOOP_REPEAT_Q: int = int(os.getenv("CONSTRAINT_LOOP_REPEAT_Q", "3"))

# 循环守卫：连续雷同回复阈值
CONSTRAINT_LOOP_REPEAT_A: int = int(os.getenv("CONSTRAINT_LOOP_REPEAT_A", "3"))

# 循环守卫：连续兜底次数达到该值触发 LLM 熔断（该会话跳过 LLM 调用止损）
CONSTRAINT_LOOP_FALLBACK_TRIP: int = int(os.getenv("CONSTRAINT_LOOP_FALLBACK_TRIP", "4"))

