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

# 请求地址：OpenAI 官方留空即可；第三方 / 自部署（DeepSeek、通义、本地 vLLM 等）填 base_url
BASE_URL: str | None = os.getenv("OPENAI_BASE_URL", "").strip() or None

# 模型 ID：如 gpt-4o-mini / deepseek-chat / qwen-plus 等
MODEL_ID: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

# ===== 服务配置 =====
HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
PORT: int = int(os.getenv("SERVER_PORT", "8623"))
