# Agent Harness 架构研究 · 总览与横向对比

> 研究时间：2026-09-04（当日 GitHub 快照）
> 方法：对每个仓库执行 `git clone --depth 1` 后用源码 + 官方文档精读，结论均附仓库内相对路径证据；不确定项在分册中显式标注"需核实/不确定"。
> 说明：以下 Star 数、版本号为研究当日快照值，项目迭代很快，引用时以具体 commit 为准。

## 研究动机

以 DeepSeek Harness（dsh）为主线，对照当下最热门的开源 agent harness / agent 框架，回答一类问题：**一个现代 agent harness 的主循环、插件化、上下文管理、记忆、多 agent、安全沙箱到底是怎么搭出来的？**

## 文档地图

| 编号 | 仓库 | 分册文档 | 一句话定位 |
|------|------|----------|-----------|
| 01 | deepseek-ai/deepseek-harness | [01-deepseek-harness.md](01-deepseek-harness.md) | "Everything is a Plugin"，Cordis 驱动的通用 agent harness（类 Claude Code），TypeScript |
| 02 | openai/openai-agents-python | [02-openai-agents-sdk.md](02-openai-agents-sdk.md) | OpenAI Agents SDK：轻量通用 agent 编排 + handoffs + guardrails |
| 03 | huggingface/smolagents | [03-smolagents.md](03-smolagents.md) | "极小核心 + 让模型写代码"的 Code-first agent harness |
| 04 | agno-agi/agno | [04-agno.md](04-agno.md) | 生产级全栈框架：Team 编排 + Workflow + 三轨记忆 + 45+ 家模型 |
| 05 | i-am-bee/beeai-framework | [05-beeai-framework.md](05-beeai-framework.md) | IBM 出品：统一 Runnable 抽象 + Memory 策略 + Workflow |
| 06 | langchain-ai/langgraph | [06-langgraph.md](06-langgraph.md) | 图状编排运行时：Pregel 超步执行 + checkpoint / 时间旅行 |

## 横向对比总表

| 维度 | dsh | OpenAI Agents SDK | smolagents | agno | beeai-framework | LangGraph |
|------|-----|-------------------|-----------|------|-----------------|-----------|
| 语言 | TypeScript | Python | Python | Python | TS / Python | Python |
| 仓库形态 | monorepo（~49 个 packages + apps/native/web） | 单包 src/agents + run_internal | 单包 src/smolagents | monorepo libs/agno | python/ + ts/ 双实现 | libs/langgraph + checkpoint/prebuilt |
| 底层运行基座 | Cordis 插件容器（依赖注入/生命周期/服务） | 纯 async 编排 + OTel | 纯 Python 事件循环 | 纯 Python | Runnable/RunContext 横切抽象 | Pregel（BSP 超步）图执行 |
| Agent 主循环 | ReactLoopAgent + turn/step 事件流，host/api/session 驱动 | Runner → run_internal run_loop（turn 状态机 NextStep） | MultiStepAgent._run_stream（model→parse→execute→observe 循环） | Agent.run → Model.response() 内置 while True 工具循环 | Agent.run → RunContext 生命周期 → 具体 agent loop | create_react_agent（图节点 agent→tools→router→END） |
| 行动范式 | 工具调用（tool_calls），动作/事件化 | function calling 自动执行 | CodeAgent 写代码 / ToolCallingAgent 调函数 | function calling | function calling | function calling / 任意图节点 |
| 插件/扩展 | **一等的插件系统**：preset→bundle→patch 组合，dsh-plugin 生态 | 代码级 Agent/工具/生命周期 hook | 工具 + managed_agents + 回调 | 代码级模块 + 生态工具包 | adapter 化 backend/tool | 图组件 + LangChain 生态 |
| MCP | 内置 MCP 包（客户端/服务端） | MCP 工具注入支持 | 间接（走工具） | 支持（工具/知识） | 支持 | 支持（LangChain MCP 工具） |
| 上下文管理 | token-meter + compaction（surface 替换式压缩）+ spill（溢出）+ inject | OpenAIResponsesCompactionSession（≥10 条 compact）+ rollover/截断 | 直接拼消息，无内置压缩 | 会话 summary + 长期记忆 | 消息窗口策略（Unconstrained/Sliding 等） | 图状态天然可裁剪 + checkpoint 历史 |
| 会话持久化 | storage/session + 断点续跑 | session 抽象 + 服务端记忆 | 无内置 | AgentSession + storage(DB) | 序列化（TS 侧，含函数反序列化安全门） | checkpointer（内存/SQLite/Postgres…）+ 时间旅行 |
| 多 Agent | subagent / Agent Teams / workflow | **handoffs（交接）+ triage 路由** | manager agent + managed_agents（委派=伪工具） | Team（leader+members，delegate 工具）与 Workflow（显式步骤） | Workflow + requirement agent | 图/Send 并行/supervisor 模式/子图 |
| 人机交互/审批 | guard + approval（fail-closed） | 工具级 interrupt/审批 | 无内置 | 无内置（社区） | 无内置 | interrupt()/Command(resume) 一等公民 |
| 安全沙箱 | sandbox 包 + code-runtime + 权限审批 | 无沙箱（纯 API 编排） | AST 白名单解释器（明示非沙箱）+ E2B/Docker/Modal 远程沙箱 | 无内置沙箱 | 无内置沙箱 | 无内置沙箱 |
| 可观测性 | 事件流 + 前端可视化 + 遥测 | tracing(OTel/Span) + RunResult | monitor（step 日志/错误计数） | 会话/调试 UI（agno.os） | emitter 事件 + logger | astream 多级 + LangSmith |
| 模型接入 | 模型供应商抽象（llm 包）+ Typert/协议 | 任意 OpenAI 兼容（Model 抽象） | InferenceClientModel / LiteLLM / OpenAI 兼容 | 45+ 厂商 + fallback 链 | backend 抽象多厂商 | 任意 ChatModel（bind_tools） |
| 典型使用面 | 交互式编码/通用 agent（终端+Web） | 生产 API/多 agent 服务 | 轻量研究/教学/单机 demo | 全栈产品（带 UI/storage） | 企业级产品集成 | 复杂有状态编排/平台 |

## 六家精华要点

### 1. DeepSeek Harness（最值得对标）
- 口号即架构：**"Everything is a Plugin"**。宿主本身极薄，能力全部来自 Cordis 服务化插件；通过 `profile/bundle/preset` 组合出不同形态（web、cli、desktop、remote gateway 都是插件/入口组合）。
- 代码走向：`packages/boot`（启动）→ `packages/host`（进程/能力宿主）→ `packages/core`（Agent/Session/事件中枢）→ `packages/llm`（模型）→ `packages/session`（会话驱动），一次交互 = session 内多轮 turn/step，事件流贯穿。
- 上下文处理是专门子系统：token 记账（token-meter）、**compaction（surface 替换式压缩）**、**spill（上下文溢出落到可检索存储）**、`agent.inject`（外部注入上下文）——这正是长任务不断线、费用可控的关键。
- 多 agent 与工具齐备：subagent、Agent Teams、workflow、MCP、skills、LSP、terminal/shell、code-runtime；安全默认 fail-closed（sandbox/approval/guard）。
- 前端与协议：host/api/client 三分，Typert（RPC）+ ACP/SDK/Python 协议，web UI 由 `dsh web` 启动（默认 127.0.0.1:3080）。

### 2. OpenAI Agents SDK
- 结构极简的"编排 harness"：`Agent`（instructions+tools+handoffs+guardrails）与 `Runner.run` 两件套。
- 0.22 起主循环拆分进 `run_internal/run_loop.py`：**turn 状态机**（NextStep：FinalOutput / Handoff / Interruption / RunAgain），`max_turns` 超限抛 MaxTurnsExceeded。
- 多 agent 靠 **handoff**：本质是把"下一个 agent"注册成一个特殊工具，模型决定转交给谁（triage 路由是常见用法）。
- 记忆分两层：context 注入（每次重建）+ session 持久化（可含 `OpenAIResponsesCompactionSession` 自动 compact）。
- 护栏（guardrail）在输入第一轮、输出最后一轮执行，可中断违规流程。

### 3. smolagents
- 反主流设计：与其教模型选工具，不如**让模型写代码**（CodeAgent）：模型输出 Python 代码段，本地解释器执行并把 stdout 喂回模型。
- 主循环在 `src/smolagents/agents.py` 的 `MultiStepAgent`：`model(step)→parse action→execute→observation→memory`，直到 `final_answer`。
- 子代理 = managed_agents，以"伪工具"形式注入，由 manager agent 决定何时委派。
- 安全分级清晰：本地 AST 白名单解释器（官方明示**不是**沙箱）→ E2B / Docker / Modal 远程真沙箱。

### 4. agno
- 全栈产品化：一个 Agent = 记忆（会话 runs + db 型用户长期记忆 + Knowledge 向量库）+ 工具 + 模型，开箱带 storage 与 UI。
- 模型层把"工具多轮循环"下沉到统一基类 `Model.response()`（`models/base.py` 内 while True），上层 Agent 不必重复实现——**循环位置的取舍**很值得学习。
- 多 agent 两套范式：Team（lead agent + 成员 + delegate 工具，动态）与 Workflow（Step/Parallel/Loop/Condition/Router 显式 DAG，可控）。
- 45+ 家模型厂商 + fallback 链，模型换用零改动。

### 5. beeai-framework（IBM）
- 组件高度一致：所有东西（agent/tool/workflow…）都是 `Runnable`，统一 `run() → RunContext` 生命周期（信号、中断、状态），横切一致性好。
- Memory 是显式策略对象（UnconstrainedMemory / SlidingMemory / TokenMemory 等），生产取舍清晰。
- Python 侧主推 RequirementAgent（规则/约束驱动），旧的 ReAct/ToolCalling 已标记弃用；TS 侧才有序列化/断点恢复（含函数反序列化安全门）。
- 正并入 A2A（Agent-to-Agent）协议体系。

### 6. LangGraph
- 不叫"agent 循环"，而是**通用图运行时**：状态 schema 注解 → channel；节点读写通道，边编译为隐藏 branch 通道；执行模型取自 **Pregel/BSP 超步**（Bulk Synchronous Parallel）——每超步可并行跑多个节点，天然支持 fan-out。
- `create_react_agent` 是预置 harness（agent→tools→router 环 + checkpointer + recursion limit）；main 分支已开始把它上移到 `langchain.create_agent` 并标记弃用。
- **checkpoint + interrupt() + 时间旅行** 是其杀手锏：暂停/恢复、断点续跑、replay/分叉，这是其它框架普遍缺的"有状态可恢复 agent"能力。

## 顶层横向洞察（自研 harness 可直接抄的模式）

1. **主循环范式二选一或分层**：绝大多数 = `while turns:` { model → tool_calls → execute → append messages }。写代码/执行环境用"模型写代码"（smolagents），纯 API 编排用 function-calling（其余全部）。可把工具循环下沉到模型抽象层（agno）或独立 run_loop（OpenAI）以复用。
2. **"turn/step" 要建模成状态机 + 事件流**（OpenAI NextStep / dsh turn-step）：便于流式、打断、审批、断点恢复，而不是裸 while。
3. **上下文管理是长会话 harness 的分水岭**：token 记账 + compact + spill + 手动 inject（dsh）；内置自动 compact（OpenAI）；checkpoint 历史即"记忆备份"（LangGraph）。
4. **多 agent 用两套正交机制**：a) handoff/delegate（模型运行时决定转交谁：OpenAI handoff、agno Team、smolagents 委派工具）；b) 确定性 workflow/图（LangGraph、agno Workflow、beeai Workflow）。生产系统通常是 b 包 a。
5. **记忆分层三件套**：会话内消息（短期）+ 用户画像/事实（长期 db）+ 语义知识（向量库）。参考 agno 三轨与 OpenAI session/context 分离。
6. **安全边界要显式**：approval/guard 默认拒绝（dsh fail-closed）、interrupt() 人机交接（LangGraph）、代码执行进真沙箱（smolagents 的教训：本地解释器≠沙箱）。
7. **插件化 = 可组合性**：dsh 的 Cordis 插件 + preset/bundle 组合是"一个核心多形态产品"的答案；非插件系框架靠包级抽象（Runnable/adapter）达到类似效果。
8. **协议化是终局**：ACP/A2A、MCP（工具）、Typert（dsh RPC）——harness 与工具、harness 与 harness 之间用标准协议解耦，才能生态化。
