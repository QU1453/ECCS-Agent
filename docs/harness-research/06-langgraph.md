# LangChain LangGraph 架构深度分析

> 研究对象：GitHub 官方仓库 `langchain-ai/langgraph`（main 分支，`--depth 1` 克隆，克隆于 2026-09-04）。
> HEAD = `81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1`（2026-09-03）。`libs/langgraph/pyproject.toml` 显示主包版本 **1.2.11**（`requires-python >=3.10`，MIT）。
> 代码证据路径均相对于克隆根目录（沙箱中实际路径为 `/tmp/harness-research/langgraph`，镜像副本 `/workspace/harness-research/langgraph`），以 `libs/langgraph/langgraph/…` 表示。
> **诚实标注**：官方文档托管在独立站 docs.langchain.com，本仓 `docs/` 目录只有 `redirects.json`/`generate_redirects.py` 等重定向脚手架，**无正文**，故本文一切结论以源码为准；个别仓库外事实（recursion_limit 默认值、Stars 数、Platform 产品行为）已单独标注来源与时点。

## 概览

**定位**：README 自述 "Low-level orchestration framework for building stateful agents"（低层有状态 agent 编排框架），GitHub 官方描述为 "Build resilient agents."。LangGraph 不是"帮你写 ReAct 循环"的高层 harness（那是其 `prebuilt` 子包或上移后的 `langchain.agents.create_agent` 的活），而是一套**可长期运行、有状态、可持久续跑（durable execution）的图式运行时**：用户定义 StateGraph，节点间靠共享状态通信，编译器把它降维成 Pregel 运行时（channels + actors + 超步），并让 checkpointer/stream/interrupt 成为一等公民。

**工程元数据**：
- Stars/Forks：约 **40.9k / 6.9k**（GitHub API 快照，2026-09-02，`stargazers_count=40882`，标注"约"）。
- 语言：Python（本仓）；另有独立仓库 LangGraph.js（TS/JS 等价实现）。
- 与 LangChain 的关系：LangChain Inc 出品，属 LangChain 生态的**运行时底座**；只依赖 `langchain-core>=1.4.7`（消息模型 `AnyMessage/BaseMessage`、`Runnable` 抽象、callbacks、`RunnableConfig`）而不依赖完整 `langchain`。
- monorepo 多包布局（`libs/`）：`langgraph`（1.2.11，运行时本体）、`checkpoint/`（`langgraph-checkpoint` 4.2.0，checkpointer 抽象与内存实现）、`prebuilt/`（`langgraph-prebuilt` 1.1.0，**独立分发但共享 `langgraph.prebuilt` 命名空间**）、`checkpoint-postgres/`、`checkpoint-sqlite/`、`sdk-py/`（`langgraph-sdk`，客户端）、`cli/`。注意：主包 `langgraph` 顶层**已无 `__init__.py`**（目录内只见 `graph/`、`pregel/` 等子模块与 `py.typed`），`langgraph.prebuilt`、`langgraph.checkpoint.*` 由独立 wheel 以命名空间包方式提供——这是 1.x 把 prebuilt（依赖 langchain）与 checkpoint 拆出主库后的结果。
- LangGraph Platform / Server：托管部署产品（旧名 LangGraph Platform，现并入 LangSmith Deployment），不在本仓；本仓仅 `libs/sdk-py` 客户端与 server 侧协议定义（`langgraph/runtime.py`、`pregel/remote.py` 提供 `Runtime`/`RemoteGraph` 与平台服务对接模型）。
- 版本脉络（源码内可见）：v0.x→v1.0 做过大规模重命名/重排：`pregel.py→pregel/main.py`、`loop.py→pregel/_loop.py`、`algo.py→pregel/_algo.py`、通道 `channels/*` 拆文件（`channels/base.py`、`last_value.py`、`topic.py`、`binop.py`…）；`MessageGraph` 标注弃用（`graph/message.py:312` "deprecated in langgraph 1.0.0, to be removed in 2.0.0. Please use StateGraph with a `messages` key instead"）；`config_schema`→`context_schema`；顶层 `__init__` 删除。**旧资料（单文件 pregel/loop.py 等）与当前 main 布局不一致，需注意。**

## 核心模型：StateGraph、状态规约与 Channel

### StateGraph（构建期）
- `StateGraph` 是纯 **builder**（`libs/langgraph/langgraph/graph/state.py:131`，"cannot be used directly for execution… must first call `.compile()`"）。构造签名（`state.py:216`）：`StateGraph(state_schema, context_schema=None, *, input_schema=None, output_schema=None)`。
- 节点签名规约：`State -> Partial<State>`（`state.py:134` 类 docstring），即节点吃全量 state、返回**部分更新字典**（或 `Command`）。
- 边 API：`add_edge`（含**多源 join**：`add_edge(["a","b"], "c")` 存为 `waiting_edges`，`state.py:928-980`）、`add_conditional_edges`（路径函数 `state -> Hashable | list[Hashable]`，`state.py:982`）、`add_sequence`、`set_entry_point/set_finish_point`。每个节点可带 `retry_policy/cache_policy/error_handler/timeout/trace_policy/defer`（1.x 新增节点级策略，`state.py:376`）。
- `compile(checkpointer, interrupt_before/after, store, cache, …)`（`state.py:1177`）→ 返回 `CompiledStateGraph`（`state.py:1404`，**`Pregel` 的子类**）。编译期做 schema 内省（`_add_schema`，`state.py:343`）、把 schema 字段映射为 channels、把每个节点包成 `PregelNode`。

### 状态 schema → channel 的映射（关键机制）
每个 state 字段按注解类型映射成**一种 channel**（`state.py:_get_channels/_get_channel`，行 1815-1873）：
1. **无注解字段** → `LastValue(annotation)`：单值，一个超步内只允许一次写入（多处写入报 `InvalidUpdateError`"Can receive only one value per step. Use an Annotated key…"，`channels/last_value.py:59`）。
2. **`Annotated[T, reducer]` 且 reducer 是二元函数** → `BinaryOperatorAggregate(T, reducer)`（`state.py:_is_field_binop` 行 1904，用 `signature` 探测恰两参）。其 `update(values)`（`channels/binop.py:123`）把本超步所有写入按序折叠：`value = operator(value, w)`；另有 `Overwrite` 包装值可绕过 reducer 整体覆写（`types.py:978`）。
3. **元数据里显式给出 BaseChannel 对象/类**（如 `Annotated[list, DeltaChannel(reducer)]`）→ 用之（`state.py:_is_field_channel` 行 1876）。
4. **managed value**（`Annotated[int, SomeManager]`，`_is_field_managed_value`）→ 不进 channel，而是运行时按任务上下文现算的值（见 RemainingSteps）。
5. 单值 schema（非 TypedDict，如 `StateGraph(int)`）→ 特殊根字段 `"__root__"`。

由此，"哪些 state 字段能并发写、怎么写"完全由字段的 reducer/channel 语义决定——`add_messages` 字段天然支持同超步多节点各追加一条消息。

### Channel 抽象（运行时状态单元）
`BaseChannel`（`channels/base.py:19`）：`ValueType/UpdateType`、`get()`（空则 `EmptyChannelError`）、`update(values: Sequence[Update]) -> bool`（**Pregel 在每超步结束时把该步全部写入一次性交给它聚合**）、`consume()/finish()`（生命周期通知）。内建通道（Pregel 类 docstring，`pregel/main.py:496-512`）：
- `LastValue`（默认；保留最后值）；`LastValueAfterFinish`（结束后才可见，用于 defer 节点）；
- `Topic(typ, accumulate=False)`（`channels/topic.py:23`）：PubSub 风格"本超步一批值"，accumulate=False 则每超步清空——**TASKS 动态任务通道即 Topic(Send, accumulate=False)**；
- `BinaryOperatorAggregate`（带 reducer 的字段）；
- `EphemeralValue`（START 输入通道）、`NamedBarrierValue`（多源 join 计数）、`UntrackedValue`、`DeltaChannel`（beta，HTTP 驱动图的消息增量优化，`channels/delta.py`）。

### 消息模型
- `add_messages(left, right)`（`graph/message.py:60`）：按消息 **id** 合并列表；同 id 则右侧替换左侧；`RemoveMessage(id=…)` 作为墓碑删除；`RemoveMessage(id=REMOVE_ALL_MESSAGES)` 清空重建；缺 id 自动补 uuid。支持 `format="langchain-openai"` 转 OpenAI 消息格式。
- `MessagesState`（`graph/message.py:372`）：`messages: Annotated[list[AnyMessage], add_messages]`——**任何 agent harness 的状态基座**（`AnyMessage` 是 langchain-core 的消息联合类型）。
- `MessageGraph`（`graph/message.py:316`）= 整个 state 只有 `messages` 键的 `StateGraph` 子类，已弃用（统一用 `StateGraph`+`messages` 键替代）。

### 为什么叫 "Pregel"（BSP 超步计算）
README 致谢段明言："LangGraph is inspired by [Pregel](https://research.google/pubs/pub37252/) and Apache Beam. The public interface draws inspiration from NetworkX." 即灵感来自 Google 2010 年 Pregel 论文（图并行计算的 **Bulk Synchronous Parallel（BSP）** 模型）与 Beam，接口风格借鉴 NetworkX。代码层：
- `Pregel` 类 docstring（`pregel/main.py:454-478`）："Pregel combines **actors** and **channels** into a single application… following the **Pregel Algorithm/Bulk Synchronous Parallel** model"，每步三阶段：**Plan**（选本超步要执行的 actor：首步=订阅输入通道者，之后=订阅了上一步被更新通道者）→ **Execution**（并行执行全部选中 actor，期间通道写入对其它 actor 不可见）→ **Update**（用本步写入更新通道），循环至无 actor 可选或达最大步数。
- 执行主循环处注释（`pregel/main.py:2959-2963`）："Similarly to Bulk Synchronous Parallel / Pregel model computation proceeds in steps, while there are channel updates. Channel updates from step N are only visible in step N+1; channels are guaranteed to be immutable for the duration of the step"——**超步内的通道不可变、写入延迟到超步边界生效**，正是 BSP 的"同步屏障"思想的直接落地（每轮超步天然是一次全局同步点，也是 checkpointer 的落盘点）。actor≈Pregel 顶点，channel 值≈顶点间的消息，而"边"通过通道订阅/写入隐式表达。

## 运行时：Pregel 执行模型

### 节点与边的编译产物（隐藏的 branch 通道）
`attach_node/attach_edge/attach_branch`（`graph/state.py:1444-1624`）把图降维成通道触发：
- 内部命名常量 `_CHANNEL_BRANCH_TO = "branch:to:{}"`（`state.py:98`）、`START="__start__"`、`END="__end__"`（`constants.py`）。
- 每个真实节点 `key` 注册一个**隐藏触发通道** `branch:to:{key}`（`EphemeralValue(Any, guard=False)`，defer 节点用 `LastValueAfterFinish`），且该节点的 `PregelNode.triggers=[branch:to:{key}]`。
- 一条静态边 `X→Y` 编译成：给节点 X 的 writers 追加一个 `ChannelWrite`（向 `branch:to:Y` 写 None）（`state.py:1551-1559`）。于是 X 跑完→写入 Y 的触发通道→下超步 Y 被调度。**图中一切"条件边/环/并行"最后都化为"谁向哪个 branch 通道写了值"**，这是 LangGraph 把 NetworkX 式有向图映射到 BSP 的关键：连 `END` 都不需要专门处理（写向不存在的目标即无事发生、任务集耗尽即停机）。
- 条件边（`attach_branch`）：给源节点追加 `BranchSpec.run(...)` writer——先经 `reader`（基于 `ChannelRead.do_read(..., fresh=True)`，见 `graph/state.py:1613` 与 `_algo.py:local_read`）读取含"本节点刚写但未提交"的视图，跑路径函数，把返回的名字（或 `Literal` 提示、path_map 别名）转成若干 `branch:to:{dest}` 写入；返回 `Send` 则写入 TASKS 通道。`local_read` 的 `fresh=True` 语义保证条件边能看到当前节点本超步内的自我写入（对 router 型节点至关重要）。
- 多源 join（`waiting_edges`）：创建 `join:a+b:c` 的 `NamedBarrierValue` 通道，各源节点写令牌，目标节点 trigger 它（`state.py:1560-1575`）。

### 调度与超步循环（main loop）
`CompiledStateGraph` 继承 `Pregel`（`pregel/main.py:450`）。核心循环（`main.py:2964` 附近，同步流；异步同构）：
```python
# Similarly to Bulk Synchronous Parallel / Pregel model ...
while loop.tick():                       # Plan：prepare_next_tasks + 中断检查
    for _ in runner.tick(                # Execute：并发执行本超步所有任务
        [t for t in loop.tasks.values() if not t.writes],
        timeout=self.step_timeout, ...,
    ):
        yield from _output(...)          # 边执行边吐 stream 事件
    loop.after_tick()                    # Update：apply_writes + 落 checkpoint
```
- `PregelLoop`（`pregel/_loop.py:158`）持 `checkpoint/channels/tasks/step/stop`；`tick()`（`_loop.py:599`）做：步数检查（`step > stop` 则 `status="out_of_steps"`）→ `prepare_next_tasks` → 任务空则 done → interrupt_before 检查 → 返回是否继续。
- **`prepare_next_tasks`（`pregel/_algo.py:392`）**= Plan：① 消费 TASKS 通道（Topic of Send）→ 每个 Send 生成一个 **PUSH** 任务（动态并行）；② 用上一步的 `updated_channels × trigger_to_nodes` 快速圈定候选 PULL 节点（否则退化遍历全部进程），对每个候选再按**通道版本**精判：`proc` 订阅的通道中只要有"版本号 > 该节点 versions_seen 记录"的更新才触发（`_algo.py:606 _triggers` 逻辑）——版本比较替代"边是否存在"的判断。
- **并发执行**：`PregelRunner.tick`（`pregel/_runner.py:176`）把所有任务 submit 进 `BackgroundExecutor`（线程池/异步 executor，`pregel/_executor.py`），`concurrent.futures.wait(FIRST_COMPLETED)` 边跑边收；任一任务失败（非 `GraphBubbleUp`）→ 停掉其它任务（`_should_stop_others`），异常收集后统一上抛。单个任务执行 `run_with_retry`（`pregel/_retry.py`）套重试策略。
- **`apply_writes`（`pregel/_algo.py:232`）**= Update：任务按 path 排序（确定性！），每任务先把"读到过的通道版本"记入 `versions_seen`；将 writes 按 channel 分组后调 `channels[chan].update(vals)`（此时才可见）；被更新通道版本号 `increment`（`_algo.py:227`，默认 int +1，可由 checkpointer 换成 uuid）；返回 `updated_channels` 集合驱动下个超步触发。任何未更新的可用通道在超步切换时收到空 update 通知（`consume` 语义，`_algo.py:326-333`），"最后超步"再统一 `finish()`。
- **确定性任务 id**：PUSH/PULL 任务 id 由 `xxhash(xxhash(checkpoint_id, ns, step, node, PULL, *triggers))` 或 v2 的 uuid5 生成（`_algo.py:550/616`）——同一 checkpoint 重放得到同一批任务 id，这是回放（replay）与 checkpoint 写入对齐的基石。
- **循环/递归保护**：图**允许环、无静态环检测**（agent 循环是特性）；运行时以 `recursion_limit` 兜底——`__enter__` 设 `step = checkpoint_metadata["step"]+1`、`stop = step + config["recursion_limit"] + 1`（`_loop.py:1700-1701`），超限后 `tick` 置 `out_of_steps`，主循环抛 `GraphRecursionError`（`main.py:3002-3011`；消息即 "Recursion limit of {n} reached without hitting a stop condition… set the `recursion_limit` config key"）。默认值 25 来自 langchain-core `RunnableConfig`（仓库外，标注）。

### Send / Command：编程式控制
- **`Send(node, arg)`（`types.py:704`）**：条件边/节点返回 `Send` 或 `list[Send]` → `_control_branch`/`attach_branch` 写入 TASKS 通道（`state.py:1750`、`_CHANNEL_BRANCH_TO` 同区）→ 下一超步生成 PUSH 任务、以 `Send.arg` 为任务输入，**同一节点可被并行多实例化且输入互不相同**（map-reduce 的标准写法，`types.py:713-748` 例）。
- **`Command(graph, update, resume, goto)`（`types.py:798`）**：节点可返回 Command 而非 dict 来"更新状态 + 改路由 + 传 resume 值 + 向父图发指令"。节点返回的 Command 由 `_control_branch`（`state.py:1749`）转写：`goto: str` → `branch:to:{s}` 写；`goto: Send` → TASKS；`goto` 缺省但带 update → 走正常 state 写入；`Command.PARENT` 用于 subgraph 节点向父图 goto/update（子图内 `graph="__parent__"`，`types.py:848`）。图输入层也可直接传 `Command`（如 `graph.invoke(Command(resume=…))`），经 `map_command`（`pregel/_io.py:56`）转成 pending writes（goto→branch/TASKS、resume→`(NULL_TASK_ID, RESUME, v)`、update→state 键值对）。
- 节点输入适配：`attach_node` 的 `_get_updates`（`state.py:1456`）把节点返回的 dict/Command/类型化对象过滤成对已知输出通道的 `(key, value)` 写；单输入 schema（`__root__`）另有 `_get_root`。

### 流式通道的"不可见屏障"带来的语义
所有节点读到的都是**上个超步结束时已提交的通道值**；同一超步内节点间无通信（无共享可变内存）。这是 LangGraph 与"普通 asyncio agent while 循环"最本质的差异：**并行=同一超步内多个 PULL/PUSH 任务；同步=每超步一次的屏障+checkpoint**。

## Agent harness：create_react_agent

**真实路径**：`libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py`（prebuilt 已独立成 `langgraph-prebuilt` 发行，但导入路径仍是 `langgraph.prebuilt`）。注意：main 分支该文件顶部已标注 **deprecated**——"`create_react_agent` … in favor of `create_agent` from the `langchain` package"（migration 见 migrate/langgraph-v1）；`AgentState` 亦标注 "moved to `langchain.agents`"。即高层 agent 工厂正在从 langgraph.prebuilt 上移进 langchain 包。

主循环构建（`chat_agent_executor.py:278` 起，真实代码节选）：
```python
# 状态：messages(可并发追加) + remaining_steps(managed，见下)
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    remaining_steps: NotRequired[RemainingSteps]        # chat_agent_executor.py:57

# agent 节点：prompt(可 str/SystemMessage/callable/runnable) | model，模型已 bind_tools
def call_model(state, runtime, config):
    ...
    response = cast(AIMessage, static_model.invoke(model_input, config))
    if _are_more_steps_needed(state, response):          # remaining_steps 不足时的优雅退出
        return {"messages": [AIMessage(id=response.id,
                content="Sorry, need more steps to process this request.")]}
    return {"messages": [response]}                      # add_messages 追加

# 路由：有无 tool_calls
def should_continue(state) -> str | list[Send]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return END                                       # 或 post_model_hook / generate_structured_response
    if version == "v1": return "tools"
    return [Send("tools", ToolCallWithContext(tool_call=c, state=state))   # v2：每个 tool_call 一个并行任务
            for c in last_message.tool_calls]            # chat_agent_executor.py:831

workflow = StateGraph(state_schema=state_schema, context_schema=context_schema)
workflow.add_node("agent", RunnableCallable(call_model, acall_model), input_schema=input_schema)
workflow.add_node("tools", tool_node)
workflow.set_entry_point(entrypoint)                     # 默认 "agent"
workflow.add_conditional_edges("agent", should_continue, path_map=agent_paths)
workflow.add_conditional_edges("tools", route_tool_responses, ...)  # 仅 return_direct 工具存在时
return workflow.compile(checkpointer=..., store=..., interrupt_before=...,
                        interrupt_after=..., debug=..., name=name)   # chat_agent_executor.py:995
```
- **tools 循环**：`agent → tools → agent` 是"图上环"而非代码 while：agent 吐含 tool_calls 的 AIMessage → `should_continue` 经条件边把控制交给 tools（v2 是按 tool_call 个数 `Send` 并行扇出，每个 Send 的载荷 `ToolCallWithContext{tool_call, state}` 自带上下文，`tool_node.py` 解析之）→ `ToolNode` 执行并回写 `ToolMessage`（走 add_messages 追加）→ tools 完成后路由回 agent → 循环直到 AIMessage 无 tool_calls 才 goto END。
- **tool 错误处理**（`libs/prebuilt/langgraph/prebuilt/tool_node.py`）：`ToolNode(RunnableCallable)` 默认 `handle_tool_errors` 为一可调用对象：捕获"模型调用工具参数非法/工具未注册"类错误，生成 `ToolMessage("Error: … Please fix your mistakes.")`（模板见 `tool_node.py:108-121`，非法工具名提示可用工具清单）**回喂给 LLM 自我修正**而非中断图；`handle_tool_errors=False` 则让异常上抛。工具也可返回 `Command`（改状态/跳转/发消息）实现控制流工具。tools 具 `return_direct` 时 `route_tool_responses` 直接 END（`chat_agent_executor.py:970`）。
- **checkpointer/断点**：透传给 `workflow.compile(checkpointer=…)`；`interrupt_before/after` 取值限定 `["agent","tools"]`（docstring `chat_agent_executor.py:447-454`）——这是给 HITL"工具执行前要人工确认"的官方断点位。
- **prompt/历史**：`prompt` 可为 str/SystemMessage（前置进 messages）或 callable/runnable（对全量 state 处理后接模型）；`pre_model_hook`（可改 `messages` 或只产出 `llm_input_messages` 不落历史，用于裁剪/摘要）、`post_model_hook`（agent 之后加护栏节点，v2 only）；`response_format` → 循环结束后追加 `generate_structured_response` 节点用 `with_structured_output` 出结构化结果，写入 `structured_response` 键。
- **RecursionLimit 的 harness 级消化**：`remaining_steps` 是 `RemainingStepsManager` **managed value**（`libs/langgraph/langgraph/managed/is_last_step.py:18`：`stop - step`，来自 Pregel scratchpad，不进 checkpoint、不占通道）。`call_model` 检测"剩余步数 <2 且响应仍带 tool_calls"→ 返回固定文案 AIMessage 优雅收尾，从而**不触发 GraphRecursionError**（docstring `chat_agent_executor.py:435-440`）。这也是 managed value 机制的典型用途：把"运行上下文派生量"动态注给节点，而非塞进持久化状态。

## 持久化与时间旅行

- **checkpointer 抽象**（独立库，`libs/checkpoint/langgraph/checkpoint/base/__init__.py:177`）：`BaseCheckpointSaver[V]`，必须实现 `get_tuple / put / put_writes / list`（+ async 版），可选 `get_next_version`（每通道单调版本；`InMemorySaver` 用 uuid hex，`memory/__init__.py:613`）。`serde` 负责序列化（`JsonPlusSerializer`/msgpack，`libs/checkpoint/langgraph/checkpoint/serde/`）。
- **数据结构**：`Checkpoint`（TypedDict，`base/__init__.py:93`）= `{v, id(uuid6 单调), ts, channel_values(全通道快照), channel_versions, versions_seen, updated_channels}`；`CheckpointMetadata={source: input|loop|update|fork, step, parents, run_id}`；**写入日志与快照分离**：`put_writes` 单独存每个任务已提交的 writes（含 ERROR/INTERRUPT 控制写），构成"每步快照 + 增量写"双存储，是 replay/fork 的基础。`CheckpointTuple` 携带 `parent_config` 与 `pending_writes`（`base/__init__.py:140`）。
- **寻址**：config 里 `configurable.thread_id`（主键，线程即会话/对话）＋ `checkpoint_ns`（子图命名空间）+ `checkpoint_id`（精确到某个历史点）。生产用 `langgraph-checkpoint-postgres`（`libs/checkpoint-postgres`，`PostgresSaver`），测试/调试用 `InMemorySaver`（docstring 明示仅测试用）。
- **落盘时序**：`_put_checkpoint`（`pregel/_loop.py:1081`）在每超步 after_tick 后执行；`durability` 分 `sync`（落盘后才进下超步）/`async`（默认，与下超步并行跑，靠 `_checkpointer_put_after_previous` 链式 Future 保序）/`exit`（beta，退出才落盘）。无 checkpointer 时内存里同样维护 `Checkpoint`（版本照常推进，仅不持久化）——**Pregel 的调度完全不依赖 checkpointer，持久化只是"顺路"把每超步屏障后的快照写下**。
- **断点与 HITL interrupt**：`compile(interrupt_before=["tools"], …)` 或每次调用传参。判定 `should_interrupt`（`pregel/_algo.py:155`）：`__interrupt__` 伪节点记录的"自上次中断以来是否有通道更新"＋目标节点命中列表。`interrupt()`（`types.py:851`）：节点内首次调用即抛 `GraphInterrupt`（`errors.py:102`，属 `GraphBubbleUp`——超步级"正常暂停"而非失败），其值作为 `(INTERRUPT, …)` 写入该任务的 pending writes 持久化（`pregel/_runner.py:585` commit 分支）；运行以 `{'__interrupt__': (Interrupt(...),)}` 形式在 stream 中吐给客户端。**恢复**：再次 `graph.stream(Command(resume="…"), config)` → `map_command` 产生 `(NULL_TASK_ID, RESUME, v)` pending write → 被中断节点**从节点开头重执行**（文档语义 "re-executing all logic"），`interrupt()` 依 `scratchpad.resume` 的序号取回 resume 值并继续；单节点多次 interrupt 按调用次序匹配（`types.py:866-868`，`interrupt` 实现 `types.py:951-974`）。
- **时间旅行**：`get_state` / `get_state_history(config)`（`pregel/main.py:1392/1480`）沿 parent 链列出全部历史快照；`update_state(config, values, as_node=…)`（`main.py:2515`）从任意历史 checkpoint 创建新分支（`source="fork"`），此后以 `checkpoint_id` 指回旧点的调用就是 **replay**，从 fork 点继续就是**分叉/新时间线**。replay 精确性来自确定性任务 id＋pending writes 重放（`_reapply_writes_to_succeeded_nodes`，`_loop.py:736`：已成功任务直接用其已存 writes，不重执行；失败/中断任务才重跑）。
- 综上，"断点（interrupt_before/after、interrupt()）、时间旅行（get_state_history/update_state/fork）、replay（checkpoint_id）、跨轮记忆（同 thread_id 续跑）"全部建立在"每超步原子 checkpoint"之上。

## 流式与可观测

- `stream_mode`（`types.py:122`）：`values`（每超步后全量状态）/ `updates`（每任务 `{node: 该节点更新}`）/ `messages`（LLM token 级，含 `lc_agent_name` 等元数据，`types.py:289`）/ `custom`（`StreamWriter` 节点内自定义事件）/ `checkpoints` / `tasks` / `debug`；可传 list 多路同时流（如 `astream(stream_mode=["updates","messages"])` 是 harness 调试标配）。emit 逻辑：`after_tick` 内 `map_output_values`（values）与 runner 边收边吐 `map_output_updates`（updates，`pregel/_io.py:100/118`）；messages 模式靠 `StreamMessagesHandler` 拦截模型回调做 token 切片（`pregel/_messages.py`）。1.x 引入 **v3 stream_events**（`stream_events(version="v3")`/`astream_events`，`main.py:3505/3561`，beta）：`StreamMux` 组合 `Values/Messages/Lifecycle/SubgraphTransformer`，返回可驱动 `run.output/interrupted/interrupts` 的类型化投影。
- 输出实现：执行与消费解耦（同步 `queue`/异步，`stream_eager=True` 或 messages/custom 模式会开"waiter"后台线程流），`subgraphs=True` 让嵌套图事件带命名空间冒泡（`CONFIG_KEY_STREAM` + `DuplexStream`）。
- debug：`debug=True` 时流/打印每超步的 `checkpoints`、`tasks`、task 结果（`pregel/debug.py`，`map_debug_*`）。
- **LangSmith 集成**：图 run 全程包在 langchain-core callback manager 里（`on_chain_start/end`），节点以"run"形式进入 LangSmith trace，虚拟节点打 `TAG_HIDDEN="langsmith:hidden"` 标签（`constants.py:26`）以便追踪 UI 隐藏 `__start__`/branch 等内部细节；`metadata`/`tags` 贯穿 config→任务→事件。README 亦把 LangSmith 作为官方调试/评估配套。

## 多 agent 与编排模式

- **Send 扇出/扇入**：上节已述——条件边返回 `list[Send]` 即动态并行；"扇入"靠**共享 state 键的 reducer**（多个并行任务各写 `results: Annotated[list, add]`）或 join 边。典型 map-reduce 示例即 `Send` 的 docstring（`types.py:723-748`）。
- **supervisor / network 模式**：**没有内置原语**——LangGraph 的答案就是"图即模式"：supervisor（路由 agent）与 workers 都是节点，用 `StateGraph` 显式连线（supervisor 节点返回 `Command(goto=…)`/条件边选 worker，worker 完成后回写 supervisor）。官方常把整个 worker 做成 `create_react_agent(...)`/编译图再 `add_node("worker", worker_graph)` 作为**子图节点**。
- **subgraph**：编译后的图是普通 Runnable，可作节点嵌入父图；运行时通过 `find_subgraph_pregel` 自动识别子图（`pregel/_read.py:187-199`，用于嵌套流式与 checkpoint 命名空间）；子图内返回 `Command(graph=Command.PARENT, update=…/goto=…)` 可向父图状态写入/路由（`types.py:848`）。checkpoint 用 `checkpoint_ns`＋`parents` 元数据把父子快照连成树（`base/__init__.py:57`）。
- **另一高层 API（提及）**：`langgraph.func.entrypoint` 函数式 API（`libs/langgraph/langgraph/func/`）用装饰器把普通函数包成 Pregel 图，供偏"脚本式"场景使用；`create_agent`（langchain 包）则是正在接棒 create_react_agent 的新 agent 工厂。

## 关键代码节选与路径总表

| 概念 | 证据位置（相对克隆根） |
|---|---|
| Pregel 类与 BSP 三阶段 docstring | `libs/langgraph/langgraph/pregel/main.py:450-478` |
| BSP 主循环注释与 while loop | `libs/langgraph/langgraph/pregel/main.py:2959-2998` |
| Plan: prepare_next_tasks / PULL 触发判据 | `libs/langgraph/langgraph/pregel/_algo.py:392-513`、`_triggers` |
| Update: apply_writes / 版本递增 | `libs/langgraph/langgraph/pregel/_algo.py:232-345` |
| tick/after_tick 超步推进 | `libs/langgraph/langgraph/pregel/_loop.py:599-726` |
| 并发 runner（线程池+futures） | `libs/langgraph/langgraph/pregel/_runner.py:176-334` |
| 节点/边编译成 branch 隐藏通道 | `libs/langgraph/langgraph/graph/state.py:1444-1624` |
| 状态字段→channel 映射 | `libs/langgraph/langgraph/graph/state.py:1815-1941` |
| add_messages / MessagesState / MessageGraph | `libs/langgraph/langgraph/graph/message.py:60/372/316` |
| BaseChannel 与内建通道 | `libs/langgraph/langgraph/channels/base.py`、`last_value.py`、`topic.py`、`binop.py` |
| Send / Command / interrupt / Overwrite | `libs/langgraph/langgraph/types.py:704/798/851/978` |
| 输入 Command→writes 映射 | `libs/langgraph/langgraph/pregel/_io.py:56-78` |
| checkpointer 抽象与 Checkpoint 结构 | `libs/checkpoint/langgraph/checkpoint/base/__init__.py:93-330` |
| InMemorySaver / PostgresSaver | `libs/checkpoint/langgraph/checkpoint/memory/__init__.py:33`、`libs/checkpoint-postgres/…` |
| interrupt 持久化(commit) 与恢复 | `libs/langgraph/langgraph/pregel/_runner.py:574-613`、`_loop.py:736-846` |
| 时间旅行 API | `libs/langgraph/langgraph/pregel/main.py:1392(get_state)/1480(history)/2515(update_state)` |
| create_react_agent 主循环 | `libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:278-1002` |
| ToolNode 错误自愈模板 | `libs/prebuilt/langgraph/prebuilt/tool_node.py:108-121,622-…` |
| RemainingSteps managed value | `libs/langgraph/langgraph/managed/is_last_step.py:18-24` |
| StreamMode 定义 | `libs/langgraph/langgraph/types.py:122-135` |

**优点**：① 状态与调度高度显式——"通道+reducer+版本"模型同时解决并行确定性、冲突规约与可观测性；② 持久化是一等公民，断点/HITL/时间旅行/replay 是**机制**而非插件；③ BSP 屏障使每一步都是可恢复的原子点，长任务/幂等重试有坚实根基；④ harness（prebuilt）与运行时解耦成独立包，高层工厂上移 langchain 不污染内核；⑤ 流式多级（values/updates/messages/debug）与 LangSmith 集成成熟。

**缺点/注意**：① 概念负载高（channel/reducer/版本/超步/checkpoint 寻址），入门门槛明显高于脚本式 harness；② 状态冗余：整份 channel 快照每超步序列化（Postgres/大状态场景成本需评估，DeltaChannel 即为此做的 beta 优化）；③ 抽象层多，调试需理解"branch:to" 内部通道与隐藏节点；④ main 分支 1.x 处于大规模弃用过渡期（MessageGraph、create_react_agent、config_schema 等），网上 v0.x 教程与当前源码大面积对不上；⑤ 官方文档独立成站，源码仓库内几乎无文档正文。

**与其它 harness 对比启发**（对照本系列 beeai/agno/smolagents/openai-agents）：多数 agent 框架把"agent 循环"写成 `while` 代码+内存会话；LangGraph 则把循环显式化为**图环+每超步快照**，从而换来跨进程续跑、精确回放、HITL 暂停与"任意历史点分叉"这类其它框架需要专门轮子才能实现的能力。它更像"带持久化语义的分布式图执行引擎（BSP）"，而其它 harness 更像"带工具的 LLM 客户端"。代价是：当任务只是单轮工具调用时，LangGraph 的模型（状态 schema、reducer、版本、checkpoint 线程）明显过重——这也解释了生态为何在其上再叠 `create_agent`/Deep Agents 这类高层产物。对本项目（自研 agent harness 研究）的启示：可借鉴"**超步屏障 + 每步快照 + 确定性任务 id**"三元组来获得 durable/可回放执行，但状态可简化为"消息列表 + 每步 append-only 增量"，无需复制其完整 channel/版本体系。
