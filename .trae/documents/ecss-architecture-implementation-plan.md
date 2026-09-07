# ECCS Agent 架构开发实施计划

> 依据：[architecture.md](/workspace/docs/architecture.md) + [memory-system-design.md](/workspace/docs/memory-system-design.md)
> 模式：分阶段实施（P0 → P8），每阶段独立可验证，全部完成后一键推送。

---

## 1. 摘要（Summary）

把项目从「买家客服」重构为「卖家工作台 + 五模块记忆 + 认知层」，完整落地两份开发文档：

- **记忆层**：权限体系（L0~L9）+ 短期（谈话粒度 K 窗口）+ 长期（二级总结范式条目）+ 知识库（索引先行两阶段）+ 状态记忆（死规则）+ 技能记忆（事/的/痛/解）
- **工具调度**：双层注册表（模块局部 + 应用全局），调用走 `level` 鉴权 + `memory_audit` 审计
- **业务层**：新增选品四步验证、Listing 四步工具与对应智能体，supervisor 路由扩展
- **认知层**：core/ 五大模块（感知/思考/调度/反思/输出）；ReAct 引擎提炼到 `core/cognition/react.py`，旧智能体继续可用
- **端到端**：server 新增谈话开始/结束 API，UI 升级为双工作台（选品 / Listing）

## 2. 现状分析（Current State Analysis）

已探查确认的关键事实：

| 文件 | 现状 | 计划中的作用 |
| --- | --- | --- |
| config.py | API_KEY / BASE_URL / MODEL_ID / HOST / PORT 五个槽位 | 追加记忆参数槽位（K/M/token 守卫等），不改现有项 |
| agents/base.py | ReActAgentBase + `_build_react_agent` + `build_memory_context` + 日语识别 + 卡片提取 | ReAct 引擎部分提炼到 `core/cognition/react.py`，本文件改为薄封装（旧智能体零改动） |
| agents/supervisor.py | 规则路由（customer_service / presales）+ specialists 注册表 + `agent_session_id` 隔离 | 追加 research / listing 意图与注册；结束谈话编排 |
| memory/\_\_init\_\_.py | `get_short_term` / `get_memory` 单例，`HAS_LONG_TERM`（hnswlib 可选降级） | 保持既有兼容层；新增模块统一走 MemoryManager |
| memory/manager.py | 聚合 short_term + long_term | 扩展聚合五模块 + caller 鉴权接入 |
| memory/short_term/memory.py | SqliteSaver + summaries 表（按消息条数压缩） | 挂接谈话注册表；消息条数压缩保留为窗口内兜底 |
| server.py | /api/ask /api/clear /api/status | 追加 /api/conversation/start、/api/conversation/end；ask 走 orchestrator |
| ui/index.html | 单对话客服界面（中日切换） | 升级为双工作台（选品 / Listing），保留中日切换与卡片渲染 |
| tools/\_\_init\_\_.py | re-export 订单/售后/推荐/商品库 | 不变；新增 research/supplier/listing 工具模块 |

约束确认：
- **旧智能体（customer_service / presales）代码不动、不删**（用户已定：意向删除，转型完成后再说）。
- **所有数据文件**（sqlite/.hnsw）继续放 `memory/**/data/`，已被 .gitignore 拦截，不进仓库。
- 推送前必须执行密钥检查（项目协作铁律）。

## 3. 实施顺序与依赖

```
P0 权限 + 注册表 ──┬──► P1 谈话窗口 ──► P2 一级总结 ──► P3 二级总结/长期记忆
                   ├──► P4 知识库
                   ├──► P5 状态记忆
                   ├──► P6 技能记忆
                   └──► P7 业务智能体 + 编排 + UI ──► P8 收尾推送
```

P0 先行：后续所有记忆读写与工具调用都过它。P1–P3 是总结管线（串行依赖），P4/P5/P6 互相独立。P7 整合 P1~P6 与业务智能体。

## 4. 分阶段详细改动

### P0 权限层 + 双层注册表骨架

**新建 memory/access.py**
- `LEVEL_ORDER = {"L0": 0, ..., "L3": 3, "L9": 9}`（L9=人类）
- `MemoryCaller(name: str, level: str, session_id: str = "")` dataclass
- `AccessError(Exception)`
- 权限矩阵（内置，按 memory-system-design.md §6.2）：

| 模块 | 写 | 改/删 |
| --- | --- | --- |
| short_term | L0（仅本人会话） | L0 本人 / L9 |
| long_term | L1 | L3 / L9 |
| knowledge | L1 | L3 / L9 |
| skill | L2 | L2（晋升降级）/ L3 |
| state | L3 | L3 / L9 |

- `guard(module: str, op: str, caller: MemoryCaller) -> None`：默认拒绝，显式授权，越权 `raise AccessError`
- `AuditLogger`：独立 SQLite `memory/data/access.sqlite`，表 `memory_audit(ts, actor, actor_level, action, module, target_id, session_id, result)`；`log(...)` 吞异常不阻断主流程

**新建 core/dispatch/registry.py**
- `ToolSpec` dataclass：`name / fn / module / description / schema / level / cost / owner`
- `LocalRegistry(owner: str)`：`.register(**meta)` 装饰器（`global_=True` 时同步注册全局）、`.get(name)`、`.snapshot()`（供 LLM 工具清单）
- `GLOBAL_REGISTRY`：`register_tool(spec)`、`resolve(name)`、`call(name, params, caller)` —— 流程：查工具 → `level` 校验（caller >= 工具所需等级）→ 执行 → `AuditLogger.log` 成败。局部优先由各 LocalRegistry 的 `call_local` 实现：先查自己，未命中回退 `GLOBAL_REGISTRY.call`
- `llm_tool_spec()`：把注册表序列化为 LLM 用的 `{name, description, parameters}` 列表

**新建空包**：core/\_\_init\_\_.py、core/dispatch/\_\_init\_\_.py

**验收**：`guard()` 越权抛错且审计有记录；装饰器注册 → 全局解析 → call 全链路跑通（无 langgraph 依赖即可测）。

### P1 谈话注册 + 短期窗口 + token 守卫

**新建 memory/short_term/registry.py**
- `ConversationRegistry(conn)`：建表 `conversation_registry(session_id PK, user_id, agent_name, status, started_at, ended_at, summary_json, rolled_up)`
- 方法：`start(session_id, user_id, agent_name=None)`、`update_agent(session_id, agent_name)`、`end(session_id, summary_json=None)`、`set_summary(...)`、`pending_rollup(limit)`（未二级总结的已结束谈话，按结束时间升序）、`recent_closed(k)`、`mark_rolled_up(ids)`

**改造 memory/short_term/memory.py**
- `ShortTermMemory.__init__` 内初始化 `self.registry = ConversationRegistry(self._conn)`（同连接）
- 新增 `window_context(user_id=None, k=None, token_guard=None) -> list[dict]`：
  - 取 `recent_closed(k)` + 当前进行中的会话
  - 每块 = `{conversation_id, topic, summary, raw: [(role, content)...]}`；raw 原文从该谈话 `agent_name` 对应 checkpoint 线程取（`agent_session_id(agent_name, conversation_id)`），无 agent 记录时只带 summary
  - token 估算复用 `long_term.chunker.estimate_tokens`；超 `token_guard` 时按最新优先**丢最旧谈话的 raw（绝不丢 summary）**，头部打标 `[已省略更早谈话 N 次]`
- 新增 `record_turn(session_id, agent_name)`（supervisor 每次路由后调用）
- 保留现有消息条数压缩链路不动（窗口内兜底）

**改造 config.py** 追加槽位：
```python
SHORT_TERM_CONVERSATIONS = int(os.getenv("SHORT_TERM_CONVERSATIONS", "5"))   # 谈话窗口 K
L2_SUMMARY_INTERVAL = int(os.getenv("L2_SUMMARY_INTERVAL", "5"))             # 二级总结间隔 M
CONTEXT_TOKEN_GUARD = int(os.getenv("CONTEXT_TOKEN_GUARD", "24000"))         # 窗口 token 上限
STATE_MEMORY_INJECT = os.getenv("STATE_MEMORY_INJECT", "1") == "1"           # 死规则注入开关
SKILL_HOT_INJECT_TOP = int(os.getenv("SKILL_HOT_INJECT_TOP", "3"))           # 热技能预注入条数
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", "").strip() or MODEL_ID     # 总结智能体模型
```

**扩展 memory/manager.py**：代理 `start_conversation / end_conversation / record_turn / window_context`。

**验收**：注册 6 个谈话 → `window_context(k=5)` 只含最近 5 个；token_guard 调小后最旧 raw 被裁、summary 保留、打标正确。

### P2 一级总结（对话结束触发）

**新建 agents/summarizer.py**
- `SUMMARIZER_PROMPT`：对话原文 → 一级总结范式 JSON（memory-system-design.md §4.2 十个字段）
- `class SummarizerAgent`：`__init__(api_key, base_url, model=SUMMARIZER_MODEL)`；`available`；`summarize(messages: str) -> dict | None`（LLM 输出 → `_parse_and_validate`）
- `_parse_and_validate(text) -> dict`：JSON 解析 + 字段类型校验（范式校验器），坏产出返回 None（不落库）
- `fallback_summary(messages, topic_hint)`：无 Key / LLM 失败时的规则兜底，保证演示可跑
- 写库 caller 固定 `MemoryCaller("summarizer", "L1", session_id)`

**改造 agents/supervisor.py**
- `__init__` 增持 `SummarizerAgent`
- 新增 `end_conversation(session_id, user_id) -> dict`：registry 找该谈话 agent → 取 checkpoint 原文 → summarize → 校验 → `set_summary` → 若 `pending_rollup` 数达 `L2_SUMMARY_INTERVAL` 则触发二级总结（P3）→ 返回 `{ok, summary, second_stage_triggered}`

**改造 server.py**：新增 `POST /api/conversation/end`（body: session_id, user_id）；`AgentService.ask` 每次路由后调 `record_turn`。

**验收**：有 Key 产出合规范式 JSON 落 registry；无 Key fallback 可用；坏 JSON 不落库。

### P3 二级总结 → 长期记忆

**改造 memory/long_term/memory.py**
- 建表 `long_term_entries(id PK, user_id, entry_type, content, confidence, source_conversations, tags, status, created_by, created_at)`
- `save_long_term_entry(...)`、`get_long_term_entries(user_id, entry_type=None, limit=20)`、`mark_conversations_rolled_up(ids)`

**改造 agents/summarizer.py**
- `second_stage(entries: list[dict], previous: list[dict]) -> list[dict]`：M 个一级总结滚动合并 → 1~N 条二级范式（entry_type ∈ user_profile/fact/pending_item/preference，含 confidence 与 source_conversations）
- 无 Key 降级 `fallback_second_stage`（保留 pending_items / 高频 fact 的规则提取）

**改造 agents/supervisor.py**：`end_conversation` 内触发——`pending_rollup` ≥ M → 二级总结 → `save_long_term_entry`（caller L1）→ `mark_conversations_rolled_up`。

**验收**：第 5/10 个谈话结束后长期记忆条目正确落库、来源可回溯；已合谈话不重复合并。

### P4 知识库（索引先行，两阶段检索）

**新建 memory/knowledge/\_\_init\_\_.py、indexer.py、retriever.py**
- `KnowledgeBase(base_dir)`：独立 SQLite `memory/data/knowledge.sqlite`
  - 表：`kb_documents(id, user_id, title, raw_text, created_by, created_at)`、`kb_chunks(id, doc_id, seq, text)`、`kb_index(id, chunk_id, brief, keywords, title, created_by, created_at)`
- indexer：`ingest(user_id, title, text, caller)`（写 guard L1）——分块复用 `long_term.chunker.chunk_text`（hnswlib 缺时内置简单分段兜底）→ 每块生成索引条目：有 LLM 用 brief 版提示（1–2 句描述 + 关键词），无 Key 降级"块前 60 字 + 高频词"
- retriever：`get_index(user_id, filter_keywords=None, limit=50)` 只返回 `[{chunk_id, title, brief, keywords}]`；`fetch_knowledge(chunk_ids)` 只取被选中块全文
- v0.1 不做 ANN 预筛（索引列表 + 关键词过滤已够演示），留 `# TODO: ANN 粗筛` 注释位

**扩展 memory/manager.py**：持 `KnowledgeBase`，透出 `ingest_knowledge / get_index / fetch_knowledge`（带鉴权）。

**验收**：入库一篇文档 → get_index 见各块简述 → 按 chunk_id 取两块全文且内容正确。

### P5 状态记忆（死规则）

**新建 memory/state/\_\_init\_\_.py、memory.py**
- `StateMemory(base_dir)`：SQLite `memory/data/state.sqlite`，表 `state_memory(id, rule_text, scope, agent_types, priority, enabled, created_by, updated_at)`
- `add_rule(rule_text, scope="global", agent_types="", caller)`（guard L3）；`set_enabled(rule_id, enabled, caller)`（L3）；`get_rules(scope, agent_type=None)`；`inject_block(agent_type=None) -> str`：enabled 且 scope 匹配按 priority 拼「铁律」块，`STATE_MEMORY_INJECT=False` 返回 ""
- 预置 5 条种子死规则（caller=L9）：不得编造订单号/数据；回复跟随用户语言；不暴露工具内部 JSON；不读写本机 C 盘；密钥不入库

**扩展 memory/manager.py**：持 `StateMemory`，透出 `add_rule / inject_block / set_rule_enabled`。

**验收**：L3 写成功、L0 写被拒留审计；inject_block 只含 enabled 且 scope 匹配规则。

### P6 技能记忆（事/的/痛/解 + 反馈闭环）

**新建 memory/skill/\_\_init\_\_.py、memory.py**
- `SkillMemory(base_dir)`：SQLite `memory/data/skill.sqlite`，表 `skill_memory(id, situation, goal, pain, solution, tags, trigger, successes, failures, score, status, created_by, updated_at)`
- `add_skill(...)`（guard L2）；`search_skills(text, top_k=5)`（tags/关键词匹配 + score 排序，ANN 留 TODO）；`feedback(skill_id, success: bool)`（score = successes/(successes+failures)，连续 3 次失败 `status='archived'`）；`hot_skills(top)`

**新建 core/reflection/（reflector.py + skill_writer.py + \_\_init\_\_.py）**
- `reflector.py`：`ReflectionAgent(L2)`——`distill_skill(situation, goal, pain, solution)` 包装 `SkillMemory.add_skill`；`reflect_on_failure(session_id)`（v0.1 占位：输出提示语，后续接失败会话分析）
- `skill_writer.py`：`SKILL_WRITER_PROMPT` + `build_skill_entries(transcript)`（LLM 从复盘文本提炼四要素，无 Key 返回 []）

**扩展 memory/manager.py**：持 `SkillMemory`，透出 `add_skill / search_skills / skill_feedback / hot_skills`。

**验收**：L2 写入成功、L0 被拒；search 命中相关技能；连续失败后技能 archived。

### P7 认知层集成 + 业务智能体 + 编排 + UI

**新建 core/cognition/react.py（ReAct 引擎提炼）**
- 把 agents/base.py 里的 `_build_react_agent`、`_JA_RE`/`is_japanese`/`_JA_REPLY_HINT` 移入；base.py 改为 `from core.cognition.react import ...` 再导出（旧智能体零改动）

**新建 core/perception/（input.py + context.py + session.py + \_\_init\_\_.py）**
- `input.py`：`clean_input(text)`（strip/去重输入）、`detect_lang(text)`（复用 is_japanese）、`intent_score(text) -> dict[agent_name, score]`（初判打分，规则词表）
- `context.py`：`assemble_context(mm, user_id, session_id, agent_name, question) -> dict`：状态死规则注入块 + 长期记忆条目（最近 10 条）+ 知识库索引提示 + 短期窗口摘要行（仅最近闭谈话的 topic 列表）+ token 估算
- `session.py`：`start_conversation(user_id) -> session_id`（生成新 id 并 registry.start）；`end_conversation(mm, sup, session_id, user_id)`（调 supervisor 管线）

**新建 core/dispatch/orchestrator.py**
- `Orchestrator(supervisor)`：`answer(question, session_id, user_id)`：perception.input → intent_score → supervisor.answer（规则路由优先，扩展 research/listing）→ 落输出格式化/校验 → 返回 `{reply, intent, data, route}`
- 完成 P7 后 server.ask 走 orchestrator（supervisor 仍可直接用）

**新建 core/output/（formatter.py + validator.py + \_\_init\_\_.py）**
- `validator.py`：`sanitize_reply(text)`——去除 `{"tool": ...}` 内部 JSON 暴露、拦截 `[工具名称]` 泄露（正则替换）
- `formatter.py`：`wrap(reply, intent, data, route)` → 标准 `{reply, intent, data}` 并附 `route`；卡片数据透传

**新建 tools/research.py、tools/supplier.py、tools/listing.py**（全部用 P0 注册表 + LLM 工具描述范式：何时使用 / 调用格式 JSON / 参数说明）
- research.py（局部注册表 `tools.research`）：
  - `check_demand(keywords)`：演示库含 5 类目搜索量/BSR/售价/重量 → 判定 ≥3000 且 $20-$70 且 <2lb
  - `check_competition(keyword)`：首页前 10 平均评分/评论数 → 判定 ≤4.3 且 ≤500
  - `calc_profit(product_code, sell_price)`：采购+头程+FBA+佣金+广告+退货+仓储 演示费率 → 净利率 ≥30% 判定
  - `run_product_research(keywords)`：四步合一编排（输出四步结论 + 总分）
- supplier.py（局部注册表 `tools.supplier`）：
  - `search_supplier(product_keyword)`：演示 3 家（深圳/东莞/义乌）+ 1688 真实接口槽位 `SUPPLIER_SOURCE`
  - `compare_supplier(product_keyword)`：MOQ/单价/交期对比表（首批 50-100 件口径）
- listing.py（局部注册表 `tools.listing`）：
  - `draft_listing(product_name, keywords)`：标题（75 字符新规：品牌+核心词+属性+场景）+ 五点（问答式）+ Search Terms
  - `check_images(image_urls)`：白底 RGB255/85% 占比/无文字水印 合规自检
  - `price_strategy(product_code)`：竞品价 + 利润率 ≥30% 反推最低售价
  - `recommend_fulfillment(product_code, stock)`：FBA/FBM 建议（首批 ≤100 件试水口径）

**新建 agents/research_agent.py、agents/listing_agent.py**
- 各自 SYSTEM_PROMPT（卖家工作台视角，中日双语约定沿用）+ `tools = [本域工具]` + 模块级兜底 `classic_research_reply` / `classic_listing_reply`（无 Key 时演示完整链路）

**改造 agents/supervisor.py**
- specialists 增 `research`、`listing`；路由新增 `_RESEARCH_PATTERN`（选品|热销|爆款|搜索量|利润|竞争|供应商|1688|阿里|采购|起订量…）与 `_LISTING_PATTERN`（listing|上架|标题|五点|描述|图片|主图|定价|售价|FBA|FBM|关键词布局…），优先级：listing > research > 旧客服/售前兜底
- `answer()` 中路由后调 `record_turn`

**改造 server.py**：`POST /api/conversation/start`（返回新 session_id）、`POST /api/conversation/end`；ask 走 orchestrator；/api/status 返回 route 信息。

**改造 ui/**：index.html 双工作台标签（选品工作台 / Listing 工作台）+ 每个工作台独立聊天流 + 「结束本次谈话」按钮；app.js 加标签切换、谈话结束 API、结果卡片渲染（选品结论卡 / 供应商对比表 / listing 草稿卡）；style.css 增工作台样式（沿用现有设计语言）。保留中/日一键切换。

**验收**：全流程演示——"帮我选个充电宝"走 research；"给云感耳机写 listing"走 listing；无 Key 时兜底同样可演示；谈话结束触发一级总结。

### P8 收尾

- 扩展 memory/demo.py：新增断言覆盖 access 越权、谈话窗口裁剪、知识库两阶段、状态注入、技能反馈
- README.md 更新：架构分层、新 API、记忆参数槽位说明
- 全量 `py_compile` + demo 跑通
- 密钥检查（.env 类文件不入库）→ commit → push main + dev/XuanFeiXiong

## 5. 假设与决策（Assumptions & Decisions）

1. **实施范围**：P0–P8 全部执行，按序推进；每阶段完成后做阶段性验证，不停顿。
2. **旧智能体**：customer_service / presales 及 order/after_sales/recommend 工具全部保留且行为不变；转型完成后再讨论删除。
3. **K=5、M=5**：取文档默认值（config 可调）。
4. **总结/索引生成 LLM**：沿用 glm-5.3-flash（`SUMMARIZER_MODEL` 槽位）；无 Key 一律走规则降级，保证演示链可跑。
5. **知识库 v0.1 不做 ANN 预筛**：索引列表 + 关键词过滤；ANN 接入点留 TODO。
6. **技能检索 v0.1 用关键词 + 评分**：不上向量检索，留 TODO。
7. **ReAct 引擎移动**：`_build_react_agent` 等通用部分移入 `core/cognition/react.py`，`agents/base.py` 重导出，兼容旧智能体。
8. **单用户演示**：user_id 默认 "default"；多用户分区结构已就绪（各表带 user_id）。
9. **审计存储**：access.sqlite 与各模块 sqlite 分库，均在 `memory/**/data/`（gitignore 覆盖）。
10. **谈话 = 一次 session_id 生命周期**：`/api/conversation/start` 换新谈话，`/api/conversation/end` 触发总结管线。

## 6. 验证步骤（Verification）

- 每阶段结束：`python3 -m py_compile <改动文件>` + 阶段验收项（见各阶段"验收"）
- P8 全量：`python3 -m memory.demo`（扩展断言全过）；`python3 server.py` 冒烟（curl /api/ask 与 /api/conversation/end）；浏览器打开双工作台验证
- 推送前：`git status --porcelain | grep -iE "\.env$|secret|token|credential" | grep -v .env.example` 必须为空

## 7. 风险与回退

- **风险**：改造 short_term/memory.py 影响现有客服链路 → 缓解：旧压缩链路不动，新增方法增量式；每阶段验证旧 /api/ask 不回归。
- **风险**：langgraph 版本差异 → `_build_react_agent` 已做多版本兼容，提炼时原样搬运。
- **回退**：每阶段独立提交（commit message 标注阶段号），任一阶段失败可单独 revert。