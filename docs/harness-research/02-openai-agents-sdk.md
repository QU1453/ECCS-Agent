# OpenAI Agents SDK 架构深度分析

> 研究对象：`openai/openai-agents-python` main 分支（本地克隆：`/tmp/harness-research/openai-agents`）
> 基线提交：`89c02c828ee8510fe9a84ee6675608193aa13b02`（2026-08-28）；包版本 `0.22.0`（`pyproject.toml`）。
> 以下所有代码结论均来自上述提交的真实源码，文内给出相对仓库根目录的路径与行号证据；不确定处均显式标注。

## 一、概览

**定位**：OpenAI Agents SDK 是一个**轻量、通用的 Agent 编排 harness（orchestration harness）**，而不是 RAG 框架，也不是向量检索/知识库系统。README 第一句即自述为 "a lightweight yet powerful framework for building multi-agent workflows"，且 **provider-agnostic**——支持 OpenAI Responses API、Chat Completions API，以及 100+ 第三方 LLM（经自定义 `ModelProvider`/LiteLLM 扩展）。GitHub 仓库自身 topics 含 `harness`、`agents`、`framework`（GitHub API `topics` 字段）。它解决的问题是：**如何把"模型调用 + 工具 + 多代理交接 + 护栏 + 会话记忆 + 可观测性"组装成一个可运行的 agent 循环**。

**数据面**（GitHub API，2026-09-04 抓取，爬虫经沙箱代理）：Stars ≈ 29.2k、Forks ≈ 4.7k、语言 Python（版本要求 `>=3.10`）、License MIT、创建于 2025-03-11、默认分支 main。作者/维护方为 OpenAI 官方。

**传承关系（需谨慎处）**：本仓库 README 与 docs 中**并未直接提及 Swarm**（全文检索无命中），因此"Swarm 是其前身"的说法主要来自 OpenAI 2025 年公开发布信息（Swarm 实验项目 → 生产化 SDK 的脉络），本文不把该论断建立在仓库内证据上。与 **Assistants API** 的传承则明确体现在类型与实现上：SDK 内部以 OpenAI **Responses API** 的 item 类型为"通用消息模型"（见下文 `items.py`），并通过 `OpenAIChatCompletionsModel`（`src/agents/models/openai_chatcompletions.py`）把 Chat Completions 适配进同一 `Model` 接口；也就是说"Assistants 底层的 Chat Completions 协议"是其一等公民后端，而非核心数据模型。

**演进到 0.22 后的产品面**（README 核心概念列表，2026 年 main 已远超早期文本 agent）：文本 Agent（本分析重点）、`SandboxAgent`（容器化沙箱执行）、`RealtimeAgent`/Voice（WebSocket 语音）、`Agents as tools`/Handoffs、Tools（函数/MCP/托管工具）、Guardrails、Human-in-the-loop（审批中断）、Sessions（会话记忆）、Tracing。

## 二、核心抽象与分层

公共 API 集中在 `src/agents/__init__.py`（600+ 行的 `__all__`），分层可粗分为三层：

1. **公开声明层**：`Agent`、`Runner`、`RunConfig`、`Tool`/`FunctionTool`、`Handoff`、`InputGuardrail`/`OutputGuardrail`、`Session`、`RunContextWrapper`、`AgentOutputSchema`、`RunResult`。
2. **执行引擎层（内部）**：`src/agents/run_internal/` 子包——run_loop、turn_preparation、turn_resolution、tool_execution、guardrails、session_persistence、oai_conversation、run_steps 等，这些是 **internal，非公共 API**（`run_steps.py:2-4` "These types are not part of the public SDK surface"）。
3. **模型与可观测性抽象层**：`models/interface.py`（`Model`/`ModelProvider`）、`tracing/`。

核心对象与源码位置：

| 抽象 | 文件 | 说明 |
|---|---|---|
| `Agent`/`AgentBase` | `src/agents/agent.py`（dataclass） | LLM + instructions + tools + handoffs + guardrails 的声明式配置 |
| `Runner`/`AgentRunner` | `src/agents/run.py` | 入口 `run/run_sync/run_streamed`，主循环编排 |
| `RunConfig` | `src/agents/run_config.py` | 整次运行的全局设置（model 覆盖、tracing、session 回调等） |
| `RunResult`/`RunResultStreaming` | `src/agents/result.py` | 运行产物：new_items、raw_responses、final_output、守卫结果、to_state() |
| `Model`/`ModelProvider` | `src/agents/models/interface.py` | 模型中立接口：`get_response`/`stream_response`/`get_model` |
| `FunctionTool`/`function_tool` | `src/agents/tool.py`、`function_schema.py` | 由 Python 函数+类型注解自动生成 JSON Schema 的工具 |
| `Handoff`/`handoff()` | `src/agents/handoffs/__init__.py` | 代理交接（实现为特殊 function tool） |
| `InputGuardrail`/`OutputGuardrail` | `src/agents/guardrail.py` | 输入/输出护栏，tripwire 中断 |
| `Session`/`SessionSettings` | `src/agents/memory/session.py`、`session_settings.py` | 会话历史存储协议 |
| `RunContextWrapper` | `src/agents/run_context.py` | 包装用户 context + usage + turn_input + 审批状态 |
| `AgentOutputSchema` | `src/agents/agent_output.py` | 结构化输出类型 → strict JSON Schema + 解析/校验 |
| `items.py` 系列 | `src/agents/items.py` | `TResponseInputItem`/`RunItem`/`ModelResponse` 等消息模型 |
| tracing | `src/agents/tracing/` | Trace/Span/Processor/Provider |

值得强调的建模选择：

- **Agent 是声明式 dataclass，不是运行时对象**。`agent.py` 里 `Agent`（`agent.py:295`）通过 `@dataclass` 定义字段：`instructions`（字符串或 `(ctx, agent)->str` 动态函数，`agent.py:309-323`）、`handoffs`、`model`、`model_settings`、`input_guardrails`/`output_guardrails`、`output_type`、`hooks`、`tool_use_behavior`、`reset_tool_choice`。克隆用 `clone(**kwargs)`（`dataclasses.replace` 浅拷贝，`agent.py:548-581`）。
- **`RunContextWrapper[TContext]` 包裹用户 context**：`context` 不发给 LLM，只用于工具函数/回调/钩子的依赖注入；wrapper 还带 `usage`（累计 token）、`turn_input`，并持有审批记录（`run_context.py:72-106`）。`ToolContext` 是其子类（`tool_context.py:42`），追加 `tool_call_id`/`tool_name`/`tool_arguments`。
- **结构化输出用 `AgentOutputSchema`**：`output_type` 是 Pydantic 模型/dataclass/TypedDict 等，包一层 pydantic `TypeAdapter`；默认 `strict_json_schema=True`，用 `ensure_strict_json_schema` 强制转成 OpenAI Structured Outputs 严格模式（`agent_output.py:60-127`）；文本输出（`str`/None）则 `is_plain_text()` 直出。
- **工具可"动态启停"**：`FunctionTool.is_enabled` 与 `Handoff.is_enabled` 都允许 bool 或 `(ctx, agent) -> bool` 回调，运行时 `AgentBase.get_all_tools()` 逐个求值后把禁用工具藏起来（`agent.py:272-292`）。

## 三、Agent 主循环（run 的完整流程）

### 3.1 入口与"turn"定义

`Runner` 是纯 classmethod 门面，`run()`/`run_sync()`/`run_streamed()` 全部委托给模块级单例 `DEFAULT_AGENT_RUNNER`（`run.py:165,325`，即文件末尾实例化的 `AgentRunner`，标注 experimental/不公开）。`Runner.run` 的 docstring 完整给出循环语义（`run.py:275-281`）：

```
1. The agent is invoked with the given input.
2. If there is a final output (i.e. the agent produces something of type
   `agent.output_type`), the loop terminates.
3. If there's a handoff, we run the loop again, with the new agent.
4. Else, we run tool calls (if any), and re-run the loop.
```

关键计量：**"turn = 一次逻辑模型调用 + 对该响应的处理"**；工具执行、handoff 解析、会话持久化、中断恢复、请求级重试都**不单独消耗 turn**（仓库内部规范 `.agents/references/runner-lifecycle.md` "Turn Boundary"）。默认 `DEFAULT_MAX_TURNS = 10`（`run_config.py:45`），`Runner.run(..., max_turns=None)` 可禁用上限；超限抛 `MaxTurnsExceeded`（`exceptions.py:444`），但新版支持 `error_handlers` 按错误类型接管，把 handler 的最终输出作为结果返回（`run.py:1499-1580`，`finalize_max_turns_handler_output`）。

主循环骨架（run.py，摘要）：

```python
# run.py:967  while True:
#   current_turn += 1
#   if max_turns is not None and current_turn > max_turns:   # run.py:1482-1491
#       ... raise MaxTurnsExceeded(f"Max turns ({max_turns}) exceeded")
#   turn_result = await run_single_turn(...)                  # -> SingleStepResult
#   match turn_result.next_step:                              # run_steps.py
#     NextStepFinalOutput -> run output guardrails; 构造 RunResult 返回
#     NextStepHandoff     -> current_agent = new_agent; continue   # run.py:2105-2115
#     NextStepInterruption-> 持久化到 RunState, 返回待审批中断
#     NextStepRunAgain    -> save turn items; continue
```

### 3.2 单轮内部流程（run_internal）

`run_single_turn`（`src/agents/run_internal/run_loop.py:2402`）是"一轮"的实现，顺序大致为：

1. **Agent start hooks**（仅当前 agent 首次进入时）：`hooks.on_agent_start` 与 `agent.hooks.on_start` 并行 gather（run_loop.py:2433-2447）。
2. **组装系统提示**：`execution_agent.get_system_prompt(ctx)`（字符串或动态函数，`agent.py:1042`）+ 可选的 Responses `prompt` 配置。
3. **取 handoffs 与 tools**：`get_handoffs(...)`；`resolve_tool_name_collisions(...)` 处理 function tool 与 handoff 工具名冲突（策略 `warn`/`error`，`run_config.py:480`）；写入 agent span 元数据。
4. **准备模型输入**：无 server conversation 时由 `_prepare_turn_input_items(original_input, generated_items, ...)` 用"历史 items + 本轮回放 items"构造；有 server conversation 时经 `OpenAIServerConversationTracker.prepare_input` 只发增量。
5. **调用模型**：`get_new_response`（run_loop.py:2533）→ `model.get_response(system_instructions, input, model_settings, tools, output_schema, handoffs, ...)`（`models/interface.py:67-100`）；外层包 `get_response_with_retry`，支持 `model_settings.retry`、`model_settings.timeout`（`ModelTimeoutError`）以及基于 `model.get_retry_advice` 的 provider 重试建议；LLM start/end hooks 在此触发；随后由 `get_single_step_result_from_response` 做响应处理与工具执行，产出一个 `SingleStepResult`（含 `next_step`）。

`SingleStepResult.next_step` 四态状态机（`run_steps.py:155-223`）是这套实现最清晰的抽象之一：`NextStepRunAgain`（当前 agent 再调一轮模型）/ `NextStepHandoff`（切换 agent 后继续）/ `NextStepFinalOutput`（有最终候选输出）/ `NextStepInterruption`（审批中断、持久化后可恢复）。

### 3.3 工具执行与"自动函数调用"

模型返回的 output item 在响应处理阶段被分类（`run_steps.py:62-148` 的 `ProcessedResponse`：`ToolRunHandoff`/`ToolRunFunction`/`ToolRunComputerAction`/`ToolRunCustom`/`ToolRunShellCall`…）。本地 function tool 执行在 `run_internal/tool_execution.py`（2775 行），要点：

- 每个 FunctionTool 的 `on_invoke_tool(ctx: ToolContext, input_json: str)`（`tool.py:455`）——LLM 传 JSON 字符串，SDK 用生成的 pydantic 参数模型校验后再 `schema.to_call_args(parsed)` 拆成 args/kwargs 调用原函数（`tool.py:2615-2650`）；**同步函数自动放入 `asyncio.to_thread` 线程池**，避免阻塞事件循环。
- **tool 异常语义**：失败默认交给 `failure_error_function`/`default_tool_error_function`（`tool.py:1863`）生成一条"错误即结果"消息**回传给模型**让它自我纠正，运行不中断；传 `failure_error_function=None` 则直接抛异常终止 run；超时行为 `timeout_behavior` 可选 `error_as_result`（模型可见的超时提示）或 `raise_exception`（抛 `ToolTimeoutError`）。
- **tool_use_behavior**（agent.py:373）：`"run_llm_again"`（默认：工具结果送回 LLM）`/"stop_on_first_tool"`/`StopAtTools`（命中名单工具即终止，其输出作为最终输出）/自定义函数 `ToolsToFinalOutputFunction`。`reset_tool_choice=True` 防止工具后无限循环（agent.py:395）。**注**：早期/别的框架常见的 `suppress_output` 参数在 0.22 main 源码中未检索到任何命中（`suppress_output` 语义目前由 `tool_use_behavior`/`stop_on_first_tool` 承担），若需确认其是否曾在历史版本存在，应查 git 历史——此为显式标注的不确定点。
- 并行工具调用：provider 侧 `parallel_tool_calls`（ModelSettings），SDK 侧 `RunConfig.tool_execution.max_function_tool_concurrency` 可限制本地并发（run_config.py:139）。

### 3.4 首轮输入护栏与末轮输出护栏（主循环中的位置）

- **Input guardrails 只属于起点 agent、只在首轮跑**（Runner.run docstring "Only the first agent's input guardrails are run"，run.py:984-986 代码按 `current_turn == 0` 取值）。分两类：`run_in_parallel=True` 与模型调用**并行**跑（`asyncio.gather(guardrail_task, model_task)`），tripwire 时取消在飞的模型任务；`run_in_parallel=False` 串行先跑，阻断后才动模型（run.py:1644-1742）。
- **Output guardrails 只在"最终输出候选"产生后跑一次**（run.py:1893 等），tripwire 抛 `OutputGuardrailTripwireTriggered`（`exceptions.py:532`）；若被拒的是 terminal tool output，SDK 会把会话里的敏感内容替换成 data-free 占位消息（`blocked_output.py`，可配 `RunConfig.output_guardrail_blocked_message`）再抛出。

### 3.5 流式与结果

`Runner.run_streamed` 返回 `RunResultStreaming`，后台跑同样的循环把语义事件写队列，用户 `async for event in result.stream_events()` 消费 `RunItemStreamEvent`/`AgentUpdatedStreamEvent`/`RawResponsesStreamEvent` 等（`result.py:595+`、`stream_events.py`）。普通 `RunResult` 含 `input/new_items/raw_responses/final_output/input_guardrail_results/output_guardrail_results/context_wrapper/last_agent/interruptions`（result.py:308-338），`final_output_as(cls)` 做类型化访问，`to_input_list()` 把整轮转成下一轮输入，`to_state()` 生成可恢复的 `RunState`（result.py:542）。

## 四、多 Agent 协作：handoffs、路由与子代理

**Handoff（交接）是 SDK 一等公民**，但实现上并无特殊传输——它被建模成一个**特殊的 function tool**：默认工具名 `transfer_to_{agent_name}`（`Handoff.default_tool_name`，`handoffs/__init__.py:207`），描述为 "Handoff to the {agent} agent..."。模型只要"调用"该工具，`on_invoke_handoff` 返回目标 agent，主循环收到 `NextStepHandoff` 后切换 `current_agent` 并继续（run.py:2105-2115）。

`Handoff` dataclass（`handoffs/__init__.py:126-218`）与工厂 `handoff(agent, ...)`（`handoffs/__init__.py:260`）支持：

- `on_handoff` 副作用回调（可带 `input_type` 结构化参数校验）；
- `input_filter: HandoffInputData -> HandoffInputData`：**交接时历史裁剪**。默认下一个 agent 看到全部会话历史（包含触发交接的 call item 与其 output item）；filter 可删旧消息/去重（`HandoffInputData` 的 `input_history`/`pre_handoff_items`/`new_items`/`input_items` 语义见 70-118 行注释）；RunConfig 级 `handoff_input_filter` 作全局兜底。Server-managed conversation（`conversation_id` 等）**不支持** input filter（handoffs/__init__.py:170）。
- `is_enabled` 动态启停（按 context/状态隐藏交接工具）。

**协作编排模式**（examples/agent_patterns/ 与 docs/multi_agent.md）：

- **Triage 路由**：`examples/agent_patterns/routing.py`——一个 triage agent 挂多个 handoff，按意图分流到专用 agent。
- **子代理 = tools**：`Agent.as_tool(...)`（agent.py:583）把 agent 变成 FunctionTool。docstring 精确区分了两者（agent.py:608-612）：handoff 时**新 agent 继承对话历史并接管对话**；as_tool 时**新 agent 只收到生成的输入**，完成后交还原始 agent 继续。示例：`examples/agent_patterns/agents_as_tools.py`、`agents_as_tools_structured.py`。
- **并行/流水线**：SDK 不内置并行编排语法，建议在应用层用 `asyncio.gather` 多个 `Runner.run` 后用 `Runner.run` 汇总（`examples/agent_patterns/parallelization.py`），或用 `deterministic.py` 做固定顺序流水线、`llm_as_a_judge.py` 做裁判聚合——即"并行/流水线交给应用代码"。
- 交接后钩子：`AgentHooks.on_handoff`/`on_agent_start`（每次 agent 变更触发，`lifecycle.py:37-59,138-146`）；追踪上每个 agent 一个 `AgentSpanData` span（run.py:1474-1480）。

## 五、上下文与记忆

### 5.1 context 注入

用户侧：`Runner.run(agent, input, context=my_ctx)`；泛型 `Agent[TContext]` 贯穿 tools/handoffs/guardrails/hooks 的 `RunContextWrapper[TContext].context`。动态系统提示 `instructions=lambda ctx, agent: ...` 可读 context 生成指令（agent.py:1042-1071）。运行中还能用 `RunConfig.call_model_input_filter` 在**每次模型调用前改写** instructions+input（run_config.py:438-446）——官方点名可用于 token 超限裁剪。

### 5.2 会话（session）抽象

`Session` 是**结构型 Protocol**（`memory/session.py:15-56`）：`session_id` + `get_items(limit)/add_items(items)/pop_item()/clear_session()`。语义：run 前 runner 取出历史拼到输入前面，run 后把本轮所有新 item（用户输入、assistant 消息、工具调用对）写回（docs/sessions/index.md "Core session behavior"；实现见 `run_internal/session_persistence.py` 的 `prepare_input_with_session`/`save_result_to_session`）。`SessionSettings.limit` 控制取回条数上限（session_settings.py:38）。

内置实现：`SQLiteSession`（`memory/sqlite_session.py`，惰性导入）；扩展（`src/agents/extensions/memory/`）：Redis、MongoDB、SQLAlchemy、Dapr、加密包装、高级 SQLite（分片/截断）、文件示例 `examples/memory/file_session.py` 等——**外部存储 provider 通过实现同一 Protocol 即插即用**。`RunConfig.session_input_callback` 可自定义"历史 + 新输入"的合并策略。

### 5.3 内置对话记忆的压缩/截断与"服务端记忆"

- **本地会话 + 压缩**：`OpenAIResponsesCompactionSession`（`memory/openai_responses_compaction_session.py:82`）是包装器：默认当 compaction 候选 item ≥10 条（`DEFAULT_COMPACTION_THRESHOLD = 10`，同文件:28、58）时自动调用 **OpenAI `responses.compact`**（仅限 Responses API + OpenAI 模型），用模型把旧历史压成摘要，从而控制 token 增长——这是"内置记忆里做语义压缩"的地方。
- **服务端托管对话（server-managed conversation）**：传 `conversation_id`/`previous_response_id`/`auto_previous_response_id` 时走 OpenAI Conversation State（`run_internal/oai_conversation.py` 的 `OpenAIServerConversationTracker`），由服务端管理历史；本地 session 与这三者互斥（docs/sessions/index.md:7）。
- **明确边界**：SDK 的 memory = **会话对话历史管理**，不是长期语义记忆/向量库；跨会话"事实记忆"要用户自己做（外部向量库/文件），SDK 不内置 RAG。官方文档把会话区分为 memory（`docs/sessions/`）与 sandbox memory（`docs/sandbox/memory.md`），后者属 SandboxAgent 的 rollout 记忆，超出本文文本 agent 范畴。

## 六、护栏与安全

- **输入护栏** `@input_guardrail`（可并行/串行）：`guardrail_function(ctx, agent, input) -> GuardrailFunctionOutput{tripwire_triggered, output_info}`（guardrail.py:19-130）。tripwire → 抛 `InputGuardrailTripwireTriggered`，整个 run 立即中止（首轮、起点 agent）。典型用法：离题检测、注入检测，甚至"劫持执行"改走别的流程（docstring 举例，guardrail.py:73-84）。
- **输出护栏** `@output_guardrail`：校验最终输出，失败抛 `OutputGuardrailTripwireTriggered`（guardrail.py:133-185）。RunConfig 也可以挂 run 级 `input_guardrails/output_guardrails`，与 agent 级并联生效（run_config.py:391-395）。
- **工具级护栏**（0.22 扩展，`tool_guardrails.py`）：`ToolInputGuardrail`/`ToolOutputGuardrail` 可经 `function_tool(tool_input_guardrails=[...], tool_output_guardrails=[...])` 挂到单个工具上——执行前/执行后拦截具体工具调用（FunctionTool 字段 `tool.py:480-484`），tripwire 抛 `ToolInputGuardrailTripwireTriggered`/`ToolOutputGuardrailTripwireTriggered`（exceptions.py:545-572）。执行顺序：input 护栏 →（审批）→ 工具副作用 → output 护栏（references/runner-lifecycle.md "Guardrail Ordering"）。
- **函数级"允许谁调用"**：`allowed_callers`（`FunctionTool.allowed_callers`，tool.py:518）限定 OpenAI Responses 模型上该工具可由 `"direct"`（agent 直接调）还是 `"programmatic"`（生成的代码程序调）调用；配合 `needs_approval`（人工审批，`RunState.approve()/reject()` 恢复）与 `timeout_seconds` 构成工具安全面。
- **数据脱敏**：`RunConfig.trace_include_sensitive_data`（默认从环境变量 `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA` 读，run_config.py:53-56、404）控制 trace 是否携带敏感内容；源码中大量 "data-redacted error" 机制（`exceptions.py`/`_debug.py`）确保脱敏路径下错误对象不泄漏 payload。

## 七、可观测性：tracing、会话恢复与 MCP

- **Tracing**：`src/agents/tracing/` 自成子系统——`TraceProvider`（抽象，provider.py:222）/`DefaultTraceProvider`（provider.py:300，默认导出到 OpenAI 后端）/`TracingProcessor`（`add_trace_processor`/`set_trace_processors`，setup.py:27）。处理器侧有 `BatchTraceProcessor`（批处理导出）、`ConsoleSpanExporter`（调试打印）、`BackendSpanExporter`（`processors.py:27/44/541/744`）。Span 层级：每次 `Runner.run` 建 `Trace`（`TraceCtxManager`/`create_trace_for_run`，run.py:738），内嵌 `task_span`→`turn_span`→`agent_span`（每次 agent 运行一个，`AgentSpanData` 记 name/tools/handoffs/output_type）→其下的 `generation_span`（模型调用）/`function_span`（工具）/`guardrail_span`/`handoff_span`（`__init__.py:217-260` 的 span 工厂列表）。`workflow_name`/`group_id`/`trace_metadata` 用于跨 run 聚合。
  **注（不确定处）**：0.22 main **没有内置 OpenTelemetry 导出器**（源码与 docs 检索 `opentelemetry/otel` 无命中）；如需 OTel 需自行实现 `TracingProcessor`，早期版本社区处理器在文档中有示例可查（建议查 docs/tracing.md 与历史 tag）。
- **会话/中断恢复**：审批（human-in-the-loop）触发 `NextStepInterruption` 时，runner 把 `RunState` 持久化（含 processed response、usage、guardrail 结果），用户 `result.to_state()` → `Runner.run(agent, state)` 恢复同一轮继续（result.py:542-589 docstring 示例；run.py:1095-1131 `resolve_interrupted_turn`）。这使**长任务可跨进程续跑**（配 SQLite 等 Session 存储）。
- **MCP 集成**：`AgentBase.mcp_servers`（agent.py:197）声明 MCP server，每次运行经 `MCPUtil.get_all_function_tools` 拉取其工具并入 `get_all_tools()`（agent.py:250-292）；`agents/mcp/` 提供 `MCPServerManager`（生命周期 connect/cleanup）、server、util；支持 Streamable HTTP/stdio、工具名冲突保留字（`mcp_config.include_server_in_tool_names`）与审批流（`MCPApprovalRequestItem`/`MCPApprovalResponseItem`，items.py 导出）。hosted 工具（`WebSearchTool`/`FileSearchTool`/`CodeInterpreterTool` 等，tool.py）由服务端执行并回传 `ToolCallOutputItem`。

## 八、关键文件速查、优缺点与启发

### 关键文件/代码节选索引

| 关注点 | 证据位置 |
|---|---|
| 循环语义 docstring | `src/agents/run.py:272-323`（run/run_sync/run_streamed 三处同文） |
| turn 计数 + MaxTurnsExceeded | `src/agents/run.py:1482-1507` |
| NextStep 状态机 | `src/agents/run_internal/run_steps.py:155-232` |
| 单轮执行 | `src/agents/run_internal/run_loop.py:2402-2530`（run_single_turn） |
| 模型调用 + 重试 | `src/agents/run_internal/run_loop.py:2533-2673`（get_new_response） |
| 工具执行 | `src/agents/run_internal/tool_execution.py` |
| 会话存取 | `src/agents/run_internal/session_persistence.py`（prepare_input_with_session / save_result_to_session） |
| Agent 定义 | `src/agents/agent.py:295-345` |
| function_tool 装饰器 | `src/agents/tool.py:2458-2712`；FunctionTool 类 `tool.py:441-614` |
| Handoff 定义 | `src/agents/handoffs/__init__.py:126-374` |
| guardrail | `src/agents/guardrail.py:19-343`；tool 级 `src/agents/tool_guardrails.py` |
| 结构化输出 | `src/agents/agent_output.py:60-192` |
| items/消息模型 | `src/agents/items.py:97-330`（RunItemBase/各 Item；`TResponseInputItem = ResponseInputItemParam`，items.py:79） |
| hooks | `src/agents/lifecycle.py:13-206`（RunHooks/AgentHooks 各 7 事件） |
| Model 接口 | `src/agents/models/interface.py:37-136` |
| tracing | `src/agents/tracing/provider.py`、`processors.py`、`setup.py` |
| 内部规范文档 | `.agents/references/runner-lifecycle.md`（turn/guardrail/流式一致性） |

### 优点

1. **API 面小且声明式**：Agent 就是 dataclass，主概念（工具/交接/护栏/会话）都收敛成 Agent 的一个列表字段；示例从 hello_world 到 customer_service（`examples/`）学习曲线短。
2. **handoffs 一等公民 + input filter**：交接不仅切换 agent，还保留了"历史所有权"与"模型可见历史 = 会话历史"的分离设计（`session_items` vs 过滤后输入），工程上非常讲究。
3. **模型中立**：`Model`/`ModelProvider` 抽象 + Responses/`OpenAIChatCompletionsModel` 双适配 + `MultiProvider`（按前缀选 provider）+ LiteLLM/any-llm 扩展，锁 OpenAI 的顾虑低。
4. **内建可观测性**：默认全链路 trace（trace/task/turn/agent/generation/function/guardrail/handoff span），无需自己埋点；`group_id` 可跨会话聚合。
5. **会话/恢复/记忆有清晰接口**：Session Protocol 极简，官方给 SQLite/Redis/Mongo/Dapr 实现；RunState 支持中断恢复与跨进程续跑。
6. **工程细节扎实**：结构化输出 strict schema 校验、同步工具自动进线程池、工具错误默认"回喂模型"、并行输入护栏与模型任务可协同取消、敏感数据可关闭（trace/脱敏错误路径）。

### 缺点 / 使用注意

1. **"记忆"是对话历史管理，不是知识/RAG**：需要长期事实记忆/检索时必须自建（向量库等），SDK 不提供 semantic memory 原语。
2. **编排原语到此为止**：并行、流水线、子任务结果聚合都要应用层 `asyncio`/自写组合（官方仅给 pattern 示例），没有工作流 DAG/重试编排。
3. **演进快、内部面大**：0.22 已有 sandbox/realtime/voice/hosted multi-agent 等分支，`run_internal/`（run_loop/turn_resolution/tool_execution 动辄 2-4 千行）+ `run_state.py` 5726 行，深度定制困难，且 internal API 不受兼容承诺保护（`AgentRunner` 明示 experimental）。
4. **默认上限与成本**：`max_turns=10` 需按场景调大/调小；tool 错误回喂模型、compaction 走 `responses.compact`（仅 OpenAI 模型）在非 OpenAI 场景下没有等价物。
5. **少量不确定点**（已在正文标注）：Swarm 传承无仓库内证据；`suppress_output` 在当前 main 无实现；OTel 需自研 processor。

### 对我们自研 harness 的启发

- **把主循环做成显式状态机**（`NextStep` 四态：RunAgain/Handoff/FinalOutput/Interruption），每个分支的副作用（钩子、持久化、追踪）集中在收口处，可测试性最好。
- **turn 语义要精确**：一次模型调用算一轮，工具/重试/交接不额外计费，且把 `max_turns`/`current_turn` 放进可序列化 state 以便续跑。
- **输入护栏可与模型调用并行**（代价是 tripwire 时要能取消在飞模型任务）；输出护栏只在最终输出处跑一次——顺序与去重规则要在文档里写死。
- **历史可见性分层**：区分"模型输入历史 / 会话持久化历史 / 回放历史"，handoff/过滤时三者的所有权分开管理（本 SDK 的 `session_items` 与过滤输入分离值得借鉴）。
- **存储用 Protocol + 轻接口**（get/add/pop/clear 级别），让 SQLite/Redis/云存储自由替换；把"自动摘要压缩"做成可插拔装饰器而非核心逻辑。
- **工具失败默认降级为消息回喂模型**（而非直接抛错），并把错误格式化点（formatter）暴露给用户；同步工具自动 offload 线程池。
- **tracing 用 spans 而非自研日志**：span 类型随概念走（agent/generation/function/handoff/guardrail），一次 run 一条 trace，天然支持多 agent 嵌套与 `group_id` 会话级聚合。

---

*文档基于 clone 到 `/tmp/harness-research/openai-agents` 的真实源码撰写；所有行号以提交 `89c02c8`（2026-08-28，v0.22.0）为准。Stars/Fork/创建时间来自 GitHub REST API（2026-09-04）。*
