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
# API Key：优先读 GLM_API（智谱密钥环境变量名），兼容旧槽位 OPENAI_API_KEY；
# 真实密钥只放 .env / 环境变量，代码与仓库中不出现
API_KEY: str | None = (
    os.getenv("GLM_API", "").strip()
    or os.getenv("OPENAI_API_KEY", "").strip()
    or None
)

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

# ===== 验证层配置槽（core/constraint/validator.py：工具调用前置四道检查）=====
# 权限模式四档：plan（只读）/ ask（写操作需人工确认）/ accept（低风险写自动放行）/ bypass（全放开）
# 项目精度优先：默认只开 plan，待逐步信任机制就绪后逐档放开
AGENT_PERMISSION_MODE: str = os.getenv("AGENT_PERMISSION_MODE", "plan").strip().lower()

# 写/执行类工具名单（这些工具会改变状态，plan/ask 模式下被拦截）；
# 新增有副作用的工具必须在此登记，或命名命中 TOOL_WRITE_NAME_RE
TOOL_WRITE_TOOLS: set[str] = {
    t.strip() for t in os.getenv(
        "TOOL_WRITE_TOOLS", "register_return,handle_return").split(",") if t.strip()
}

# 路径检查：允许访问的根目录（绝对路径必须在根内；相对路径禁止 .. 穿越）
TOOL_PATH_ROOTS: list[str] = [
    p.strip() for p in os.getenv("TOOL_PATH_ROOTS", str(BASE_DIR)).split(";") if p.strip()
]

# 网络访问策略：deny（全禁）/ allowlist（仅白名单域名）/ allow（放开，仍禁云元数据端点）
TOOL_NET_POLICY: str = os.getenv("TOOL_NET_POLICY", "allowlist").strip().lower()
TOOL_NET_ALLOW_HOSTS: list[str] = [
    h.strip().lower() for h in os.getenv("TOOL_NET_ALLOW_HOSTS", "").split(",") if h.strip()
]

# ===== 循环守卫配置槽（core/constraint/tool_loop.py：agent 循环防打转）=====
# 单会话工具调用总量上限（超出即熔断，后续工具调用全部拒绝）
TOOL_LOOP_MAX_CALLS: int = int(os.getenv("TOOL_LOOP_MAX_CALLS", "40"))

# 连续失败次数上限（工具连续抛错达阈值即熔断）
TOOL_LOOP_MAX_CONSEC_FAILS: int = int(os.getenv("TOOL_LOOP_MAX_CONSEC_FAILS", "5"))

# 完全相同调用检测的记录窗口（保留最近 N 条调用；签名 = MD5(工具名+参数)前12位 + 结果前20字符）
TOOL_LOOP_IDENTICAL_WINDOW: int = int(os.getenv("TOOL_LOOP_IDENTICAL_WINDOW", "10"))

# ===== 预算熔断配置槽（core/constraint/budget.py）=====
# 单会话 token 总预算（输入+输出累计，超出后 LLM 熔断转离线答复）
SESSION_TOKEN_BUDGET: int = int(os.getenv("SESSION_TOKEN_BUDGET", "100000"))

# 单会话金额预算（元；0 = 不启用金额熔断）
SESSION_COST_BUDGET_CNY: float = float(os.getenv("SESSION_COST_BUDGET_CNY", "0"))

# 计费单价（元 / 百万 token）：按智谱账单实际价格填写，默认 0 = 只按 token 熔断
PRICE_INPUT_CNY_PER_M: float = float(os.getenv("PRICE_INPUT_CNY_PER_M", "0"))
PRICE_OUTPUT_CNY_PER_M: float = float(os.getenv("PRICE_OUTPUT_CNY_PER_M", "0"))

# 上下文五段预算分配（百分比，合计 100）：
# 输出预留 15% / 系统提示词 10% / 长期记忆 5% / 当前任务 20% / 历史会话（短期+知识库）50%
BUDGET_PCT_OUTPUT: int = int(os.getenv("BUDGET_PCT_OUTPUT", "15"))
BUDGET_PCT_SYSTEM: int = int(os.getenv("BUDGET_PCT_SYSTEM", "10"))
BUDGET_PCT_LONG_TERM: int = int(os.getenv("BUDGET_PCT_LONG_TERM", "5"))
BUDGET_PCT_TASK: int = int(os.getenv("BUDGET_PCT_TASK", "20"))
BUDGET_PCT_HISTORY: int = int(os.getenv("BUDGET_PCT_HISTORY", "50"))

