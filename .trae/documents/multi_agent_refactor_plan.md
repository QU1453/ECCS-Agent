# 多智能体改造（仅限 agent.py 单文件）实现计划

## Repository Research

### 当前 `agent.py` 结构（单文件现状）
- **`SYSTEM_PROMPT`**：单一硬编码提示词，写死「当前以中文演示」。
- **`_HAS_LANGGRAPH` / `_build_react_agent()`**：LangGraph 可选依赖 + 多版本兼容的 graph 构建。
- **`class Agent`**：`__init__` 里立刻构建**一个** graph，绑定全部 4 个工具（订单/物流/退换/推荐）+ 同一个 SYSTEM_PROMPT；`answer()` 直接调 graph，无路由。
- **`Agent._format_result()`**：从 graph 返回消息里提取 reply，再扫描 tool_calls，还原 `intent: order/recommend` + 卡片 `data`。
- **`classic_reply(q)`**：本地兜底正则路由（中文），订单/售后/推荐/闲聊/默认 5 分支，直接返回 `{reply, intent, data}`。
- **卡片 helpers**：`_card_items()`、`_order_card()`，被 `Agent._format_result` 和 `classic_reply` 复用。

### 关键约束（用户明确要求）
- ✅ **只改 `/workspace/agent.py`**：`server.py / tools.py / Dockerfile / ui/*` 一律不动。
- ✅ **对外签名零变化**：`server.py` 执行 `from agent import Agent, classic_reply`，以及 `Agent(api_key, base_url, model)`、`agent.answer(q, history)`、`agent.available`、`agent.reason`、`classic_reply(q)` 这 6 个使用方式必须**完全兼容**。
- ✅ **不新增目录/文件**：`agents/`、`base.py` 之类全部砍掉，所有逻辑收敛在 `agent.py`。
- ✅ **兜底不能断**：未配 Key 时 `classic_reply` 必须继续工作，且新增日语/人工分支也走本地关键词。

---

## Files and Modules

| 文件 | 变更类型 | 预期变更 |
| --- | --- | --- |
| `/workspace/agent.py` | 修改 | 单文件内完成：①意图分类+路由；②按 `(intent, lang)` 动态切换 SYSTEM_PROMPT 与工具子集，多 graph 缓存；③日语分支（LLM 版 + classic 兜底版）；④人工接管 intent 返回；其余文件保持原样。 |

其他文件（`server.py / tools.py / Dockerfile / ui/* / requirements.txt`）**零改动**。

---

## Implementation Steps

### 1. 新增「语言 + 意图」分类函数（文件顶部，与 classic_reply 同层）
1. **`_detect_lang(q: str) -> str`**：用正则 `[ぁ-んァ-ヶー]` 扫描输入，命中返回 `"ja"`，否则默认 `"zh"`。
2. **`_classify_by_regex(q: str) -> tuple[str, str]`**：返回 `(intent, lang)`。
   - 先 `lang = _detect_lang(q)`。
   - 再按优先级命中**第一个**正则即返回（覆盖中英日三语关键词）：
     | intent | 中文关键词 | 日文关键词 |
     | --- | --- | --- |
     | `human` | 人工、真人、客服、听不懂、转人、帮我接 | オペレーター、人間、わかりません、繋いで |
     | `after_sales` | 退、换、退款、售后、质量、坏了、瑕疵 | 返品、交換、返金、不良、欠陥 |
     | `recommend` | 推荐、什么好、哪款、耳机、键盘、保温杯、充电宝 | おすすめ、人気、どれが、イヤホン、キーボード |
     | `order` | 物流、快递、到哪、发货、订单、单号、签收、付款 | 注文、配送、到着、追跡、発送、荷物 |
     | `chitchat` | 在吗、你好、哈喽、hi、hello、谢谢、再见 | こんにちは、はじめまして、ありがとう、さようなら |
     | `unknown` | — | — |
3. **`_classify_by_llm(q: str, lang: str, llm: ChatOpenAI | None) -> str`**（文件级纯函数，无状态）：
   - 仅当 `llm` 非空且 regex 返回 `unknown` 时调用。
   - 用 `llm.invoke(messages)` 做**单次纯分类**（不跑 LangGraph、不调用工具）。
   - Prompt 模板按语言构造：
     - 中文模板：`"将用户问题分类为 order/after_sales/recommend/chitchat/human/unknown 之一，只返回 JSON {\"intent\":\"...\"}。用户输入：{q}"`
     - 日语模板：`"ユーザーの質問を order/after_sales/recommend/chitchat/human/unknown のいずれかに分類し、JSON {\"intent\":\"...\"} だけを返してください。入力：{q}"`
   - 外层 `try/except` + JSON 解析失败一律返回 `"unknown"`。

### 2. 改造 `Agent` 内部：多 specialist graph 缓存 + 路由分发
4. **移除 `__init__` 里「立刻建一个 graph」的代码**，改为懒加载缓存：
   - 新增实例成员：
     ```python
     self._llm: ChatOpenAI | None      # 只在 Key 可用时创建（意图精分 + 各 specialist 共用）
     self._graphs: dict[tuple, Any]    # key=(intent, lang) → CompiledGraph，首次访问创建
     self._prompt_cache: dict          # (intent, lang) → 对应 SYSTEM_PROMPT 字符串预生成
     ```
   - `_build_react_agent()` 保留（原方法不变），但改为内部按需调用（不再在 `__init__` 里跑一次）。
5. **新增 `_prompt_for(intent: str, lang: str) -> str` 实例方法**：按 2×5=10 种组合生成专用 SYSTEM_PROMPT：
   - **lang=zh**：
     - `order`：专注订单/物流查询的中文客服 prompt（说明可用工具 query_order_info + track_logistics）
     - `after_sales`：专注退换货/退款的中文客服（工具 handle_return）
     - `recommend`：专注商品推荐（工具 recommend_products）
     - `chitchat / unknown`（通用 fallback）：原 PROMPT 去掉「当前以中文演示」硬编码，改为「使用用户输入的语言回复」
   - **lang=ja**（です/ます体强约束，加粗强调）：
     - `order`：日语订单配送查询，丁寧語，工具同上
     - `after_sales`：日语返品交換対応
     - `recommend`：日语商品推薦
     - `chitchat / unknown`（日语通用）：「あなたはECCS越境ECのAIカスタマーサポート。必ずです・ます体で、丁寧に回答。金額や日時はツールの事実を使用。」
   - 所有 prompt 末尾统一要求：使用与用户相同的语言，不要暴露工具名/JSON 内部细节。
6. **新增 `_tools_for(intent: str) -> list` 实例方法**：返回工具子集（体现多 specialist 工具隔离）：
   - `order` → `[query_order_info, track_logistics]`
   - `after_sales` → `[handle_return]`
   - `recommend` → `[recommend_products]`
   - `chitchat / unknown / human` → `[query_order_info, track_logistics, handle_return, recommend_products]`（全量兜底，保持原能力）
7. **新增 `_get_graph(intent: str, lang: str)` 实例方法**：
   - 查 `self._graphs[(intent, lang)]` 命中则直接返回。
   - 未命中：调用 `_build_react_agent(self._llm, self._tools_for(intent))`，并把 `prompt=SYSTEM_PROMPT` 参数替换为 `self._prompt_for(intent, lang)`。
   - 写回缓存，返回 graph。
   - 若 `self._llm is None`（无 Key 模式），直接返回 `None`。
8. **重写 `answer(question, history)` 主流程**（核心路由骨架）：
   ```
   1. intent, lang = _classify_by_regex(question)
   2. if intent == "human":
        直接返回 _build_human_reply(lang)   # 不跑 LLM，纯文本构造
   3. if intent == "unknown" and self._llm:
        intent = _classify_by_llm(question, lang, self._llm)
   4. graph = self._get_graph(intent, lang)    # 命中 specialist graph 缓存
   5. if graph is None: return None            # 触发 server 走 classic_reply 兜底
   6. result = graph.invoke(messages=...)      # 正常 ReAct
   7. result = self._format_result(result)
   8. 保证 result["intent"] 存在（若 _format_result 没给出 tool_based intent，则回填路由的 intent）
   9. return result
   ```
   - 辅助：`_build_human_reply(lang) -> dict`：
     - `zh`：`reply = "已为您转接人工客服，我们的专员会尽快与您联系～"，intent = "human"，data = None`
     - `ja`：`reply = "オペレーターにお繋ぎいたします。担当者がまもなく対応いたします～"，intent = "human"`
   - 第 8 步回填 `intent`：如果用户问「イヤホンのおすすめ」LLM 调用了 `recommend_products`，`_format_result` 会正确填 `recommend`；但如果 specialist 跑了没调用工具（闲聊），`_format_result` 返回的是 `intent=none`，我们覆盖为路由时的 intent，便于日志审计（server 层对此字段是"只要 reply 和 data 正确即可"，intent 值改变不会影响现有前端渲染，因为 server 不处理 `chitchat / unknown` 这些新 intent，前端只识别 order/recommend/human，其余都按纯文本气泡渲染）。

### 3. 扩展 `classic_reply`：日语分支 + 人工接管分支
9. 在 `classic_reply(q: str)` 的开头加语言检测 + 人工接管检测：
   - 步骤 0：`lang = _detect_lang(q)`
   - 步骤 1：人工关键词命中（中日）→ 返回 `intent: human` 的中英文对应文本。
   - 步骤 2：若 `lang == "ja"`，新增 **日语关键词分支**（替换现有中文分支）：
     ```
     注文/配送/荷物 → 查订单 2026081200012，回复です/ます体 + 同一 order_card
     返品/交換/不良 → register_return，です/ます体说明 3 种方案
     おすすめ/人気/イヤホン → recommend_for 3 件 + です/ます体推荐文
     こんにちは/はじめまして → 问候
     其他 → 默认 ECCS 客服日语提示
     ```
   - 步骤 3：若 `lang == "zh"` → 保留**原有中文分支**（代码逐字不动，确保中文兜底行为 100% 兼容）。
   - 卡片 data 结构（`_order_card / _card_items`）全复用，订单号、商品名、价格等都是数字或通用文字，前端照渲，不影响日文文本气泡。

### 4. `available` 与 `reason` 兼容
10. `Agent.available` 逻辑：返回 `self._llm is not None`（原来判断 graph，现在改为判断 LLM 是否初始化成功——本质等价，Key + 依赖都 OK 时为 True）。
11. `Agent.reason` 初始化逻辑不变；新增懒加载时若某 specialist graph 构建失败，只在实例内记日志（不影响 available 状态，也不抛错），下次同 key 再请求继续尝试或复用其他 specialist 的 graph。

---

## Dependencies and Considerations
- **LangGraph 可选依赖**：`_classify_by_llm` 用的是 `ChatOpenAI` 单独调用（不是 LangGraph graph），它的 import 已经包含在现有 `try: from langchain_openai import ChatOpenAI` 中，**无需新依赖**。
- **无 Key 兜底**：`classic_reply` 的中文原分支完全保留一字未动；新增分支只在语言/人工命中时触发，回归风险 = 0。
- **工具函数来源**：`from tools import (...)` 那一行原样保留，所有 specialist 复用同一批工具，与 `server.py / tools.py` 零耦合。
- **`server.py` 零改动的原因**：
  - 导入：`from agent import Agent, classic_reply` 名字不变。
  - `AgentService.ask()`：`agent.answer(message, history)` 返回值仍是 `{reply, intent, data}`，只是多了 `human` 意图——server 不区分 intent，直接 JSONResponse 原样返回前端；前端 `intent` 目前只处理 `order / recommend / none`（其余即 `none` 行为，纯气泡），但 human 回复的文本本身已包含「已转接人工」字样，用户可读可懂，完全不破坏。若以后要在前端加视觉高亮，再在 app.js 加即可，本次计划不动。
  - `/api/status`：`agent.available`、`agent.model`、`agent.reason` 三个属性签名均保留。
- **Dockerfile 零改动的原因**：没新增文件，`COPY server.py agent.py tools.py ./` 就够了。

---

## Validation

（所有验证都只依赖 server.py 原端口 8623，不新增命令）

1. **导入兼容**：
   ```bash
   python -c "from agent import Agent, classic_reply; a=Agent(None); print('available=', a.available, 'reason=', a.reason)"
   # 期望 available=False，reason 是未配置 Key 文案，无异常
   ```
2. **未配 Key 兜底 + 中文回归**：
   ```bash
   python -c "from agent import classic_reply; print(classic_reply('我的订单到哪了'))"
   # 返回 intent=order，与改造前文本一致
   ```
3. **未配 Key 兜底 + 日语新分支**：
   ```bash
   python -c "from agent import classic_reply; r=classic_reply('イヤホンのおすすめは？'); print(r['reply'][:30], r['intent'])"
   # 期望 reply 含です/ます体，intent=recommend
   ```
4. **未配 Key 兜底 + 人工接管**：
   ```bash
   python -c "from agent import classic_reply; r=classic_reply('帮我转人工'); print(r)"
   # 期望 intent=human，reply 含"转接人工客服"
   python -c "from agent import classic_reply; r=classic_reply('オペレーターに繋いで'); print(r)"
   # 期望 intent=human，reply 日语
   ```
5. **配 Key 后端到端（若当前环境有 Key）**：
   ```bash
   python server.py &
   curl -X POST http://127.0.0.1:8623/api/ask -H 'Content-Type: application/json' -d '{"message":"イヤホンのおすすめは何ですか"}'
   # 期望 reply 日语です/ます体，intent=recommend，data.items 存在
   curl -X POST http://127.0.0.1:8623/api/ask -H 'Content-Type: application/json' -d '{"message":"我听不懂，转真人客服"}'
   # 期望 intent=human
   ```
6. **卡片渲染**：在浏览器打开 http://127.0.0.1:8623 ，快捷按钮「物流 / 退货 / 推荐」依次点击，确认卡片渲染正常；手动输入一句日语订单查询，确认气泡显示日语、订单卡正常。

---

## Risks

| 风险 | 影响 | 处理方式 |
| --- | --- | --- |
| 单文件代码行数膨胀（agent.py 从 200 行 → 约 500 行） | 可读性略下降 | 内部用清晰分段注释 `# ==== 意图分类 ====` `# ==== Agent 路由 ====` `# ==== classic_reply 兜底 ====` 分隔，函数名自解释 |
| LLM 意图分类返回非法 JSON | 路由错乱 | `try/except + fallback unknown`，unknown 会走「通用中文/日语」 specialist（工具全集），等价于原单智能体行为，不会死 |
| `_get_graph` 缓存 key 冲突（intent/lang 组合写错） | 用了错误的 prompt 或工具集 | 组合表使用 Enum 或常量化字符串，避免硬编码错别字；首次 `_get_graph` 打印一次 `(intent, lang, tools_names, preview_prompt_first_line)` 到 `reason` 不现实，改为在 DEBUG 环境下 `print` 一次即可，首测完删除 |
| 日语 specialist 回复中夹杂中文（因工具返回中文商品名） | 演示观感略瑕疵 | SYSTEM_PROMPT 明确指令：商品名/订单号原样使用，其余连接词和说明必须日语；实际 LLM 能做到，demo 时若担心可提前跑一遍选最好的展示案例 |
| 多 graph 缓存长期不回收 → 内存 | 可忽略 | 最多 5(intent)×2(lang)=10 个 graph，每个只是 Python 对象 + LLM 引用；单进程 MB 级，无需 LRU |
| `_format_result` 回填 intent 时覆盖了 tool 检测结果 | 误标 | 回填逻辑必须写为：`result["intent"] = result.get("intent") or routing_intent`（只有 tool 没检测到时才用路由 intent） |
