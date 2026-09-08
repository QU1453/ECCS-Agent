# 计划：智能体调试后台（遥测 Trace 面板）v2

## 概述

新增一个**独立调试后台页面**（`/debug`），记录并展示每次智能体运行的完整遥测数据：用了哪些工具、各阶段耗时、token 消耗、路由/兜底/约束拦截情况。目的：**便于调试和修改智能体**（定位"为什么路由错了/工具没被调用/token 为什么这么高"）。

数据**SQLite 持久化**（`core/telemetry/data/telemetry.sqlite`，见 .gitignore 增补），记录范围为**全量**（每轮问答一条 trace + 若干事件）。

> v2 修订（自查优化）：
> ① 补齐"LLM 模式工具调用如何写入 events 表"的闭环（v1 只说提取 `_telemetry`，没说谁落库——排行图会没数据）；
> ② 兜底模式的工具使用从 `result.data.type` 推断记录（v1 完全缺失，兜底链路调试看不到工具）；
> ③ 新增「会话 token 趋势」折线图——逐轮 input_tokens 是诊断记忆上下文膨胀的核心指标；
> ④ 遥测库移到 `core/telemetry/data/`（语义归位，.gitignore 增补一行）；
> ⑤ 新增清空遥测接口（调试期防库膨胀）；
> ⑥ events/traces 加索引；error/detail 截断放宽；`_telemetry` 剥离时机明确到 `wrap()` 之前。

---

## 业界参考（GitHub 调研结论）

用 GitHub 插件调研了 OpenInference（Arize-ai，LLM 智能体追踪的事实标准）与 LangSmith 的字段设计，映射到本项目：

| OpenInference 标准字段 | 本项目采用 | 来源 |
| --- | --- | --- |
| `llm.token_count.prompt / completion / total` | `input_tokens / output_tokens / total_tokens` | AIMessage.usage_metadata |
| `llm.model_name` | `model` | config.MODEL_ID / agent |
| `openinference.span.kind = LLM / TOOL / CHAIN` | 事件 kind：`stage / llm / tool / constraint` | 编排器/注册表埋点 |
| `tool.name / tool.parameters / tool_call.function.arguments` | 事件 name + params_json | LangGraph tool_calls / GLOBAL_REGISTRY.call |
| `input.value / output.value` | question / reply_snippet（截断） | 编排器 |
| `session.id`（trace 分组） | `session_id + trace_id` | 会话体系 |
| `llm.finish_reason / error` | `status`（ok/error/deny/fallback） | 各阶段结果 |

**我们的项目特有、必须额外记录的**（调试本项目智能体专用）：
- `route`（supervisor 规则路由结果：research/listing/customer_service/presales/constraint）
- `llm_mode`（llm / fallback / constraint_denied —— 本项目双保险链路的核心调试信息）
- 约束层拦截原因（redline / repeat_question / rate_limited…）
- 上下文组装的 token 估算（`assemble_context` 已产出 `estimated_tokens`）

---

## 现状分析（Phase 1 探索结论）

1. **审计已有但不含 token/耗时**：[memory/access.py](file:///workspace/memory/access.py) 的 `AuditLogger` 记 `ts/actor/actor_level/action/module/session_id/result`，存 `memory/data/access.sqlite`。可作为遥测库的实现范本（连接管理、WAL、try 容错模式），但**不复用该表**（语义不同：审计=权限，遥测=调试）。
2. **LLM usage 可获取**：[agents/base.py](file:///workspace/agents/base.py) 的 `answer()` 里 `result["messages"]` 每条 AIMessage 自带 `usage_metadata`（input_tokens/output_tokens/total_tokens，langchain-openai 标准字段），`tool_calls`（工具名+参数）也在消息里——`_format_result` 已经在遍历这些消息提取卡片，同一处顺手提取遥测数据，**零额外开销**。
3. **工具调用两路互补**：
   - LLM 模式：`self.tools`（原始函数）直接传给 `create_react_agent`，工具在 LangGraph 内部执行，**不经过** `GLOBAL_REGISTRY.call` → 只能从 `tool_calls` 消息提取；
   - 兜底/跨模块模式：`GLOBAL_REGISTRY.call` 与 classic 回复函数直接调工具 → registry 埋点 + `data.type` 推断。
4. **埋点主入口**：[core/dispatch/orchestrator.py](file:///workspace/core/dispatch/orchestrator.py) 的 `answer()` 流水线（约束 pre_check → 路由 → 上下文组装 → LLM/兜底 → 约束 post_check）天然是 trace 的骨架，各阶段计时即可。
5. **前端挂载**：[server.py](file:///workspace/server.py) 用 `StaticFiles` 托管 `ui/`（`/ui` 前缀 + 根路径 html=True），新增 `/debug` 页面挂载方式完全同构。ui/ 现有 index.html/app.js/style.css 为原生 HTML/JS，无框架。
6. **无既有遥测代码**：无 /api/telemetry、无 tracing 相关实现。

---

## 实施方案

### 新增文件

#### 1. `core/telemetry/__init__.py` + `core/telemetry/recorder.py`（遥测记录器）

```
TelemetryRecorder（进程级单例 get_recorder()，旁路容错：任何异常不抛出、不影响主链路）
```

- **存储**：`core/telemetry/data/telemetry.sqlite`，WAL，`check_same_thread=False`（照抄 AuditLogger 模式）
- **表结构**：
  - `traces`：`id INTEGER PK, ts TEXT, session_id TEXT, user_id TEXT, route TEXT, agent TEXT, intent TEXT, question TEXT(截断500), reply_snippet TEXT(截断500), llm_mode TEXT(llm/fallback/constraint), status TEXT(ok/error), latency_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, tokens_source TEXT(api/estimated/none), context_tokens INTEGER(上下文组装估算), error TEXT(截断500)`
    - 索引：`idx_traces_session(session_id)`、`idx_traces_ts(ts)`
  - `events`：`id INTEGER PK, trace_id INTEGER FK, seq INTEGER, ts TEXT, kind TEXT(stage/llm/tool/constraint), name TEXT, params_json TEXT(截断800), status TEXT(ok/error/deny), duration_ms INTEGER, detail TEXT(截断300)`
    - 索引：`idx_events_trace(trace_id)`
- **写入 API**（fail-open：内部 try 吞异常）：
  - `start_trace(session_id, user_id, question) -> trace_id`
  - `add_event(trace_id, kind, name, params=None, status="ok", duration_ms=None, detail=None)`
  - `close_trace(trace_id, **fields)`（补 route/intent/reply/tokens/latency/status/error）
  - `set_tokens(trace_id, input_tokens, output_tokens, source)`
  - `clear()`（清空两表，面板"清空数据"按钮用）
- **查询 API**：
  - `list_traces(limit=50, session_id=None, route=None)`（倒序）
  - `get_trace(trace_id)`（含事件，按 seq 排序）
  - `summary()`（SQL 聚合：按工具的调用次数/平均耗时、按 route×llm_mode 的分布、token 总量、兜底率、约束拦截数、平均 latency、最近 5 条 error）
- **尺寸控制**：question/reply 截断 500、error 500、params_json 800、detail 300——调试够用，防库膨胀。

#### 2. `ui/debug.html` + `ui/debug.js`（+ 复用/新增 `ui/debug.css`）

用 **frontend-design 插件技能**设计视觉方案后实现（约束：与现有工作台同一套设计语言延续、原生 HTML/CSS/JS、后台固定中文）。页面结构：

- **顶部概览卡**：今日问答数 / 总 token（输入+输出）/ 兜底占比 / 约束拦截数 / 平均耗时
- **中部三块**：
  - 工具调用排行（名称 + 次数 + 平均耗时条形）
  - 智能体分布（route × llm_mode 堆叠占比）
  - **会话 token 趋势**（选中某 session 过滤时显示该会话逐轮 input_tokens 折线——诊断记忆上下文膨胀的核心视图：轮次越多 input 应平稳，若持续攀升说明上下文注入失控）
- **下方 trace 列表**（可按 session / route 过滤）：表格行 = 时间 / 会话 / 路由 / 模式 / 工具数 / token / 耗时 / 状态；点击行**展开事件时间线**（constraint → stage → llm → tool 的瀑布，含参数 JSON、状态与耗时；错误行红标可展开看 error 详情）
- **刷新**：手动刷新按钮 + 可开关的 5s 自动轮询（默认关）
- **维护**：「清空遥测数据」按钮（调 `POST /api/telemetry/clear`，带确认弹窗）

#### 3. server.py 新增 4 个 API + 静态挂载

```
GET  /api/telemetry/traces?limit=&session_id=&route=  → 近期 trace 列表
GET  /api/telemetry/traces/{id}                       → 单条 trace + 事件明细
GET  /api/telemetry/summary                           → 聚合统计（概览卡 + 排行数据源）
POST /api/telemetry/clear                             → 清空遥测库（调试期维护）
挂载：app.mount("/debug", StaticFiles(directory=BASE_DIR/"ui", html=True)) 限制到 debug.html
     实现方式：小路由 @app.get("/debug") 返回 FileResponse(ui/debug.html)
```

### 修改文件

#### 4. `core/dispatch/orchestrator.py` — 流水线埋点（trace 骨架 + 工具事件落库闭环）

- `answer()` 开头：`trace_id = recorder.start_trace(...)`；结束前 `close_trace(...)`（latency 用 `time.perf_counter` 全程差值）
- 各阶段埋点：
  - 约束 pre_check 命中 → `add_event(kind="constraint", name=verdict.kind, status="deny")`，`llm_mode="constraint"`，close 后返回
  - 路由完成 → `add_event(kind="stage", name="route", detail=route)`
  - 上下文组装 → `add_event(kind="stage", name="context", detail=f"{非空块数}块/{estimated_tokens}tok")`；`context_tokens` 存 trace
  - LLM 调用（supervisor.answer）计时 → `add_event(kind="llm", name=route, duration_ms=…)`；异常 → status="error"、error 文本存 trace
  - **工具事件落库（v2 补齐闭环）**：消费 supervisor 返回的 `_telemetry` 时，把 `tool_calls` 逐条 `add_event(kind="tool", name=…, params=…)`——LLM 模式的工具调用全部由此入 events 表（与 registry 埋点两路合并展示）；token 同时 `set_tokens(...)`
  - 兜底 → `llm_mode="fallback"` + `add_event(kind="stage", name="fallback")`；**从 `result.data.type` 推断工具事件**（`research_report`→`run_product_research`、`supplier_compare`→`search_supplier+compare_supplier`、`listing_draft`→`draft_listing` 等，映射表一处维护）
  - 约束 post_check → `add_event(kind="stage", name="post_check")`
- `_telemetry` 消费完即 `result.pop("_telemetry", None)`，**在 `wrap()` 之前剥离**，保证对外契约不变

#### 5. `agents/base.py` — usage / tool_calls 提取（唯一真实 token 数据源）

`_format_result` / `answer()` 中，对 `result["messages"][prev_count:]`：

- 累加每条 AIMessage 的 `usage_metadata`（`input_tokens/output_tokens`；ReAct 每步模型调用各有一条，含工具调用轮——汇总口径 = 本轮所有模型调用之和，与 API 计费一致）
- 收集所有 `tool_calls`（name + args）
- 汇总为 `formatted["_telemetry"] = {"input_tokens":…, "output_tokens":…, "tool_calls":[{name, args}…], "model": self.model}`（key 带下划线表示内部字段，orchestrator 消费后剥离）

#### 6. `core/dispatch/registry.py` — GLOBAL_REGISTRY.call 一行埋点

`call()` 成功/失败处各加 `recorder` 记录（kind="tool"，name，params 截断，status ok/error/deny）——覆盖约束层工具与未来跨模块调用（fail-open：recorder 异常吞掉）。

> LLM 模式工具由第 4/5 点的 `tool_calls` 提取；兜底/跨模块由本点 + data.type 推断覆盖；三路合并进同一 events 表。

#### 7. `ui/index.html` — 主页面加后台入口

顶栏/页脚加一个低调的「调试后台」链接 → `/debug`（不打扰主工作台）。

#### 8. `.gitignore` — 增补一行

```
core/telemetry/data/
```

（`*.sqlite` 已全局忽略，但显式加目录规则与 `memory/*/data/` 保持同一防御层次。）

#### 9. `memory/demo.py` — 追加 P10 验收场景

加一段：发一条问答 → 查 traces/events 表有记录 → 断言字段齐全 → clear() 后表为空。

---

## 假设与决策

- token 只有 LLM 模式有真实值（API usage）；兜底模式 `tokens_source="none"` 显示"—"，`context_tokens`（估算）单独展示并标注
- trace 不记完整 prompt/reply 全文（只截断摘要）——完整原文在短期记忆 checkpoint 里，需要时另查；避免库膨胀与敏感内容落库
- 遥测库独立于审计库（`core/telemetry/data/telemetry.sqlite` vs `memory/data/access.sqlite`）
- 后台页面不做鉴权（本地调试工具，与现有 UI 同级）；中日切换仅主工作台需要，后台固定中文
- 自动轮询默认关闭，手动点开；清空数据需二次确认
- 单进程假设（与项目整体一致），遥测写库为同步 SQLite（单轮量级 < 10 事件，微秒级，不引异步复杂度）

## 验证步骤

1. `python -m py_compile` 全部改动文件
2. 验收脚本（无 Key 模式）：发 3 轮问答（普通选品/红线拦截/重复提问）→ 查库断言 3 条 trace；约束事件 status=deny；兜底 trace 的工具事件来自 data.type 推断；clear 后表空
3. 有 Key 时人工验证 usage 累加正确（ReAct 多步工具调用时 input/output 逐条累加，与 API 后台账单对得上）
4. 启动 server → `/debug` 打开 → 概览卡 / 工具排行 / 智能体分布 / token 趋势 / trace 展开事件时间线 / session 过滤 / 轮询开关 / 清空按钮全部可用
5. 主工作台回归：`/api/ask` 返回契约不变（`_telemetry` 已在 wrap 前剥离）
