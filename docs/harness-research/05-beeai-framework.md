# IBM beeai-framework 架构深度分析

> 研究对象：GitHub 官方仓库 `i-am-bee/beeai-framework`（main 分支，`--depth 1` 克隆）。
> HEAD = `59686000ab245229e906b9c5b358a23338d0ccf0`（2026-09-04，"feat(python): add evaluation framework (DeepEval + Ragas) (#1453)"），克隆于 2026-09-04。
> 代码证据路径均相对于克隆根目录 `/tmp/harness-research/beeai`，以 `python/…`、`typescript/…` 表示。**说明**：本仓库有两种文档源（`docs/` 与 `docs-old/`，内容基本同源），下文文档引用默认用 `docs/src/content/docs/…`。

## 概览

**定位**：BeeAI Framework（beeai-framework）是 IBM 发起、现归属 Linux Foundation AI & Data 下属 BeeAI 系列项目的"生产级 agent 框架"。README 首句即 "Build production-ready multi-agent systems in Python or TypeScript"。它不是 LangGraph 式的纯图运行时，也不是 LlamaIndex 式的数据框架，而是一套**自带观点（opinionated）的模块化 agent 工具包**：Agents + Backend(LLM) + Tools + Memory + Workflows + Serve(协议托管) + 可观测性，官方强调"lightweight"（轻量、无重型运行时依赖），当前 Python 侧主推 **RequirementAgent**（用规则约束 LLM 行为以获得确定性）。

**工程/生态元数据**：
- Stars/Forks：约 **3.4k**（2026-09 GitHub 组织页实测 3,384 stars / 482 forks，趋势仍在涨，标注"约"）。
- 语言：Python 与 TypeScript 双实现（monorepo：`python/` + `typescript/`），文档声称 feature parity。
- 包版本：Python `beeai-framework` **0.1.83**（`python/pyproject.toml`：`[project] name="beeai-framework"`, `requires-python = ">=3.11,<3.14"`）；TypeScript `beeai-framework` **0.1.30**（`typescript/package.json`）。
- License：Apache-2.0；版权头为 "© BeeAI a Series of LF Projects, LLC"。
- 与 IBM 的关系：README 法律声明明确 "IBM developers produced this code as an open source project (not as an IBM product)"；代码层面 IBM watsonx 是一等公民——`python/beeai_framework/adapters/watsonx/backend/chat.py` 提供 `WatsonxChatModel`（基于 LiteLLM），另有 `adapters/watsonx_orchestrate/`（watsonx Orchestrate 的 agents/serve 集成）、`adapters/agentstack/` 等。`adapters/beeai_platform/` 下全是自动生成的**弃用转发 shim**（`beeai_platform → agentstack`，见 `scripts/generate_shims.py`），反映平台品牌从 "BeeAI Platform" 更名为 "Agent Stack"。
- 协议：ACP（Agent Communication Protocol）与 M2M 相关协议在 2025-08-25 并入 A2A 并归 Linux Foundation（README "Latest updates"）；A2A/MCP/OpenAI 兼容 serve 均有实现（见下文）。

**历史脉络（README/docs）**：2024-08 建仓；2024-11 TypeScript Workflows 上线；2025-02 Python alpha 发布并引入 Backend 模块；2025-05 ACP/MCP 集成；2025-06 实验性 Requirement Agent；2025-08 ACP→A2A 合并。**重要提示（诚实标注）**：docs 明示 ReAct 与 ToolCalling agent "不再积极支持"（`docs/src/content/docs/modules/agents.mdx` Warning），但代码 `python/beeai_framework/agents/{react,tool_calling}/` 仍完整保留；任务描述中的"StateGraph/Step/Transition/Worker""SlidingWindow""guardrails 模块""@beeai 版本化运行"等名词**在本仓并不以这些符号存在**，对应物分别是：`Workflow`/`WorkflowState`（无图 DSL）、`SlidingMemory`/`TokenMemory`、RequirementAgent 的 requirement 规则体系 + 中间件、以及仓库外的 BeeAI/Agent Stack 平台寻址（本仓无证据），下文逐一说明。

## 模块分层（python/beeai_framework/ 顶层）

| 模块 | 职责 | 关键文件 |
|---|---|---|
| `agents/` | Agent 抽象与具体实现：base(BaseAgent)、requirement（主推，规则约束）、lite（无 system prompt 的最小 agent）、react（弃用）、tool_calling（弃用）、experimental | `agents/base.py`、`agents/requirement/agent.py`、`agents/requirement/_runner.py`、`agents/lite/agent.py` |
| `backend/` | 统一的 LLM 抽象：ChatModel（chat completion）、EmbeddingModel、Message 模型、工具 schema 组装 | `backend/chat.py`（957 行，核心）、`backend/constants.py`（provider 注册表）、`backend/message.py` |
| `adapters/` | 各家 provider/平台适配（ollama/openai/anthropic/watsonx/gemini/bedrock/vertex/groq/xai/mistral/deepseek/qwen/minimax/azure/litellm/transformers/… + a2a/acp/agentstack/beeai） | `adapters/{provider}/backend/chat.py` |
| `tools/` | Tool 抽象、input schema（pydantic→JSON Schema）、缓存与重试、@tool 装饰器、内置工具（search/weather/code/filesystem/mcp/handoff/think） | `tools/tool.py`（322 行）、`tools/errors.py` |
| `memory/` | 会话记忆：BaseMemory 接口 + 4 种策略 + ReadOnly 包装 | `memory/{base_memory,unconstrained_memory,sliding_memory,token_memory,summarize_memory}.py` |
| `workflows/` | Workflow（schema 化步骤编排）与 AgentWorkflow（agent 流水线封装） | `workflows/workflow.py`（196 行）、`workflows/agent/agent.py` |
| `emitter/` | 事件系统：分层 Emitter、EventMeta/trace、通配/正则匹配 | `emitter/emitter.py` |
| `context.py` `runnable.py` | **全局横切抽象**：RunContext（contextvar）、Run（惰性执行+任务队列）、run 生命周期事件 | `context.py`（338 行）、`runnable.py` |
| `retryable.py` | 通用指数退避/信号感知重试（被 ChatModel/Tool 复用） | `retryable.py` |
| `middleware/` | run 中间件（trajectory 轨迹日志、stream_tool_call 流式工具调用） | `middleware/trajectory.py`、`middleware/stream_tool_call.py` |
| `serve/` | 把 agent 托管成服务（Server/MemoryManager），结合 adapters 支持 A2A/MCP/OpenAI/ACP | `serve/server.py` |
| `cache/` | 结果缓存（null/unconstrained/sliding/decorator），ChatModel 与 Tool 均插桩 | `cache/` |
| `logger/` `errors.py` `template.py` `utils/` | 日志、FrameworkError 体系（含 explain/dump）、Mustache 风格 PromptTemplate、schema/clone/abort 工具 | `logger/logger.py`、`errors.py`、`template.py` |
| `evaluation/` | 评估框架（DeepEval + Ragas 适配，HEAD 提交新增） | `evaluation/` |

**核心横切设计**：几乎所有组件（ChatModel、Tool、Agent、Workflow）都是 `Runnable`，`run()` 返回惰性 `Run` 对象，支持 `.on(matcher, cb)`/`.observe(...)`/`.middleware(...)`/`.context(...)` 链式装配；每次 run 由 `RunContext.enter` 建立独立执行上下文（详见下节）。这是 beeai 区别于多数 Python agent 框架的最大特点：**运行期管线化且统一**。

## Agent 运行机制与 run 生命周期

### 基类与 run 入口
- `agents/base.py`：`BaseAgent(Runnable[R])`，抽象 `run(input: str | list[AnyMessage], **kwargs: Unpack[AgentOptions])`（注意：**输入允许裸字符串**，子类负责转 `UserMessage`）；`AgentOptions` 含 `expected_output: str | type[BaseModel]`、`total_max_retries`、`max_retries_per_step`、`max_iterations`、`backstory`、`signal`、`context`。`AgentOutput` 在 `RunnableOutput`（`output: list[AnyMessage]` + `context`）之上加 `output_structured`。
- `BaseAgent._to_run`（`agents/base.py:118`）用 `_is_running` 标志**拒绝并发**："Agent is already running!"；body 异常统一 `AgentError.ensure(e)` 包装；最后 `.middleware(*self.middlewares)`。
- `runnable.py:runnable_entry` 装饰器把子类 `run` 包成 `Run`：真正 handler 通过 `RunContext` 的 `run_params` 取到（可被中间件改写过的）输入再执行。`RunnableOutput.last_message` 空输出时回退 `AssistantMessage("")`。

### RunContext 生命周期（context.py）
`RunContext.enter(instance, handler, signal, run_params)`（`context.py:187`）：
1. 用 `storage`(ContextVar) 支持嵌套（父子 run 树），创建 `run_id/group_id/parent_id` 与 `EventTrace(id=group_id, run_id, parent_run_id)`；把 emitter 挂到 trace 上、`pipe` 到父 emitter；
2. `AbortController` 聚合外部 signal 与父 signal（`utils/cancellation.py`）；
3. 触发 `run.start`（`RunContextStartEvent(input=run_params)`）→ 若中间件在 start 事件里改写了 `input`，写回 `context.run_params`，实现**输入中间件**；
4. 同时起 runner_task 与 abort_task，`asyncio.wait(FIRST_COMPLETED)`——abort 时抛 `AbortError` 并取消 runner；
5. 成功发 `run.success`，异常包成 `FrameworkError` 发 `run.error` 再抛出；finally 发 `run.finish`（带 error/output），随后 `context.destroy()`（销毁 emitter、abort controller）。
`Run.__aiter__`（`context.py:69`）把所有 emitter 事件灌入内部 Queue，使 `async for (data, event) in run` 成为一等用法（流式消费）。

### 具体 agent 的主循环（以 lite/requirement 为例，均为真实代码）
- **LiteAgent**（`agents/lite/agent.py`）：无内置 system prompt。`run` 先 `await self._memory.clone()` 得到 run_memory（**隔离副本**）；循环：迭代计数超 `max_iterations` 抛 `AgentError`；`async for` 消费 `self._llm.run(messages, tools, signal, max_retries)` 流：`new_token` 事件 → 向 `ctx.emitter` 转发 `final_answer` 流式块；`success` → 追加 assistant 输出，若有 tool calls 则 `run_tools(...)` **并发执行**（`agents/_utils.py:run_tools` 用 `asyncio.gather(create_task(...))`，单工具失败被捕获到 `ToolInvocationResult.error` 而非中断），工具结果以 `ToolMessage` 回填内存；无 tool call 即收敛。**成功后才把 run_memory 提交回 `self.memory`**（`reset()` + `add_many`），失败不污染长期记忆——一种实用的"事务式"会话设计。
- **RequirementAgent**（主推，`agents/requirement/agent.py` + `_runner.py`）：每轮迭代前由 `RequirementsReasoner.create_request`（`requirements/utils/_llm.py:64`）把各 requirement 生成的 `Rule`（`allowed/hidden/forced/prevent_stop` 等标志）按优先级聚合成"本轮允许/隐藏/强制调用哪些工具"的 `RequirementAgentRequest`，再带 `tool_choice` 调 LLM；产出若为纯文本且允许停止，则用 `parse_broken_json` 尝试"救回"为 FinalAnswerTool 调用（`_runner.py:_create_final_answer_tool_call`）；`ToolCallChecker` 检测工具调用循环（同工具连续 N 次）后注入"禁用该工具"的额外规则重跑；工具错误按模板渲染成 ToolMessage 回喂模型而非直接失败（`_runner.py:_invoke_tool_calls`）；每步写入 `state.steps`，合并 `usage/cost`；`expected_output`（str 或 Pydantic）经 task prompt 模板下发并在 FinalAnswerTool 的 schema 中做结构化校验，最终 `RequirementAgentOutput(output=[answer], output_structured=final_state.result)`。run 结束时按 `save_intermediate_steps` 决定整体提交还是只回写"最后一条工具调用对"（`extract_last_tool_call_pair`，`memory/utils.py`）。
- **ChatModel.run**（`backend/chat.py:504`）即"LLM 循环"的底层：`Retryable`（`max_retries`、factor=0、信号感知）包裹，on_retry 处理两类自愈：`ChatModelToolCallError` → 把错误文本+可用工具清单作为临时消息追加后重试（`fix_invalid_tool_calls`）；空响应 → `retry_on_empty_response`。流式时 `_create_stream` 逐 chunk 发 `new_token`，chunk 聚合为 `ChatModelOutput.from_chunks`。工具调用回退：若模型不支持原生 tool calling 或 `tool_choice` 受限，则走 `force_tool_call_via_response_format`——把工具集转成 union JSON Schema 让模型以结构化输出产出工具调用，再 `model_validate` 校验、`_fix_tool_calls` 修补残缺参数、`_assert_tool_response` 断言与 `tool_choice`（required/none/single/具体工具）一致。

### "Runs 校验"小结（诚实标注）
beeai **没有** LangGraph 式独立 `InputSchema/OutputSchema` 校验层：输入校验散落在 ① Tool 层（pydantic `model_validate`，见下）；② 结构化输出层（`response_format` 校验、FinalAnswerTool/`output_structured`）；③ Workflow 的 state 是单一 pydantic schema（`to_model` 强校验，`workflow.py:run`），但 **run 结束尚无 output schema**（源码留有 `# TODO: add output schema`，`workflow.py:178`）。预期输出走"提示引导 + 结构化解码"双通道，而非硬性运行时 gate。

## 工具与后端

**Tool 抽象**（`tools/tool.py`）：`Tool(Generic[TInput, TRunOptions, TOutput])`，子类必须实现 `name/description/input_schema: type[TInput]`（Pydantic 模型，`model_json_schema()` 生成 JSON Schema 供 LLM 工具描述，`to_json_safe`）与 `_run(input, options, context)`。`run()`（`tool.py:117`）也是一个 `RunContext.enter`：先 `_validate_input`（`model_validate`，失败抛 `ToolInputValidationError`）→ 命中缓存则直接返回（key 由 input+options 序列化生成，`_generate_key`）→ `Retryable` 执行（`options.retry_options.max_retries/factor` 与 `context.signal`）→ 全程按序发 `start/error/retry/success/finish` 事件（`tools/events.py:tool_event_types`）。`@tool` 装饰器（`tool.py:254`）与 `get_input_schema`（`tool.py:202`）用 `inspect.getfullargspec` 从普通函数签名**运行时生成 pydantic 模型**（带默认值/注解/`**kwargs`→`extra="allow"`），docstring 作为 description，同步/异步函数皆可，`with_context=True` 注入 `RunContext`；返回值非 `ToolOutput` 时包成 `StringToolOutput(str(...))`。

**错误处理设计**：工具失败不直接中断 agent——`run_tools` 把结果收进 `ToolInvocationResult(error=...)`，由 agent（requirement/lite）决定把错误文案渲染回上下文继续迭代；`ToolError.ensure` 且 `FrameworkError.is_fatal` 为真才上抛。`ChatModelToolCallError` 等 backend 错误在 `backend/chat.py` 内做修复重试。

**Backend/LLM 抽象**：`ChatModel`（`backend/chat.py`）统一接口（create/stream 两个抽象方法由 provider 实现）；`from_name("provider:model", params)` 静态工厂（`chat.py:747`）经 `parse_model` + `load_model`（`backend/utils.py`）+ `BackendProviders` 注册表（`backend/constants.py`，含别名如 `watsonx/ibm`、`qwen/dashscope`）懒加载 provider 子类；类级 `tool_choice_support`、`allow_parallel_tool_calls`、`use_strict_tool_schema` 等开关刻画各家能力差异。`Backend`（`backend/backend.py`）把 chat + embedding 捆成一个可 `clone()` 的对象。python 官方 Python 侧还通过 `adapters/litellm` 与 `adapters/transformers` 支持"任意 LLM"接入。

## Memory：各内存类与生产取舍

`BaseMemory`（`memory/base_memory.py`）定义 `messages/add/delete/reset` + `add_many/splice/is_empty/as_read_only/clone/to_json_safe`。实现（均为**纯内存列表实现**，未内置持久化）：
- `UnconstrainedMemory`：无上限追加。生产问题：无限增长 → 仅供演示/短会话；默认 memory（如 LiteAgent）虽用它，但每次 run 走 clone 隔离。
- `SlidingMemory`（`memory/sliding_memory.py`）：按**条数**滑动窗口（`config.size`）；溢出时调 `removal_selector`（默认删首条 `messages[0]`），用户可注入策略（如优先删 tool 消息）；删除兜底不足时抛 `ResourceError`。
- `TokenMemory`（`memory/token_memory.py`，生产推荐）：按 **token 预算**滑动；可注入 `tokenize/estimate/removal_selector` handlers（`llm` 参数用于精确 tokenizer，`sync()` 惰性校准，脏比率 ≥ `sync_threshold`(0.25) 才触发 sync 以省 API 调用）；`capacity_threshold`(0.75) 决定提前驱逐水位；单条消息超 `max_tokens`（默认 128k）直接 `ResourceFatalError`。
- `SummarizeMemory`（`memory/summarize_memory.py`）：每次 add 即调 LLM 把全量对话压缩成一条 SystemMessage 摘要（简单但**无阈值触发/无分层**，成本高，属实验性质）。
- `ReadOnlyMemory`（`memory/readonly_memory.py`）+ `as_read_only()`：多 agent 共享防篡改视图（AgentWorkflow 用）。

工具/临时消息治理：`memory/utils.py` 提供 `TEMP_MESSAGE_META_KEY="tempMessage"` 与 `delete_messages_by_meta_key`——ChatModel 重试注入的"修复消息"带 temp 标记，requirement agent 每轮末尾统一清扫（`_runner.py:322`），避免脏上下文进入下一轮。

## Workflow：步骤编排与 agent 融合

- `Workflow(schema, name)`（`workflows/workflow.py`）：Python 侧是**轻量顺序机**而非状态图 DSL——`add_step(name, handler)` 注册；handler 签名 `(state: T) -> str | None`，返回值为路由目标，内置保留符 `START/SELF/PREV/NEXT/END`（`workflow.py:33`，字符串路由，见 `run()` 中 `if/elif` 分支）；`state` 是单一 pydantic 实例，每步传入 `model_copy(deep=True)` 副本、结束后 `check_model` 校验再回写 `run.state`，`run.steps` 记录执行轨迹；每步发 `start/success/error` 事件（含 run/step/next）。**注意**：非 DAG、无并行节点、无 checkpoint、run 尾部 output-schema 未实现（TODO）。TypeScript 侧同为 `Workflow`（`typescript/src/workflows/workflow.ts`）；docs 标注 Workflows 正在重构（"V2 Workflow Proposal" discussion #1005）。
- `AgentWorkflow`（`workflows/agent/agent.py`）：在 `Workflow` 之上把"多 agent 顺序协作"建模为**多个输入的任务流水线**——`Schema(inputs, current_input, final_answer, new_messages)`；`add_agent(name, role, instructions, tools, llm)` 注册的每步会现场 `create_agent(memory.as_read_only())`（ToolCallingAgent/RequirementAgent 二选一），每步弹出下一个 `AgentWorkflowInput(prompt/context/expected_output)` 执行，agent 产出以 `new_messages` 尾部窗口传递到下一步。默认 execution `max_retries_per_step=3, total_max_retries=3, max_iterations=20`。README 的多 agent 例子用 `HandoffTool`（工具化移交另一个 agent）+ `ConditionalRequirement` 实现"路由式"协作。
- 组合启发：确定性编排（Workflow/AgentWorkflow 顺序 + 状态 schema）+ agentic 步骤（每步内部是完整 ReAct/Requirement 循环），两者共享同一 `Run`/Emitter 事件体系，嵌套观察（如 `AgentWorkflow` 内 ChatModel 事件）天然可用。

## 多语言与协议

- TS/Python 对齐：文档与目录镜像（`python/examples/*` ↔ `typescript/examples/*`，agents/backend/cache/emitter/logger/memory/middleware/tools/workflows 一一对应）；但**实现进度不完全对等**（如实标注）：serialization 仅 TS 有（python docs "Example coming soon"）、evaluation 是 python 侧 2026-09 才落地的 HEAD 特性。
- ACP：python 提供双端——`adapters/acp/agents/agent.py`（把远程 ACP agent 包装成本地 Agent 调用）与 `adapters/acp/serve/server.py`（把本地 agent 以 ACP 服务暴露，含 IO/agent executor）；另有 `acp_zed`（Zed 场景）。ACP 已并入 A2A 移交 Linux Foundation（README 2025-08-25），迁移状态见 `docs/src/content/docs/integrations/acp.mdx`。
- A2A/MCP/OpenAI：`adapters/a2a/` 含客户端 agent 与 serve（`react_agent_executor.py`、`tool_calling_agent_executor.py` 等）；`tools/mcp/mcp.py` + `serve` 的 MCP server（examples/serve/mcp_agent.py）；`adapters/openai/serve/` 同时提供 **Chat Completions 与 Responses 两种 API** 的 OpenAI 兼容服务端（`server.py`、`api.py`）；`serve/server.py` 的 `MemoryManager` 提供按会话存续记忆的托管。
- watsonx/平台：`WatsonxChatModel`（LiteLLM 底座，`tool_choice_support={"none","single","auto"}`）；`adapters/agentstack/` 是面向 Agent Stack 平台的 provider（chat/embedding/vector_store/factory/server），`beeai_platform` 旧路径自动转发；"agent 以 `@namespace/name` 版本化寻址/运行"属于 **BeeAI/Agent Stack 平台侧能力，本仓无对应代码**（本仓仅见 provider 名与文档引用），不做推断。

## 事件与可观测、序列化/断点恢复

- **Emitter**（`emitter/emitter.py`）：类名空间（namespace）+ 树形层级，`Emitter.root().child(namespace=[...], creator=...)` 子 emitter 自动 `pipe` 到父级（内部以持久监听实现事件上浮），因此监听父级即可收子树事件，`match_nested` 控制是否展开；`EventMeta(id,name,path,created_at,source,creator,context,group_id,trace,data_type)`；匹配器支持字符串、正则、函数；每次 run 的事件都带 `EventTrace`（group/run/parent_run_id），可跨组件（Workflow→Agent→ChatModel→Tool）聚合为一次完整 trace。Run 事件类型注册表 `run_context_event_types`（start/success/error/finish）。`middleware/trajectory.py:GlobalTrajectoryMiddleware` 订阅 run 树把工具/LLM 调用轨迹打印/落盘（`included/excluded` 按类过滤），是开箱调试利器；`examples/middleware/` 还有 prompt-injection 检测、content-filter、secrets-detection 等安全类中间件示例。
- **Guardrails 的对应物**（如实标注，无独立 guardrails 模块）：① RequirementAgent 的 requirement 体系（`agents/requirement/requirements/`，`ConditionalRequirement` 支持 `force_at_step/only_after/min_invocations/consecutive_allowed` 等约束，见 `conditional.py:29`；需求可访问状态并产出 `Rule` 影响下一轮工具白名单，events.py 里 `RequirementError/init` 事件）；② 工具输入 JSON Schema 严格校验 + tool_choice 断言；③ 中间件（可前置注入/拦截）；④ docs 层面把 requirements 直接称为 "reasoning rules, guardrails, and user permissions"（`docs/.../tour.mdx`）。**没有**独立的输出护栏类。
- **Serialization（重要差异）**：python 包**目前没有 serializer 模块**（全仓 python 侧无 `Serializer`；`docs/src/content/docs/modules/serialization.mdx` 的 python 代码块全部为 "coming soon"），agent 会话持久化主要靠各组件 `clone()`（`Cloneable`，utils/cloneable.py）手工复制，属浅替代。TS 侧 `typescript/src/serializer/serializer.ts` 是完整实现：全局工厂注册表 `Serializer.register/registerSerializable`（类名→toPlain/fromPlain/createEmpty/updateInstance），`Serializable` 类提供 `createSnapshot/loadSnapshot/fromSerialized`；序列化格式为带 `__version__`（来自 `typescript/src/version.ts`）+ `__class/__ref/__value` 节点的版本化 JSON（示例见 serialization.mdx "Context matters" 的原始串），支持别名、循环引用惰性填充；**反序列化函数体默认禁用**（`Function()` 执行任意代码风险，须显式 `allowFunctionDeserialization: true`，见 serializer.ts:40 注释）——安全设计值得借鉴。
- **断点恢复/checkpoint**：python 侧**没有** checkpointer/断点续跑原语（与 LangGraph checkpoint、Agno session 不同）；最接近的是 requirement agent 的"成功才提交记忆 + `save_intermediate_steps` 复用中间结果 + serve 的 `MemoryManager` 会话记忆"。

## 关键代码节选（路径为证）

- run 生命周期事件骨架：`python/beeai_framework/context.py` `RunContext.enter`（`start`→handler/abort 竞速→`success/error/finish`→destroy）。
- agent 并发守卫与错误包装：`python/beeai_framework/agents/base.py:118` `_to_run`（`if self._is_running: raise RuntimeError("Agent is already running!")`）。
- LiteAgent 主循环/记忆提交：`python/beeai_framework/agents/lite/agent.py:107-155`。
- RequirementAgent 规则驱动执行：`python/beeai_framework/agents/requirement/_runner.py:250`（`run`）、`:64`（`RequirementsReasoner.create_request`）、`requirements/conditional.py:29`。
- ChatModel 重试与工具调用回退：`python/beeai_framework/backend/chat.py:542`（Retryable+on_retry）、`:604`（流式/cache）、`:628`（response_format 救回 tool call）。
- Tool 校验+缓存+重试：`python/beeai_framework/tools/tool.py:111`（`_validate_input`）、`:158`（Retryable）、`:202`（`get_input_schema`）。
- TokenMemory 预算驱逐：`python/beeai_framework/memory/token_memory.py:101`（`add`）。
- Workflow 路由与 TODO：`python/beeai_framework/workflows/workflow.py:125-181`。
- TS 序列化器与函数反序列化安全门：`typescript/src/serializer/serializer.ts:40-52`。

## 优缺点与横向对比启发

**优点**：① 全组件统一的 `Runnable→RunContext→Run` 抽象使事件/中间件/中止/克隆语义一处实现处处生效，代码风格高度一致、心智负担小；② 全程 pydantic 强类型（工具输入 schema、workflow state、结构化输出），配合 JSON Schema 打通任意 LLM；③ RequirementAgent 把"确定性"做成可声明的规则而非提示词，直接应对生产场景的"模型不听话"问题；④ 记忆"每 run 克隆、成功才提交"的隔离设计很实用；⑤ 工具失败转上下文反馈、chat 层 malformed-tool-call 自愈等错误韧性考虑细致；⑥ 协议面广（A2A/ACP/MCP/OpenAI serve）。**缺点/风险**：① python serialization 缺失使"agent 会话存续/断点恢复"在主力语言上仍是空白，跨进程/跨重启持久化要自建；② Workflow 仍是线性顺序机（手动字符串路由、无图编译/并行/checkpoint、output schema TODO），复杂编排能力明显弱于 LangGraph，官方也承认在重构；③ API 处于 0.1.x 快速变动期（`expected_output` vs TS `expectedOutput`、beeai_platform→agentstack 迁移 shim、ReAct/ToolCalling 弃用但文档与代码并存）；④ 无独立 guardrails/checkpointer 模块，安全护栏散落（requirement 规则+中间件+示例）；⑤ 文档与代码/语言间"coming soon"不一致较多，需以源码为准。**对 harness 建设的启发**：① 把"run 生命周期事件（start/success/error/finish）+ trace 分组"作为统一可观测基线，比各框架自造事件名更易做跨 harness 归一化；② "工具调用产物逐条校验 + 错误回喂上下文 + 有限修复重试"是可靠工具调用的通用配方；③ 同一抽象上叠加确定性编排（workflow state schema）与 agentic 步骤，可复用于我们 harness 的混合编排；④ python 侧序列化缺失说明"会话存续"必须作为一等需求从框架选型起就评估，不能靠 clone() 补。
