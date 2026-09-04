# Agno 架构深度分析

> 研究对象：GitHub 官方仓库 `agno-agi/agno`（main 分支），clone 于 2026-09-04，HEAD = `d1a388446`（"chore: Release v3.0.6 (#9907)"）。
> 本文所有代码证据均来自该 clone：`/tmp/harness-research/agno/libs/agno/agno/…`（下文行号引用即该目录内文件）。

## 概览

**定位**：Agno（2025 年初由 Phidata 更名而来）自我定位不是"又一个 Agent 编排库"，而是 **"framework and runtime for agent platforms"**（README 开篇："Build, run, and manage agent platforms"）。即它同时提供三层能力：① Agno SDK——用 Python 写 Agent/Team/Workflow，接 tools、memory、knowledge、storage、多厂商模型；② AgentOS Runtime——把 agent 变成可服务的 FastAPI 式运行时（会话、SSE/WebSocket、RBAC、MCP、调度、tracing，主要落在本仓 `agno/os` 子模块与兄弟包 `agno_infra`/`agnoctl`）；③ AgentOS UI 控制平面（chat、session、trace 可视化，独立于本仓，官方另有 `agno-agi/agentos-*` 部署模板仓库）。

**仓库/工程元数据**：
- Stars/Forks：约 **4.2 万**（2026-08-31 GitHub 组织页显示 41,976 stars / 5,849 forks，持续增长，标注"约"）。
- 语言：Python（requires-python `>=3.9,<4`，见 `libs/agno/pyproject.toml`）。
- pip 包：**agno**（`[project] name = "agno"`，version **3.0.6**，description："The programming language for agentic software."）。
- License：Apache-2.0（`LICENSE` + pyproject classifier）。
- monorepo `libs/` 下共三个包：`agno`（核心 SDK+AgentOS runtime）、`agno_infra`、`agnoctl`（CLI/控制面工具，`agnoctl>=0.2.0` 为核心依赖）。
- 代码量：`agno/agno` 包约 21MB、500+ py 文件；`tools/` 目录 155 项（工具包与内置工具），`models/` 57 项（约 45 个 provider 包），`db/` 22 项、`vectordb/` 25 项。

**能力图谱**：Agent（含 reasoning、RAG、HITL 暂停、checkpoint 续跑）→ Team（4 种编排模式）→ Workflow（Steps/Parallel/Loop/Condition/Router 流水线）；统一 Model 抽象 + fallback 链 + 约 45 家模型厂商；统一 Message/Function/Tool 层与 MCP；会话级/用户级双轨记忆（session runs+summary / db 型 user memory）+ 向量知识库（约 20 种 vectordb + 25 种关系/文档/键值 db）；事件流 RunEvent 全量可观测；AgentOS 服务化。

**重要版本提示（诚实标注）**：任务描述中的若干名称属 Agno v2 时代 API（`AgentMemory`、`run_once`、`response_model`、`agno.playground.Playground/AgentUI`）。当前 main（v3.0.6）代码中这些符号**已不存在**（全仓搜索无命中），对应物为：`AgentSession`（保存 runs/messages）、`Agent.run()` 单轮语义、`output_schema`（结构化输出）、`agno.os` 运行时与外部 AgentOS UI。v2 中的 `agno.playground` 是否在历史分支仍存在，本深度克隆（depth 1）无法验证，以下一律以 v3.0.6 源码为准。

## 分层与目录（模块职责表）

源码根目录 `libs/agno/agno/`（顶层约 45 个模块）：

| 模块 | 职责 | 关键文件 |
|---|---|---|
| `agent/` | Agent 定义 + 运行调度 | `agent.py`（Agent，74 行）、`_run.py`（run 主流程，347/1283 行）、`_messages.py`、`_response.py`、`_storage.py`、`_cli.py` |
| `agents/` | 与其它 agent 框架互操作的适配基类（langgraph/claude/dspy/antigravity，`base.py`） | `agents/base.py` 等 |
| `run/` | run 级数据模型：RunOutput/RunEvent/RunInput/RunMessages | `run/agent.py`、`run/team.py`、`run/workflow.py`、`run/requirement.py` |
| `session/` | 会话数据模型 AgentSession/TeamSession/WorkflowSession + 摘要 | `session/agent.py`、`session/summary.py` |
| `memory/` | 长期用户记忆管理（db 型）与压缩策略 | `memory/manager.py`（MemoryManager，46 行）、`memory/strategies/summarize.py` |
| `knowledge/` | 知识库：向量库 + 内容解析（reader/chunking/embedding/reranker） | `knowledge/knowledge.py`（Knowledge，46 行）、`protocol.py` |
| `vectordb/` | 约 20 种向量库适配（pgvector/chroma/qdrant/lancedb/…） | `vectordb/base.py` |
| `db/` | 约 20 种数据库适配（sqlite/postgres/mysql/mongo/…）+ 组件版本化 | `db/base.py`（BaseDb 295 行 / AsyncBaseDb 2100 行） |
| `models/` | 统一模型抽象与 45+ 厂商接入、fallback | `models/base.py`（Model，134 行）、`fallback.py`、`message.py` |
| `tools/` | Function/Toolkit/@tool 装饰器 + 100+ 内置工具包 | `tools/function.py`、`toolkit.py`、`decorator.py`、`mcp/` |
| `workflow/` | 显式流水线/DAG 编排（Steps/Parallel/Loop/Condition/Router） | `workflow/workflow.py`（Workflow，580 行） |
| `team/` | 多 agent 编排（leader+members，4 模式） | `team/team.py`（Team，81 行）、`mode.py`、`_task_tools.py` |
| `os/` | AgentOS 运行时：REST schema、路由、MCP、approval、interfaces | `os/app.py`、`os/router.py`、`os/interfaces/`、`os/schema.py` |
| `approval/` `hooks/` `guardrails/` | HITL 审批、pre/post hooks、护栏 | `approval/decorator.py`、`guardrails/` |
| `media/` | 图像/音频/视频/文件输入输出与存储 | `media/`（storage 子包） |
| `reasoning/` `learn/` `eval/` `tracing/` `scorer/` `scheduler/` | 推理、学习机、评估、tracing、评分、定时任务 | 各自目录 |
| `run/` `context/` `filters/` `compression/` `offload/` | 运行上下文、过滤器、上下文压缩、结果卸载 | 各自目录 |
| `cli/` 不存在；CLI 由 `agnoctl` 与 `agent/_cli.py`（print_response 富文本终端）承担 | | |
| `playground/` 不存在 | v3 由 `agno.os` + AgentOS UI（外部仓库）取代 | | |

## Agent 主循环

`Agent` 是 `@dataclass(init=False)` 大字段类（`agent/agent.py:74`），手动 `__init__`（386 行起）。核心字段即架构切片：`model`/`fallback_models`/`fallback_config`、`tools`（可 `Toolkit|Callable|Function|Dict` 或工厂函数）、`knowledge`、`db`、`memory_manager`、`update_memory_on_run`、`session_id`、`output_schema`、`retries`、`tool_call_limit`、`reasoning_model`、`pre_hooks/post_hooks`、`checkpoint` 等。`AgentSession` 也在 `agno.agent` 顶层 re-export。

**入口**：
- `agent.run(...)`（`agent/agent.py:1455`，带 `@overload`）→ 直接委托 `_run.run_dispatch(self, …)`（`agent/_run.py:1283`）；异步 `arun` → `arun_dispatch`（2801）。无 `run_once`——单次 run 即"一次 run"；多轮 tool 循环在模型层（见下）。
- `agent.print_response(...)`（`agent.py:1219`）→ `_cli.agent_print_response`（rich console 渲染，纯展示壳）。
- 事件流模式：`run(stream=True, yield_run_output=True)` 返回 `Iterator[RunOutputEvent]`；事件枚举 `RunEvent` 在 `run/agent.py:144`（`RunStartedEvent`、`RunContentEvent`、`ToolCallStartedEvent/ToolCallCompletedEvent`、`Reasoning*`、`RunPausedEvent` 等）。

**`_run`（`agent/_run.py:347`）docstring 白纸黑字列出主流程 16 步**（节选）：
> 1. Read or create session … 4. Execute pre-hooks 5. Determine tools for model 6. Prepare run messages 7. Start memory creation in background thread 8. Reason about the task 9. Generate a response from the Model (includes running function calls) … 12. Convert the response to the structured format if needed 13. Execute post-hooks 15. Create session summary 16. Cleanup and store the run response and session。

要点：
- **run 级重试**：`num_attempts = agent.retries + 1`（406 行起 `for attempt in range(num_attempts)`），每次尝试内重新走完整流程（读会话→pre-hooks→工具→消息→模型→后处理）。
- **模型调用**：`call_model_with_fallback(...)`（`models/fallback.py:158`）——先调 `model.response(**kwargs)`，抛 `ModelProviderError` 时按 `fallback_config` 取 fallback 模型逐个试（`_try_fallback_models`，283 行；成功者会把其追加的消息同步回原 messages 以便持久化）。
- **结构化输出**：`response_format` 由 `_response.get_response_format`（`agent/_response.py:856`）根据模型能力生成——`supports_native_structured_outputs`（如 OpenAI）走原生 `structured_outputs`；否则 `use_json_mode` / json_schema。响应解析：`update_run_response`（945）里若 `model_response.parsed` 非空直接采用原生结构化输出；否则 `convert_response_to_structured_format`（903）用 `parse_response_model_str(content, output_schema)` 把字符串解析成 BaseModel 实例并写入 `run_response.content/content_type`。另有 `parser_model`（次模型重解析）与 `output_model`（独立模型直接生成结构化输出）。
- **多轮 tool 循环不在 Agent 层，而在 `Model.response()`（`models/base.py:646`）**——这是 v3 的关键设计：循环对全部厂商复用一次实现：
```python
while True:
    ...
    self._process_model_response(messages=..., assistant_message=assistant_message, ...)  # 单次 API 调用
    messages.append(assistant_message)
    if assistant_message.tool_calls:
        function_calls_to_run = self._prepare_function_calls(...)
        for function_call_response in self.run_function_calls(...):   # 执行工具
            ...收集 updated_session_state / images / tool_executions ...
        self.format_function_call_results(messages=messages, function_call_results=...)
        if any(m.stop_after_tool_call for m in function_call_results): break
        if after_tool_results is not None: after_tool_results(model_response)   # checkpoint="tool-batch" 钩子
        if any(tc.requires_confirmation / external_execution_required / requires_user_input ...): break  # HITL
        continue            # 有工具调用 → 带 tool 结果再请求模型
    break                    # 无工具调用 → 结束
```
（`models/base.py:700-869`，多轮以 `function_call_count` 计数并在超过 `tool_call_limit` 时停止——`_limit_charge_for` 累加。`assistant_message.tool_calls` 由各 provider 的 `_parse_provider_response` 填充。）
- **模型级 retry/backoff**：`_invoke_with_retry`（`models/base.py:227`）按 `model.retries` 重试，`_is_retryable_error`（199）只重试 429/5xx 类，400/401/403/404/413/422 与 context-window 错误直接失败；另有 `RetryableModelProviderError` → "retry_with_guidance"（往 messages 追加 `temporary=True` 的引导消息再请求一次，264-270 行）。注意 `Message.temporary=True` 消息在收尾由 `_remove_temporary_messages` 剔除（435 行）——重试痕迹不进会话历史。
- 运行上下文模型 `RunContext`（`run/` 下）携带 `session_id/user_id/dependencies/metadata/session_state/output_schema`，贯穿 pre/post hooks 与工具签名注入。

## 记忆体系

记忆被拆成三层，全部围绕"run/session 落库"展开：

1. **短期记忆 = 会话内消息历史**。每次 run 产出一个 `RunOutput`（`run/agent.py:618`：`run_id/session_id/messages: List[Message]/tools: List[ToolExecution]/status`，支持 `paused/cancelled` 状态与 `requirements`）；这些 RunOutput 追加进 `AgentSession.runs`（`session/agent.py:99 upsert_run`）。历史如何回填上下文由 Agent 字段控制：`add_history_to_context`/`num_history_runs`/`num_history_messages`/`store_history_messages`（默认 False，即每 run 只存自身消息，历史在读取时沿前序 run 重建，避免二次方存储膨胀——注释见 `agent.py:228-233`）。
2. **长期用户记忆（db 型，提取式）**：`MemoryManager`（`memory/manager.py:46`）持有一个管理模型（默认 OpenAIChat gpt-4o，112-123 行）和 `db`（`UserMemory` 表，`db/base.py:691 get_user_memories`）。它把自己的 add/update/delete/clear 建模为**工具**交给管理模型决策（`manager.py:62-73` 各开关），即"用一次模型调用从对话中抽取事实写入 `user_id` 维度的记忆表"。触发时机：run 组装消息后即后台启动 `start_memory_future`（`agent/_managers.py:180`，满足 `memory_manager 配置 && update_memory_on_run && !enable_agentic_memory`）→ `make_memories`（29 行）调用 `memory_manager.create_user_memories(...)`，主循环无需等待；可选 `enable_agentic_memory=True` 时改为给 Agent 注册 `update_user_memory` 工具、由 agent 在对话中自主记忆（`agent.py:124-132`）。回填：`add_memories_to_context` 时 `get_user_memories`（`_managers.py:218`）注入 system prompt。
3. **会话摘要与跨会话检索**：`enable_session_summaries` + `SessionSummaryManager`（`session/summary.py:63`，`summary_request_message`、`SessionSummaryResponse`），在 run 收尾生成 `SessionSummary`（summary/topics）随 `AgentSession.summary` 持久化；`search_past_sessions=True` 时给 agent 加"搜历史会话"工具；摘要可注入上下文（`add_session_summary_to_context`）。
4. **向量型记忆/知识 = `Knowledge`**（严格说 v3 把"向量记忆"归入知识库而非 memory）：`Knowledge`（`knowledge/knowledge.py:46`，继承 `RemoteKnowledge`）字段 `vector_db + contents_db + readers + max_results`；`insert(path/url/text_content/topics/remote_content…)` → 读取文档 → chunking（`knowledge/chunking/`）→ embedder → upsert 向量库；检索入口 `get_relevant_docs_from_knowledge`（`agent/_messages.py:1708`）。两种接线方式：① 静态 RAG——`add_knowledge_to_context=True` 时在 `get_run_messages` 阶段把 top-k 文档作为 references 注入 user prompt；② Agentic RAG——`search_knowledge=True`（默认）注册 `search_knowledge_base`/`search_knowledge_base_with_filters` 工具（`agent/_default_tools.py:130/198`），由模型自主决定何时检索、传什么 query/filter（`enable_agentic_knowledge_filters`/`knowledge_filters`）。`Knowledge` 支持 `user_id` 级内容隔离与 `isolate_vector_search`。
5. **学习机（v3 新增，可视为"记忆+知识"的统一演进）**：`learn/` 提供 `LearningMachine` 与多个 store（user_memory/entity_memory/user_profile/learned_knowledge/session_context），`agent.learning=True` 时 run 期间后台抽取、跨 agent 复用。

## Storage（数据库持久化与会话生命周期）

v3 不再有独立的"AgentStorage"类——`db` 就是持久化总入口（`agent.py:136`：`db: Optional[Union[BaseDb, AsyncBaseDb]]`）。`db/base.py` 的 `BaseDb`/`AsyncBaseDb` 提供约 20 种后端（sqlite、postgres、mysql、mongo、redis、valkey、clickhouse、dynamo、firestore、singlestore、surrealdb、json、gcs_json、in_memory…），语义上管理三类对象：组件（agent/team/workflow 配置本身，带版本化 publish/draft，见 `db/base.py:29 ComponentType` 与 registry）、会话（`SessionType`：agent/team/workflow，23 行）、run/记忆（UserMemory）。会话读写集中在 `agent/_storage.py`：`read_session`（355）/`upsert_session`（403）/`upsert_run`（457）/`read_or_create_session`（635，按 `session_id+user_id` 读库，无则新建并落库）/`load_session_state`；run 收尾 `persist_run_in_session`（`agent/_run.py:6044`）。`checkpoint` 字段（`agent.py:144`）控制持久化粒度：默认 `"runs"`（仅终态写库），`"tool-batch"` 则每个模型轮后经 `after_tool_results` 回调写中间检查点（配合 `RunOutput.last_checkpoint_at_message_index` 与 continue/fork 机制实现断点续跑）。Workflow/Team 各自拥有对应的 Session 模型与同一套 db 接口（`session/workflow.py`、`session/team.py`）。

## 多 Agent：Team 与 Workflow 两种范式

**Team（运行时动态编排）**：`Team`（`team/team.py:81`）本质是"leader agent + members"：`members: List[Agent|Team]`（86 行）+ team 自身 `model`（88 行，即 leader 大脑）+ `tools`。编排模式 `TeamMode`（`team/mode.py:6`）：`coordinate`（默认 supervisor：leader 挑选成员、撰写任务、汇总）/ `route`（路由到单一专家直接返回成员答复）/ `broadcast`（同一任务派发给全部成员，arun 并发）/ `tasks`（leader 把目标拆成共享任务列表并循环直到完成，`max_iterations`）。通信方式是把"派活"建模成 **leader 的工具调用**：`_default_tools.py` 中 `delegate_task_to_member(member_id, task)`（690 行）/`delegate_task_to_members(task)`（1051 行）内部执行被选 agent 的 `run()`，把成员 `RunOutput` 转成事件/文本喂回 leader；`get_member_information`（team.py:1572）让 leader 先侦察成员能力再决定派给谁；tasks 模式另配 `_task_tools.py`（`list_tasks`/`add_task_note`，272/283 行）。因此每个成员可以是完整独立 Agent（自带 model/tools/knowledge/db/记忆），Team 无自己的子 agent 运行循环——成员互不可见、仅通过 leader 中转（除非 `share_member_interactions`/`add_team_history_to_members`）。Team 也有自己的 session/run 持久化与事件流（`run/team.py:TeamRunOutput/TeamRunEvent`）。lead-agent 即"Team 自身的 model+instructions"。

**Workflow（静态显式流水线）**：`Workflow`（`workflow/workflow.py:580`）构造参数 `steps` + 可选 `agent`（`WorkflowAgent`，597 行——由 agent 决定"何时跑哪个 workflow"，即 agentic workflow）。`steps` 用"执行器 + 控制结构"声明式组合：`Steps`（顺序流水线，`steps.py:40`）、`Parallel`（`parallel.py:47`）、`Loop`（`loop.py:43`）、`Condition`（`condition.py:55`）、`Router`（`router.py:50`），叶子执行器是 Agent/Team/函数（`types.py:StepType/ExecutorType`，736/747 行），步骤间显式传参（`StepInput/StepOutput`），支持 HITL `HumanReview` 暂停审批（`types.py:65`）。`Workflow.run(input, session_id, stream…)`（10478 行）返回 `WorkflowRunOutput`；`as_tool()`（737 行）把整个 workflow 发布成一个工具（可供其它 agent 或 MCP 调用）。与 Team 相比：Team 的"图"是模型在运行时动态决定的，Workflow 的图是代码显式定义、可静态分析/恢复/发布为工具的。

## 模型接入

统一基类 `Model`（`models/base.py:134`，ABC）：声明 `id/name/provider/model_type`（`model_type` 区分 MODEL/OUTPUT_MODEL/PARSER_MODEL 角色，143 行）、能力位 `supports_native_structured_outputs/supports_json_schema_outputs`、重试参数，并**把多轮工具循环、结构化输出请求、temporary 消息管理都实现在基类**，子类只需实现 6 个原语：`invoke/ainvoke/invoke_stream/ainvoke_stream/_parse_provider_response/_parse_provider_response_delta`（547-587 行）。约 45 个 provider 包各自实现原语：如 `models/openai/chat.py`（OpenAIChat，`invoke` 392 行调 chat.completions 并做错误分类：RateLimit/APIStatus/context_length_exceeded → `ContextWindowExceededError`）、`models/openai/responses.py`（Responses API）、`anthropic/claude.py`、`google/gemini.py`、`models/litellm/chat.py`（借 LiteLLM 一包覆盖数百模型）等。统一消息类型 `Message`（`models/message.py:56`）、`ModelResponse` 与 `ToolExecution`（`models/response.py`）。多厂商切换即一行：`Agent(model=OpenAIChat(...))` / `model=Claude(...)` / 字符串经 `models/utils.get_model` 工厂解析；跨厂商容错 = `fallback_models`/`fallback_config`（`FallbackConfig` 支持按错误码路由，`models/fallback.py`）+ 基类重试，两级叠加。agno 侧对 model 只依赖 `response/aresponse` 这一契约，`Agent` 与厂商 SDK 完全解耦。

## 会话与 API

- **session_id 语义**：Agent 构造可传 `session_id`（否则 `id`/`session_id` 自动生成），`run(..., session_id=...)` 可覆盖；同一 `(agent_id, session_id, user_id)` 会 `read_or_create_session` 续接历史，实现多轮会话与横向扩容（agent 无状态，状态全在 db）。
- **AgentSession**（`session/agent.py:16`）：session_id + agent/team/workflow/user 外键 + `session_data`（session_state）+ `runs: List[RunOutput]` + `summary`，`to_dict/from_dict` 手工做深拷贝裁剪以控制序列化成本（48-61 行注释）。
- **run/事件 API**：`RunOutput` 是"一次 run 的完整档案"（内容、reasoning、messages、tools、media、metrics、requirements、fork/regenerate 血缘字段），支持流式事件（`yield_run_output`）。HITL 一等公民：`RunRequirement`（`run/requirement.py:14`）+ `agno/approval`（`@approval` 装饰器，`Function.approval_type`）使工具可暂停等待人批/外部执行/用户补参，暂停态 run 可续跑（`continue_run_dispatch`，`agent/_run.py:3352`）。
- **playground/AgentUI**：v3 `agno` 包内**无** playground 模块。其职能由 `agno.os`（本仓内 AgentOS runtime：`os/schema.py` REST schema、路由、`os/interfaces/`（slack 等消息入口）、client/`（`client/os.py`、A2A）承担；图形化控制平面 AgentOS UI 为仓库外独立产品（`os.agno.com`，agno-agi 组织下的部署模板仓库），本文仅凭 README 描述转述，未作代码验证（不确定项）。
- **CLI**：无 `agno/playground`；终端交互由 `agent/_cli.py`（`print_response`/`cli_app` 富文本 REPL）与独立包 `agnoctl`（控制面 CLI）承担。

## 与其它 harness 对比与启发

- **vs LangChain/LangGraph**：Agno 不做通用链/图的粗粒度抽象，agent 就是"model+tools+记忆+db"的 dataclass，代码可读性强、实例化开销极小（官方宣传微秒级）；但 v3 又通过 `agno.agents.langgraph / claude / dspy` 适配基类承认生态互操作，而非逼用户换框架。
- **vs OpenAI Agents SDK / Pydantic AI**：结构化输出同为 Pydantic 原生；Agno 差异化在"生产运行时打包"——数据库原生持久化会话/run/记忆、HITL 审批、RBAC、MCP server、调度、tracing 直接进 SDK 而非外挂，以及 45 家厂商统一轮循环。
- **vs CrewAI**：Crew 用角色剧本约束协作；Agno Team 更像"leader 动态编排 + 工具化委派"，且保留 Workflow 显式管线两条路。
- **启发**：① 把多轮 tool 循环下沉到统一 Model 基类（一次实现、全部厂商复用、重试/容错集中管理）——harness 应让"模型调用循环"成为唯一事实源；② run/session 双 ID + 全量事件流（RunEvent）+ checkpoint 续跑/fork，是"可观测、可恢复"的关键建模；③ "记忆分轨"：会话 runs（短期，线性存储）与用户记忆表（长期，抽取式）分离，向量知识库独立成 RAG 通道；④ 把"人审"（requires_confirmation/approval/requirements）做成工具与 run 状态的一等字段，agent 暂停/恢复是状态机而非异常；⑤ Agent、Team、Workflow 都可被发布成工具/MCP 组件——组合即复用。

---

*研究路径：本仓库深克隆 `/tmp/harness-research/agno`；另以 workspace 副本 `.agno-src/` 完成全文搜索（Grep 工具无法访问 /tmp）。所有行号基于 HEAD `d1a388446`（v3.0.6）。*
