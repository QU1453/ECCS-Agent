# DeepSeek Harness (dsh) 架构深度分析

> 研究对象：GitHub 官方仓库 `deepseek-ai/deepseek-harness`（默认分支 `master`，TypeScript/Cordis monorepo）。
> 研究方式：`git clone --depth 1` 后基于仓库内真实文档与源码撰写；所有结论尽量给出仓库内相对路径证据；无法确证处标注"需核实"。
> 数据时间点：2026-09-04（克隆当时 master HEAD）。

## 一、概览

**DeepSeek Harness（`dsh`）** 是 DeepSeek AI 开源的 agent harness（智能体框架/运行器），定位上与 Claude Code 一类的"编码/通用 agent 产品"同赛道，但形态是一个可编程、可嵌入的运行时而非单一 CLI：同一内核可以套上 `web`（浏览器 GUI）、`headless`（一次性运行器）、`sdk`（进程外 JSON-RPC SDK）、`acp`（自动化协议服务器）等不同外壳（见 `docs/architecture.zh.md` "Profile 与组合包"一节与 `README.zh.md`）。

GitHub 元数据（经 GitHub REST API 核验，2026-09-04）：仓库创建于 2026-08-13，star 数 **211,400（约 21.1 万）**，fork 24,780，主语言 **TypeScript**，许可证 **MIT**（根目录 `LICENSE`），仓库描述即 **"Everything is a Plugin."**，topic 含 `ai-agents`、`cordis`、`dsh`、`dsh-plugin`。注意：star 数与创建日期变化很快，此处为快照值。

版本与工程信息：根 `package.json` 名为 `@deepseek-ai/dsh-root`，版本 `0.1.3-alpha.1`（`private: true`），包管理器 `pnpm@11.7.0`，要求 Node `^22.19.0 || >=24.0.0`；发布态处于 **开发者预览**（README.zh.md 明示"未来将出现破坏兼容性的变更"）。

两条最核心的产品/技术主张（均出自 `README.zh.md`）：

1. **一切皆插件（Everything is a Plugin）**：产品每一部分都是 Cordis 插件——模型适配器、工具注册表、会话日志，乃至 agent 主循环本身——都可以从配置上整体替换，不存在需要打补丁的"特权内核"（`docs/architecture.zh.md` "Cordis"一节）。
2. **理论依托**：设计论文《A Programming Paradigm for Spatiotemporal Composability》，链接为 `https://arxiv.org/abs/2608.25512`（照 README 原文抄录；论文实际内容未在仓库中展开，**需核实**）。

代码组织特点：以 `@deepseek-ai/dsh-*` 为作用域的 npm 包工作区（`packages/` 下按能力分组，共 49 个组），另有 `vendor/`（vendored 第三方源码，如 Cordis 本体）、`native/`（如 Landlock runner）、`python/`（Python SDK + 打包 `dsh` CLI 的 runtime wheel）、`website/`（文档站）与 `apps/`（CLI、Web 壳）。仓库对文档质量要求极高（`docs/AGENTS.md` 定义分层文档体系与字数预算，`scripts/` 下有大量 `verify-*` 生成物新鲜度门禁），本身就是一份"自举"研究素材。

## 二、仓库形态：Monorepo 目录结构

物理布局（关键路径证据）：

- 根：`README.zh.md`、`SAFETY.zh.md`、`CONTRIBUTING.zh.md`、`AGENTS.md`（仓库级 agent 指令）、`package.json`、`pnpm-workspace.yaml`、`tsconfig*.json`（Host/Client 双 aggregate，见下）、`vitest*.config.ts`、`lefthook.yml`。
- `packages/`：**按能力分组的 npm 包工作区**，布局为 `packages/<组>/<包>/package.json`（workspace glob 为 `"packages/*/*"`）。权威分组表见 `packages/README.zh.md`（节选"包分组"一表，全表 49 行）。
- `apps/`：`cli`（`dsh` 可执行入口，`apps/cli/src/bin.ts`，根脚本 `"dsh": "node --import tsx/esm apps/cli/src/bin.ts"`）、`web`（Vite 前端壳，`index.html` + `vite.config.ts`）。
- `docs/`：分层文档（架构/子系统参考/用户指南/cookbook/postmortem/Agent Notes），其中 `docs/subsystems/*.zh.md` 是与源码生成物交叉校验的子系统语义参考。
- `.agents/`：agent 笔记（决策记录）、skills（如 `dsh-doc`）与模板。
- `native/landlock-run`、`vendor/*`、`python/{sdk,sdk-runtime}`、`scripts/`（构建/门禁脚本，量极大）、`patches/`（pnpm patch，如 `node-pty`）。

**49 个包组职责速查表**（依据 `packages/README.zh.md` 的组表整理，均为原文职责的转述）：

| 组目录 | 职责 |
|---|---|
| `core/` | 产品 API 主干：会话日志、提示词组装、工具注册表、agent 服务与**具体循环**（`agent`、`agent-loop`、`session`、`system-prompt`、`tools`、`scope`） |
| `api/` | Remote BFF 装配与 Typert RPC 网关（`session-controller`、`workspace-controller`、`settings-controller`、`gateway`、`remotes`） |
| `typert/` | 类型图代码生成器、产物加载器、运行时注册表（协议/生成器/loader/registry） |
| `goal/`、`schedule/` | 同会话持久目标；仅限会话内的定时后续（提醒回到原 Session） |
| `plan/` | Plan 协作状态（进入/评审退出流程） |
| `todo/` | 面向模型的 `todo_write` 工具 |
| `feedback/` | 人类反馈采集与命令 |
| `identity/` | 共享匿名用户身份（如遥测） |
| `llm/` | LLM 能力系列：抽象服务 `llm` + 适配器（DeepSeek、pi-ai 等）+ `token-meter` + 重试 |
| `session/` | 持久会话"数据平面"：持久化 seam/JSONL 后端/格式迁移、投影、日志、标题、遥测 |
| `session-query/` | 会话检索：语料库、有界读取、血缘、语义过滤、SQLite FTS |
| `subagent/` | subagent 能力系列：Service Definition + 6 个提供方 + 面向模型工具 |
| `jobs/` | 通用后台任务运行时与 `job_*` 控制工具 |
| `workflow/` | 工作流 seam、worker 线程引擎、`workflow`/`ralph` 工具 |
| `sandbox/` | 进程限制 seam（argv 包装），后端 bwrap/Landlock/Seatbelt/Windows ACL |
| `shell/`、`terminal/`、`subprocess/` | Bash/PowerShell 执行 seam 与后端；持久 PTY；子进程 seam |
| `code-runtime/`、`e2b/` | 代码执行（worker 线程 + PTC mode Consumer）；E2B 远程运行时（POC） |
| `fs/`、`lsp/` | 文件系统 seam/本地实现/工具；LSP seam/stdio 提供方/`lsp` 工具 |
| `web/` | Web 能力系列：seam、搜索/抓取提供方、面向模型的 Web 工具 |
| `attachment/`、`spill/` | 持久附件（内容寻址存储）；工具超大输出 spill 存储 seam |
| `skill/` | skill 能力系列：注册表、本地提供方（`.dsh/skills` 等）、模型目录/加载工具 |
| `compaction/` | 上下文压缩 seam：Service Definition + basic 后端 + 命令 + 工具结果剪枝 |
| `context/` | 模型可见请求上下文（workspace 指令、时间上下文、会话引用等） |
| `preset/` | agent preset：按 `cordis.yml` 在每会话组装 agent |
| `interaction/` | 人机协作：审批/`approval`、权限预设、`commands`、询问用户工具 |
| `guard/` | 循环卫生守卫（重复工具调用提醒 + `tools/execute` 超时强制） |
| `hooks/` | Claude Code/Codex 钩子桥接与线协议库 |
| `extensions/` | 运行时自修改：实时插件/服务检查（inspector）、模型所写 mount/unmount |
| `credentials/`、`settings/`、`storage/`、`workspace/`、`webhook/` | 凭据、用户设置、非会话存储、Workspace 实体、外部事件 webhook |
| `sdk/`、`acp/` | 进程外 SDK（JSON-RPC 协议 + TS 客户端/服务器）；仅自动化的 ACP 服务器 |
| `boot/`、`bundle/` | app bin 启动粘合（`app-boot`）；可安装的 `dsh --profile` 补丁层（`base`/`web-app`/`headless`/`sdk-app`/`sdk-minimal`/`acp-app`） |
| `host/` | GUI Host 半侧：`webserver`、`frontend-static`、`plugin-inventory`、目录选择器等 |
| `client/` | 浏览器半侧：`connection`、`store`、`modules`、slot、大量 `ui-*` 插件 |
| `test-support/`、`runtime-diagnostics/`、`util/`、`experimental/` | 测试基建；运行时不变式；零依赖小工具（`brand` 等）；私有原型 |

补充：`experimental/` 含 `agent-team`（Agent Teams 原型，架构文档称其挂在 `ctx.agentTeams` 上）、`inspector`（`cordis.source.patch.yml` demo，根脚本 `demo:inspector`）等；`host/` 中 `webserver`、`compaction/compaction`、`typert/registry` 三个包同时被 Host/Client 两个 tsconfig aggregate 引用（`docs/development.zh.md`）。

**TypeScript 工程纪律**（`docs/development.zh.md` "TypeScript 项目布局"）：Host 与 Client 是两个互相隔离的 Project Reference aggregate（`tsconfig.host.json` / `tsconfig.client.json`），原因是两侧会对同一 Cordis `Context` 接口以不同服务做声明合并，合并进同一个 `ts.Program` 会冲突；构建顺序固定为 host tsc → host tsdown（此处运行 Typert 生成）→ client tsc → client tsdown → `build:web`。

## 三、插件机制：Cordis 与 profile/bundle/preset

### 3.1 Cordis 基础概念

Cordis 是 dsh 底层插件框架，仓库以 vendor 方式引入（`docs/cordis-primer.zh.md`："Cordis 是 DeepSeek Harness 底层以 vendor 方式引入的插件框架"；源码在 `vendor/`，同步流程见 `vendor/README.md`）。代码中一律以 **`@deepseek-ai/cordis`** 作用域导入（例如 `packages/core/agent-loop/src/index.ts` 首行 `import { Context, FiberState, Service } from '@deepseek-ai/cordis'`）——即上游 `cordiverse/cordis` 被 fork 或重发布到 DeepSeek 作用域，**具体与上游的差异需核实**。`docs/cordis-api/` 下有 context/events/fiber/registry/service 等框架 API 中文参考。

`docs/cordis-primer.zh.md` 归纳五个核心概念：

1. **插件是提供 Service 的对象**（`inject` + `apply(ctx)` 的函数，或 `Service` 子类），挂载到上下文。
2. **上下文（`Context`）是服务的容器**：一个服务占据稳定的 `ctx.<key>`（`ctx.tools`、`ctx.llm`、`ctx.sessions`、`ctx.agents`…），插件按 key 查找，不 import 具体实现。
3. **`inject` 声明依赖**：依赖就绪插件才启动，加载顺序由服务依赖表达。
4. **类型化事件通信**：通过 `declare module` 声明合并注册事件名；分发模式有 `emit` / `waterfall` / `parallel` / `serial` / `bail`（观察、包装/短路、并行、按序、首个值即停）。harness 用 `@mode` 标签记录模式，并有 `verify-scoped-events` 等脚本交叉校验声明与分发点。
5. **注册是可逆副作用**：通过 `ctx.effect()`/`ctx.on()` 安装，热重载与 teardown 自动撤销（disposer 模式）。

waterfall 语义：`ctx.waterfall` 是环绕中间件，监听器收 `(...args, next)`，`next()` 执行下游；不调 `next()` 直接返回即短路（策略监听器"拥有决策权"）。这在 agent 循环里大量用于 `agent/pre-step`、`agent/request`、`tools/*`、`approval/request` 等（详见下文）。

**类型系统层面**两条全仓通用模式（`docs/subsystems/core.zh.md`）：

- **`…Map` → 派生联合类型**：可扩展联合由 `interface ContentBlockMap/SessionEventMap/TurnEndReasonMap/MessageSourceMap/FinishReasonMap` 等以判别标签为键的 map 经 `keyof` 派生，插件用声明合并添加变体而无需改源包。
- **品牌化 ID（Branded id）**：跨包 ID（`SessionId`、`ToolCallId`、`JobId`、`ApprovalRequestId`…）在类型层面不可互换；构造原语 `Branded<B>` 在 `packages/util/brand`（`docs/subsystems/core.zh.md` 引 `packages/util/brand/src/index.ts`）。

### 3.2 组合机制：profile → bundle → patch 树

`docs/architecture.zh.md` "Profile 与组合包"说明运行中的 dsh 是一棵**插件树**，由启动时按序叠放的层构成：

- **profile**：Harness home 中存放的具名组装，列出要叠放的组合包、装用户安装的树外插件、保存用户自己的 `cordis.patch.yml`。随发行版交付 `web`、`headless`、`sdk`、`sdk-minimal`、`acp` 模板。
- **组合包（bundle）**：Cordis 配置项 + 挂载代码的分发格式（配置补丁），其声明在各自 `package.json` 的 `dsh` 字段：`dsh.profile` 列出 profile 的组合包，`dsh.bundle` 指向组合包的 patch 文件。
- 层序：空列表 → 按 profile 顺序的每个 bundle → profile 的 `cordis.patch.yml` → home 级 patch → `--patch` overlay。patch 按 id 定位条目替换整个 config，或插入新条目。`dsh --profile web --dump-config` 可打印整棵配置树，任何条目都可被 patch 替换。
- 共享第一层 `dsh-base`（`packages/bundle/base`）承载模型适配器、工具、持久化、沙箱与审批策略、设置、凭据、遥测；`dsh-web-app` 增加浏览器应用、`dsh-headless` 增加不带服务器的一次性运行器、`dsh-sdk-app` 增加 SDK JSON-RPC 服务器、`dsh-acp-app` 增加纯自动化 ACP 服务器；`dsh-sdk-minimal` 是例外：完整显式配置树且不叠 `dsh-base`。
- **agent preset**（`packages/preset/agent-presets`，服务 `ctx.agentPresets`）：让"某个会话拥有不同能力集合"的机制——每个 preset 是一份 `cordis.yml` 组合（独立服务行可带 `isolate` realm），agent 工厂在 `setup(agentCtx)` 时调用 `ctx.agentPresets.mount(agentCtx, id)` 挂载常驻组合，子 agent 通过 `composeFrom()` 与父 agent **join 同一代组合**（绑定而非重挂载，避免读到中途改写的组合文件）。详见 `docs/subsystems/core.zh.md` 生成区块中 `AgentPresets` 的方法（`list/resolve/mount/composeFrom/recompose/select/…`）。

启动粘合在 `packages/boot/app-boot`（assembly 机制），配置字段全集见生成的 `docs/config-catalog.zh.md`。

## 四、Agent 主循环与运行时

### 4.1 主干包与一次轮次的旅程

`docs/subsystems/core.zh.md` 的"主干逐包速览"给出一条循环流经六个包的路径：

`packages/core/agent-loop` 的 driver 认领排队的提示词 → 在会话日志（`ctx.sessions`，`core/session`）开轮次 → 经 `ctx.systemPrompt`（`core/system-prompt`）组装请求前缀并从日志派生历史 → 经 LLM seam（`ctx.llm`，`llm/llm`）流式取模型响应 → 经工具注册表（`ctx.tools`，`core/tools`）分发工具调用 → 每个模型可见事实追加回日志供下一步派生。

| 包 | 职责 | ctx 键 |
|---|---|---|
| `core/session` | 仅追加 `SessionEvent` 日志 + 内存 store（唯一真源） | `ctx.sessions` |
| `core/system-prompt` | 提示词片段与工具 schema 组装 | `ctx.systemPrompt` |
| `core/tools` | 作用域化工具注册表 + 带把关执行流水线 | `ctx.tools` |
| `core/agent` | `Agent` 接口、活跃 agent 注册表、`agent/*` 事件 | `ctx.agents` |
| `core/agent-loop` | 实现该接口的默认驱动（`ReactLoopAgent`） | `ctx.agentLoop` |
| `core/scope` | 按 agent 划分作用域的注册原语（库，无 ctx 键） | — |

关键源码位置：`packages/core/agent-loop/src/agent.ts` 顶注释即"Default Agent driver over queued turns and step-boundary input. Every request is derived from the session log."，导出类 **`ReactLoopAgent implements Agent`**（内部 `Phase = idle | maintenance | running` 状态机）；`packages/core/agent-loop/src/index.ts` 是具体插件：注册工厂（`setFactory`）、发布 agent/session、注册 `turnBoundaryProjectionDefinition`（`turnBoundary` 投影，用 zod schema 描述 `openTurnStartSeq/lastStepStartSeq/lastTurn…`）并拥有有序 teardown。`Agent` 接口、`AgentRegistry`（`ctx.agents`）在 `packages/core/agent/src/index.ts`，事件词汇在 `packages/core/agent/src/runtime-types.ts`。

### 4.2 轮次/步骤模型与事件流

**步骤（step）** = 一次模型请求 + 它调用的工具；**轮次（turn）** = 零或多个步骤（领取首条输入时开、不再欠任何工作时关）。`docs/architecture.zh.md` "轮次流程"给出规范时序（摘录并整理）：

```text
turn/start
  claim 下一轮输入 + 1 条排队消息
  assemble 提示词片段 + 工具 schema
  -> agent/pre-step（waterfall）    reject 或 enter(messages, startsRequestSeries?)
     step/start
     append user/message
     从日志派生模型历史（deriveMessages）
     agent/request（waterfall）-> llm/stream（waterfall）-> agent/assistant-stream
       chunk* -> assistant/message | assistant/attempt
     tool/call* -> tools/pre-execute -> tools/execute -> tools/post-execute -> tool/result*
     step/end
  还有欠账或有新输入 -> 下一 step
  -> agent/turn-stopping（serial）   可 steer 续跑，否则关轮次
turn/end
```

持久会话事件与三类实时扩展点区分：`turn/*`、`step/*`、`user/message`、`assistant/message`、`assistant/attempt`、`tool/*`、`request/header`、`request/context`、`session/end-seed` 是**持久**的；`agent/*`、`tools/*`、`llm/stream`、`fs/*`、`telemetry/*` 是实时扩展点。waterfall 事件（`agent/pre-step`、`agent/request`、`llm/stream`、`tools/pre-execute|execute|post-execute`）的监听器必须 `next()` 才委托；`agent/turn-stopping` 是 serial。

**Agent 公开句柄**（`Agent` 接口，`packages/core/agent/src/types.ts`，即 `docs/subsystems/core.zh.md` 中 type-equiv 原文）：`id`、`options`、`session`、`inbox`、`status`（`idle|running`）、`ctx`（agent 作用域上下文），方法 `send(target, wakeup)`/`followup`/`steer`/`inject`/`cancel(cause, {keepInbox})`/`runMaintenance`/`whenIdle`。取消原因 `AgentCancelCause = user|parent|hook(reason)|disposed` 会随持久 `turn/end {reason:{kind:'aborted'}}` 落盘。输入投递统一走 **inbox**（`InboxTarget = 'next-turn' | 'next-step'` 两条持久投影的待处理队列）；`agent.inject()` 投注入上下文而不唤醒（等到下一次获准请求）。这构成了"多轮对话、自动继续/打断"的机制基础：唤醒投递 → driver 开轮次 → 排空 → `whenIdle()`；打断 = `cancel` + 保留 inbox（`keepInbox`）→ 再次唤醒续跑。

### 4.3 高层执行模型

除"一问一答"外，仓库将"目标/计划/后台任务/定时"都做成**挂在会话日志之上的小领域插件**：

- **goal**（`packages/goal/goal`，`ctx.goals`）：同会话持久目标。`goal/change` 会话事件是唯一持久权威，CAS 修订（`GoalRef {id, revision}`）、阶段 `active|paused|blocked|complete`，`maxGoalRounds` 封顶续跑轮次；每轮获准的 `user/message` 带 `GoalMessageSource {goalId, revision, round}`（`docs/subsystems/goal.zh.md`）。
- **plan**（`packages/plan`）：协作计划状态，进入即执行命令、经评审退出（`packages/README.zh.md` 组表）。
- **jobs**（`packages/jobs`，`ctx.jobs`）：长任务运行时。`JobKindMap` 目前 `bash|subagent`，`JobStart/JobHooks{run(), cancel(), done, readOutput()}`；`job_*` 工具收集/停止（`docs/subsystems/jobs.zh.md`；架构文档扩展点表："添加后台工作 | 在 `ctx.jobs` 上注册"）。
- **schedule**（`packages/schedule`）：仅限 Session 内的提醒，到期作为普通 follow-up 轮次回到原 live Session；记录为 `schedule/change` 事件，支持 `after`/`at`/`every`（`every_seconds ≥ 300`，无 cron）（`docs/subsystems/schedule.zh.md`）。`docs/user/guide/schedule.zh.md` 为用户指南。
- **webhook**（`packages/webhook`，`ctx.webhookRuntime`）：受信规则认证外部事件 → 创建一次性 Workspace Session（架构文档扩展点表）。
- **Agent Teams / workflow**：`experimental/agent-team`（`ctx.agentTeams`，可继续 subagent 之上提供持久 roster/任务板/mailbox，见 `docs/subsystems/agent-team.zh.md`）；`packages/workflow` 提供 worker 线程工作流引擎与 `workflow`/`ralph` 工具。

## 五、上下文管理：token 记账、compaction、spill

**会话日志即上下文真源**：LLM 历史永远由日志*派生*（`Session.deriveMessages()` / `deriveEventMessage()`，增量缓存 + 深冻结），"模型可见即已记录"是不变量（`docs/subsystems/session.zh.md`；架构文档"会话日志"节）。派生面由 **surface** 机制驱动：只有 `SurfaceEventType`（`user/message`、`assistant/message`、`tool/result`）产生模型消息；每条携带 `SurfaceOp`（`'append'` 或 `{op:'replace',start,end}`）与 `sourceEventSeqs`——这正是 compaction 能"替换历史"而不破坏重建性的根基。

**compaction seam**（可选能力，`docs/subsystems/compaction.zh.md`）：三角色拆分——Service Definition `packages/compaction/compaction`（`ctx.compaction`，`CompactionEngine`）、后端（如 `compaction-basic`）、用户命令 Consumer（`command-compact`）。`compaction/start|summary|end` 三种事件经声明合并进入 `SessionEventMap`，**只写日志不进 surface**；真正的摘要内容由一条带 `surfaceOp replace` 的 `user/message` 携带，遮蔽从 start 到 end 的被替换节点（`shadowedSeqs` 权威列出）。`CompactionTrigger = 'pressure' | 'context-overflow'`（provider 确认溢出时更激进），自动压缩在 `agent/pre-step` waterfall 里先行；`compactNow()` 作为轮次间 maintenance 运行；`compactRegion()` 要求工具调用/结果配对平衡（`toolPairingBalancedBefore/After`）。工具结果剪枝 `ctx.toolResultPruner`（`compaction-tool-result-pruner`）可先把超大工具结果确定性剪到预算内。manual 失败码 `busy|cancelled|changed|summary|commit|persistence`。

**spill seam**（`docs/subsystems/spill.zh.md`）：`ctx.spillStore.saveText()`（`packages/spill/spill`）把超限纯文本结果持久化为**会话作用域私有文件**（本地后端 `spill-local` 写入 `<root>/session-<sha256>/<random>-<safeName>`，0700/0600、`open(path,'wx')` 防符号链接预植），返回不透明 `SpillLocator` + `retrievalHint`；策略 `spill-policy` 挂 `tools/post-execute`，把超过 `maxInlineBytes` 的文本替换为"首尾预览 + spill 引用"。token 估算与回放统一归 **`ctx.tokenMeter`**（`packages/llm/token-meter`，`docs/subsystems/token-meter.zh.md`）所有，compaction 只消费其测量。

**运行时上下文快照**：审批策略等状态变化会作为带来源的 `user/message`（`ContextForm`：`instructions|catalog|snapshot|notice|relay|recall`）追加进历史——"上下文"本身也是日志的一部分（`docs/subsystems/approval.zh.md`、`docs/subsystems/llm-streaming.zh.md` 的 `ContextForm` 词表）。`request/header` 事件把调用配置+系统提示词+工具 schema 的完整 `EpochHeader` 写入日志，使"每个对话请求都是日志的纯函数"（可重建性）。请求头变化（改模型等）记为 `'change'` 并可 `startsSeries` 开启新消息序列。

说明：任务描述提到的 "context-vista 之类插件依赖的上下文 API"——仓库 `packages/context` 组目前只含 `session-reference` 等少量包（组表职责："模型可见请求上下文：workspace 指令、时间上下文、引用"），**未发现名为 context-vista 的包（Glob `**/*vista*` 无结果）；是否指仓库外第三方 dsh 插件，需核实**。模型可见上下文的主要编程入口是 `agent.inject()`（`docs/architecture.zh.md` 扩展点表："添加模型可见上下文 | 调用 `agent.inject()`"）。

## 六、工具与能力扩展

**工具注册与执行流水线**（`docs/subsystems/tools.zh.md`；源码 `packages/core/tools/src/index.ts`、`schema.ts`、`presentation.ts`）：`ToolDefinition` = 面向模型的 `ToolSchema`（name/description/parameters）+ **强制规范输出声明 `output`**（`schema: JsonSchemaNode` + `render` + 可选 `presentationMeta`）+ `execute(args, exec)` + 可选 `finalizeContent/timeoutMs/isConcurrencySafe/presentCall/presentResult`。作者用 **`defineTool` DSL** 声明参数/输出（`ValueSchemaSpec`/`ParameterSchemaSpec`，类型推断 `InferValue`/`InferArgs`，字面量约束 16 层后回退 `JsonValue`），校验经 `parameterSchemaSpecToJsonSchema()` + `validateArgs()`，错误为 `ToolArgsError(INVALID_ARGS)`/`ToolOutputError(INVALID_TOOL_OUTPUT)`。执行管线：`tools/pre-execute`（allow/deny/ask waterfall）→ 单调 `ToolGuard`（只能拒绝不能放行）→ `tools/execute` 环绕分派包装（可换 signal 不可去 signal）→ `tools/post-execute` → `finalizeContent` → `tools/result`。`ToolExecutionMode = parallel|exclusive`（并发安全工具滚动池并行、其余成屏障串行）；`ToolRunContext.deferContext()/concludeTurn()` 支持组合工具转运上下文与"本结果终结本轮"。作用域化：`ToolRestriction {allow,deny}` 过滤**继承**的工具，`tools.restrict()` 用于子 agent 能力裁剪（"可见性而非权限"）。

**能力 seam 思想**（架构文档"能力 seam"节）：一项可替换能力 = Service Definition（接口）+ Service Provider（实现）+ Consumer（多为面向模型的工具）。替换提供方即改变整个产品——如把 fs/进程提供方指向远程沙箱，Bash、PTY、LSP 一并"搬过去"。

**MCP**（`packages/mcp/README.zh.md`）：唯一包 `mcp/mcp-client`——把外部 MCP **工具服务器**（文件系统、GitHub、DB、记忆服务器）挂载进来，工具以服务器限定名当原生工具用；默认不启用任何服务器；**只桥接 Tools，不支持 MCP resources/prompts**。自动重连、单次中断尝试预算等见 `.agents/notes/…/2026-08-06-mcp-client-auto-reconnect.zh.md`；第三方记忆 MCP 的 overlay 示例见 `docs/user/guide/mcp-memory.zh.md`。

**Skills**（`docs/subsystems/skills.zh.md`）：`ctx.skills` 注册表合并各提供方（本地 `dsh-skill-filesystem`、随包 `dsh-skill-badge`、运行时可注册）；Consumer 是模型目录 + `skill` 工具。本地发现 rank 顺序：`<projectRoot>/.dsh/skills`(100) < `.agents/skills`(200) < `Config.customSkillDirs`(300) < `<dshHome>/skills`(400) < `<agentsHome>/skills`(500) < bundled(600)；名字 kebab-case，接受 `<name>/SKILL.md` 目录或 `<name>.md` 平铺。调用策略规范化 `SkillInvocationPolicy {modelInvocable, userInvocable}`（frontmatter `disable-model-invocation`/`user-invocable`）。skill 是**可选指令**（读进来成为上下文），不是会话事件。

**其他执行能力**：shell（`ctx.shell` 后端：bash-local/pwsh-local + 沙箱版 + 持久工具 `tool-bash-persistent`）；terminal（持久 PTY，`ctx.terminals`）；subprocess（`ctx.subprocess` 本地进程树）；code-runtime（worker 线程 + PTC mode Consumer：模型可在程序内直接调度原生工具名；`tools/ptc-dispatch-log` waterfall 可改写落盘副本）；LSP（`ctx.lsp` seam + stdio 提供方 + `lsp` 工具）；web 组（搜索/抓取）；fs 组（`tool-fs`、`str-replace-editor`、`tool-fs-search` + 观测策略）；todo（`todo_write`）；hooks 组（Claude Code/Codex 钩子桥接，`hook/invoked`-`hook/result` 对）。内置工具的权威枚举是生成的 `docs/tool-catalog.md/zh.md`。

## 七、子 agent 与多 agent

`docs/subsystems/subagent.zh.md`：subagent 是**可选能力 seam**，与其他 seam 不同点在于**同一上下文允许多个提供方按名共存**（`ctx.subagents` 注册表，仿 LLM 适配器注册表而非单例执行器）。六兄弟提供方：`subagent-spawn-in-process`、`subagent-fork-in-process`、`subagent-acp`、`subagent-codex`、`subagent-claude-code`、`subagent-dsh-sdk`；Consumer：`tool-subagent`（按提供方委派）、`tool-subagent-control`（可选 `send_message`/`interrupt_agent`/`list_agents`）。

- **一次性（one-shot）**：`SubagentProvider.start()`，能力 flag 先行检查（`agentOptions/outputSchema/depthLimit/toolFilter/persona`），"fail loud, no silent degradation"；支持 `outputSchema` 结构化回传、`maxDepth` 委派深度上限、工具过滤（子 agent 作用域 `tools.restrict()`）、persona 遮蔽。
- **可继续（continuable）后台 subagent**：持久子会话 + 至多一个进程内 **Activation**（驻留期）。管理者负责准入/直接父级鉴权/冷恢复/子级优先释放；Agent inbox 是唯一 FIFO 队列，所有消息走 `Agent.steer()`；`sendMessage()` 只允许"直接 parent ↔ 直接 child"，权限来自**确切在线 sender**（`AgentMessageSource{kind:'agent-message'}`）；`interrupt()` 是唯一公开停止（`Agent.cancel(cause,{keepInbox:true})`）。冷恢复直接 `ctx.agents.resume()` 且不经提供方。持久枚举 `listChildren()/listDescendants()` 从 session header（`origin:'subagent'`）+ 投影折叠，**绝不加载/恢复 Agent**。
- 子 agent 继承父能力靠 preset `composeFrom(agentCtx, parentCtx)` **join 同一代组合**（见 §3.2）。

**多 agent**：进程外委派经 ACP/Codex/Claude Code/SDK 提供方；实验性 **Agent Teams**（`packages/experimental/agent-team`，私有显式启用，`ctx.agentTeams`）在可继续 subagent 之上提供持久 roster/任务板/mailbox（`docs/subsystems/agent-team.zh.md`）。fork 会话原语 `ctx.sessions.fork()` / `ctx.agents.create({..., meta:{parentSession, seedLength}})`,仅在轮次边界 fork（`docs/architecture.zh.md` 扩展点表；`docs/subsystems/session.zh.md` "活跃会话 fork API"）。

## 八、安全模型

四层相互正交的机制：

1. **进程沙箱**（`docs/subsystems/sandbox.zh.md`；`packages/sandbox/{sandbox,sandbox-local,sandbox-policy}`）：`SandboxMode = read-only | workspace-write | danger-full-access`（只管制文件系统效果）；`ctx.sandbox.confine(argv, policy)` 返回**包装后的 argv** 与 `SandboxEnforcement = full|partial`（旧 Landlock ABI / Windows ACL 缺口 → partial，要求绝对边界的消费方必须拒绝）；fail-closed——受限策略下静默无隔离透传不合法（`SandboxUnavailableError SANDBOX_UNAVAILABLE`）。后端：Linux bwrap/Landlock、macOS Seatbelt、Windows ACL 受限令牌；denial 方言（EROFS/EACCES/EPERM）与 runner 失败分类由 `ConfinedArgv` 携带。策略解析 `ctx.sandboxPolicy.resolve()` 按"显式批准模式 > 会话日志 `sandbox/mode` 事件 > 部署默认"取优先级。
2. **工具把关 + 用户审批**（`docs/subsystems/tools.zh.md`、`approval.zh.md`；`packages/interaction/user-approval`）：`tools/pre-execute` waterfall 的 allow/deny/**ask** 与单调 `ToolGuard` 构成"执行前审批"；`ctx.approval.request()` 要求轮次内，追加 `approval/asked`+`approval/decided` 审计对（只进日志不进模型 transcript），结果封闭 `allowed-once|rejected|cancelled|unavailable`，除 `allowed-once` 外一律拒绝（fail-closed on unavailable）。会话策略 `ApprovalPolicy = ask|never`（never = 无头 CI 姿态，确定性拒绝）；ACP 自动化桥接为其拥有的 agent 提供一次性机器决策；`approval/request` 是 waterfall，第一个应答者占用唯一决策槽。**权限预设**（`interaction/permission-presets`）把批准策略与沙箱模式组合成可复用预设供 UI 选择。
3. **文件系统 seam/观测策略**：fs 访问与策略走 `ctx.fs` 提供方 + `fs/*` 事件（架构文档扩展点表）；`fs-observation-policy` 决定工具看到什么。
4. **守卫与卫生**：`packages/guard`（组表："循环卫生守卫：建议性重复调用提醒 + `tools/execute` 截止时间强制执行器"——即 `repeat-tool-reminder` 与 `timeout-policy`；后者实现 `ToolDefinition.timeoutMs` 的执行时限）。工具并发安全声明（`isConcurrencySafe`）限定哪些可并行。另：spill 本地文件用 0700/0600+`wx` 防符号链接（§5）；凭据 `credentials` 组与环境变量优先 `.env`；settings 传输侧强制 `redactSecrets`（见下节 UI 条目）；`SAFETY.zh.md` 是面向运行者的安全说明（README 要求运行前阅读）。

## 九、前端与协议：host/api/client 三分与 Typert RPC

仓库把 GUI 拆成 **host（宿主进程服务）/ client（浏览器应用）/ api（BFF Remote 层）** 三侧，通信协议分两层：

**A. Remote 一元调用层（Typert API Gateway）**（`docs/api-gateway.zh.md`）：业务服务用 `@Remote`/`@RemoteScope` 装饰器声明可对 client 开放的方法；构建期 **Typert generator**（`packages/typert/*`）以 Host `ts.Program` 为种子做严格类型图分析并生成 `lib/typert.host.*` 与 `lib/typert.remote-client.*`（含运行时 codec、声明合并与 sourcemap）。运行时：Host 侧 `ctx.typertGateway`（`api/gateway`）认领 `/api/<namespace>/<method>` 端点，校验参数/返回值，经 `TypertLookupMap`（如 `agent`→`agentId` 的 wire 解析）把 id 解析为 Host 对象后调用**实时 Cordis 服务**；Client 侧 `ctx.remote.<namespace>`（`client/connection` + `api/remotes` 装配）生成具体函数对象（**非 Proxy**），`agentCtx.remote.<namespace>` 为按 agent 作用域调用。Connection 统一做 Host/Origin 校验、RPC id、响应 envelope 与取消（`connection.rpc.call('/api', …)`）；`@Remote` 方法支持协作式取消（末尾 `signal: AbortSignal`）与 `{mode:'stream'}` 流式。分派示例：`api/session-controller`（`ctx.sessionController`，Remote `create/list/search/prompt/cancel/fork/rename/follow/control/attachment/modelCatalog…`，见 `docs/subsystems/session.zh.md` 生成区块）。开发期有 SRC 回退（源码运行时从函数签名弱推断），Client 永远只用严格 codec。

**B. 事件/流层**：持久 `session/event` + 实时 `agent/assistant-stream`（进程本地 start/chunk/end frame；Web 的 Session-follow adapter 是其唯一远程消费方，架构文档"轮次流程"节）。`ctx.sessionController.follow()` 返回"完整 opening 快照 + 无缺口持久事件帧 + 可选 assistant-stream 帧"。数据协议（增量投影、分页、实体子流）不走 Remote，复用 Connection 的精确 Fetch/SSE 路由注册（`docs/api-gateway.zh.md` "边界"节）。

**Host 侧**：`host/webserver`（`ctx.webServer`，`node:http`，named route + fallback 席位 + gzip + index 注入；只服务浏览器，Electron 走 `file://`+IPC）；`host/frontend-static`（SPA dist 服务器，Connection 认证先于读 index.html，非 index 资产公开）；`api/settings-controller`、`workspace-controller`、`session-controller`；目录选择器（native/browse）。`host` 组表："web GUI 宿主半侧：API 网关 + HTTP 路由服务器"。

**Client 侧**（浏览器）：`client/connection`（RPC carrier、信任边界、`/api` HTTP bridge）、`client/store`、`client/modules`（启动 manifest）、slot 系统与大量 `ui-*` 插件（`ui-chat`、`ui-session`、`ui-tool`、`ui-approval`、`ui-settings*`、`ui-goal`、`ui-jobs`、`ui-schedule`、`ui-skill`、`ui-subagent`、`ui-plan`、`ui-trajectory`、`ui-renderer`…）；Conversation 子系统（`docs/subsystems/conversation.zh.md`）把事件流组装成 Chat 节点（每事件族须携带稳定业务 id）。`apps/web` 是 Vite 壳；`packages/bundle/web-app` 组装整个 Web profile。设置 UI 经 `settings` seam 的 `describe()` 渲染 schema 表单，对外传输必须 `redactSecrets`（从三层剥 `role('secret')` 字段并枚举 slot，页面只渲染只写输入框，永不收到机密值——`docs/subsystems/settings.zh.md`）。

**进程外协议**：`sdk` 组（JSON-RPC 协议 + TS client/server，profile `sdk`/`sdk-minimal`）；`acp` 组（**仅自动化**的 Agent Client Protocol 服务器，JSON-RPC stdio，支持建/列/恢复/关会话、挂载 MCP、发图/文提示、语义更新、应答审批、取消；`docs/postmortem/0001-acp-default-export-drops-inject.zh.md` 等反映其演进）；Python SDK（`python/sdk`，`python/sdk-runtime` 把 `dsh` CLI 打包成 `deepseek-harness-sdk-runtime-<platform>-<arch>` wheel，客户端默认 `dsh --profile sdk` 显式 Harness home 启动——`docs/architecture.zh.md` "应用启动"节）。`subagent-acp`/`subagent-dsh-sdk` 让 dsh 自身当这些服务器的客户端。

## 十、关键文件/代码节选（真实相对路径 + 符号）

| 关注点 | 证据路径 / 符号 |
|---|---|
| 默认 agent 驱动类 | `packages/core/agent-loop/src/agent.ts`：`export class ReactLoopAgent implements Agent`；`Phase = idle\|maintenance\|running`；"Every request is derived from the session log." |
| 循环插件/工厂/投影 | `packages/core/agent-loop/src/index.ts`：注册 `AgentFactory`；`turnBoundaryProjectionDefinition = { key:'turnBoundary', stateVersion:2, … apply: (state,event)=>… switch(event.type) case 'turn/start'… }` |
| Agent 接口与注册表 | `packages/core/agent/src/types.ts`（`Agent`/`InboxTarget`/`AgentCancelCause`）、`packages/core/agent/src/index.ts`（`ctx.agents`：`setFactory/create/resume/register/enter/announce/get/roots/withInitiator/currentInitiator`）、`runtime-types.ts`（`agent/pre-step`、`agent/request`、`agent/assistant-stream` 等事件 payload） |
| Session 事件溯源 | `packages/core/session/src/types.ts`（`SessionEventMap`/`SurfaceEventType`/`SurfaceOp`）、`Session` 类（`append/deriveMessages/deriveEventMessage/snapshotEvents`）、`packages/core/session/src/index.ts`（`ctx.sessions.create/prepare/enter/announce/flush/fork`） |
| LLM 服务 | `packages/llm/llm/src/index.ts`：`LlmRuntime`（waterfall 环绕每次流式调用）+ 抽象 `LlmAdapter` + `BlockAssembler`；`declare module '@deepseek-ai/cordis' { interface Context { llm: LlmRuntime } }` |
| 工具流水线 | `packages/core/tools/src/index.ts`、`schema.ts`、`presentation.ts`、`ptc.ts`（`ToolDefinition`、`defineTool`、`ToolExecution`、`ToolGuard`、`ToolExecutionMode`、`PtcDispatchLog`） |
| 系统提示词组装 | `packages/core/system-prompt/src/index.ts`；调用侧 `packages/core/agent-loop/src/agent.ts` 里 `joinContextSections/renderContextSections/renderPrompt`、`assembleContextFor`（dsh-agent） |
| 作用域 | `packages/core/scope/src/index.ts`（`createScope/scopeOf/scopeTarget`，library，无 ctx 键） |
| 压缩/剪枝/spill | `packages/compaction/compaction/src/index.ts`（`ctx.compaction` 抽象 `CompactionEngine`）、`packages/compaction/compaction-tool-result-pruner/src/index.ts`（`ctx.toolResultPruner`）、`packages/spill/spill/src/index.ts`（`ctx.spillStore.saveText`） |
| 子 agent | `packages/subagent/subagent/src/index.ts`、`types.ts`、`continuation.ts`、`descriptor.ts`；提供方在 `packages/subagent/*` |
| 审批/权限 | `packages/interaction/user-approval/src/index.ts`（`ctx.approval.request`）、`types.ts`（`ApprovalOutcome`/`ApprovalPolicy`）；权限预设 `packages/interaction/permission-presets` |
| 沙箱 | `packages/sandbox/sandbox/src/index.ts`（`ctx.sandbox.confine`）、`sandbox-policy/src/index.ts`（`ctx.sandboxPolicy.resolve`）、`sandbox-local`（bwrap/Landlock/Seatbelt/ACL） |
| Settings/credentials | `packages/settings/settings/src/index.ts`（`SettingsScope.get/watch/update/replace/describe`）；`packages/credentials/*` |
| 远程 API | `docs/api-gateway.zh.md` + `packages/api/gateway`（`ctx.typertGateway`）、`api/session-controller`、`api/remotes`（client 装配 `ctx.remote.$mount()`）、`client/connection`（RPC carrier） |
| Web 载体 | `packages/host/webserver/src/index.ts`（`ctx.webServer.register/registerUpgrade/registerFallback/tapIndex/renderIndex`）、`host/frontend-static` |
| 启动/组合 | 根 `package.json`（`"dsh": "node --import tsx/esm apps/cli/src/bin.ts"`）、`packages/boot/app-boot`、`packages/bundle/{base,web-app,headless,sdk-app,sdk-minimal,acp-app}`、`packages/preset/agent-presets`（`ctx.agentPresets`） |

节选一（driver 状态，`packages/core/agent-loop/src/agent.ts`）——真实代码语义：每个 agent 的循环在 `idle / maintenance / running` 三态间迁移；`running` 态持有 `abort: AbortController` + `turn/step` 计数，说明"一次唤醒可跨越多个排队轮次排空"；预准备类型 `PreparedStep = reject | enter{messages, startsRequestSeries, assembly: PromptAssembly}` 对应 pre-step 决策。

节选二（事件即扩展点，`docs/architecture.zh.md` 的事件分类表）：持久会话事件 ↔ `agent/*` 实时事件 ↔ 能力事件（`fs/*`、`tools/*`、`telemetry/*`）三层分工——扩展者先选对"域"，再看 `event-producer-consumer.zh.md` 决定生产/消费位置。

## 十一、优缺点与启发

**优点**

1. **可替换性彻底**：agent 循环自身是插件（`ctx.agentLoop`/`AgentFactory`），扩展插件只依赖 `dsh-agent` 接口而"绝不依赖 agent-loop"（`docs/subsystems/core.zh.md`）；文件系统/进程提供方指向远程沙箱即可把 bash/PTY/LSP 全部迁移——"seam"抽象收益显著。
2. **事件溯源 + 可重建性纪律**：模型历史永远是日志投影，"模型可见即已记录"，且 `assistant/message` 内嵌紧凑带时间戳流、`request/header` 记录完整 EpochHeader——由此天然获得 fork/resume/transcript/重放/崩溃恢复（`interrupted` 轮次关闭器）等能力，比"另存 messages 数组"的方案严谨得多。
3. **文档-源码生成闭环**：子系统页面的类型块与源码类型用 `verify-type-equiv` 防漂移、Cordis 目录/工具目录/配置目录由生成器产出并有 CI 新鲜度门禁；这份文档体系本身可作为工程样板。
4. **工程纪律强**：branded id、`…Map→派生联合`、waterfall/单调 guard、fail-closed（沙箱不可静默透传、审批 unavailable 即拒绝）、声明合并免改源包——类型系统深度参与架构。
5. 上下文管理做成**可选 seam**（compaction/spill 都不进主循环），主循环保持小而稳；同时自动压测与 provider 溢出信号（`context-overflow`）联动。

**缺点 / 代价**

1. 概念与包数量庞大（49 组、150+ 包），"一切皆插件"带来陡峭学习曲线与事件流调试难度；许多语义以"Agent Note"沉淀在 `.agents/notes/`，对新手入口不友好（虽然对 agent 友好）。
2. Cordis 以 vendor/fork 形式引入并重发布为 `@deepseek-ai/cordis`，与上游的关系、升级路径不透明（需核实）。
3. 事件溯源 + 严格 surface 的重建不变量使任何"新增模型可见输入"都要新增事件类型并写渲染规则，扩展成本前置。
4. 仍处 alpha/开发者预览（`0.1.3-alpha.1`），破坏性变更被明示预期；一次轮次的开销/运行时资源占用（多进程、持久化、热重载 watcher）未见基准（`BENCHMARK.md` 存在，未深入）。

**启发（对其他 agent 框架/编码 agent 的借鉴点）**

- 把"循环"做成可替换服务，把产品差异（web/headless/sdk/acp）收敛为**配置补丁层叠**而不是多套可执行文件；用 `--dump-config` 暴露整棵可 patch 配置树。
- 会话日志作为唯一真源 + surface 替换原语，是"压缩、续跑、分支、审计"都能自洽的关键设计（compaction 只追加事件、用 replace op 遮蔽旧节点）。
- 审批/权限/沙箱全部 fail-closed，策略（never/ask）与审计落盘进日志，天然可复现。
- 权限类判断全部收敛为"确切在线对象"（`withInitiator`、sender 鉴权），同进程环境值不作为授权依据——防御性强。
- 跨语言/跨产品互操作采用标准协议（MCP Tools 子集、ACP、Claude Code/Codex hooks、JSON-RPC SDK、Python wheel 打包 CLI），把自己做成"可被其他 agent 驱动"与"能驱动其他 agent"的双向节点。

（附：本文所引 star 数/创建时间来自 GitHub REST API 2026-09-04 快照；仓库仍处快速迭代，阅读时请以最新 master 为准。）
