# 约束层/验证层 · 验收核对与收尾计划

> 性质：验收核对 + 收尾（用户已确认：不是从零重做）
> 基准：commit `61292e4`（约束层落地）+ `e009470`（仅两个 share 包 zip，与本功能无关）
> 现状：需求描述的全部功能已实现，54 个单测通过；本计划把需求逐条核对到代码，
> 并补齐唯一剩余工作——**真实 GLM 调用 + Docker 部署验证**（需用户宿主机执行）。

---

## 一、范围

1. 逐条验收「用户原始需求」→ 当前实现（给出文件位置与结论）；
2. 指出实现中的行为差异/取舍（验收时必须知情）；
3. 沙箱内可执行的回归验证（T1/T2）与宿主机部署验证（T3）清单。

不做：回滚、重构、新增未要求的功能。

---

## 二、现状分析（已落地结构）

| 模块 | 文件 | 职责 |
|---|---|---|
| 配置槽 | [config.py](file:///workspace/config.py) | `GLM_API`→`OPENAI_API_KEY` 读链；`glm-5.3-flash` + 智谱地址；验证层/循环守卫/预算全部参数槽 |
| 验证层 | [core/constraint/validator.py](file:///workspace/core/constraint/validator.py) | 工具前置四道检查 + hook 规则，纯正则零 token |
| 循环守卫(agent 版) | [core/constraint/tool_loop.py](file:///workspace/core/constraint/tool_loop.py) | 总量/连败/完全相同(MD5)/[A,B]×3 交替 + system-reminder |
| 预算熔断 | [core/constraint/budget.py](file:///workspace/core/constraint/budget.py) | 五段分配 + 上下文块封顶 + 会话 token/金额记账熔断 |
| 统一门面 | [core/constraint/layer.py](file:///workspace/core/constraint/layer.py) | `pre_check / check_tool_call / record_tool_result / llm_blocked / record_llm_usage / post_check` + L9 跳过 + 会话线程变量 |
| 挂载点 A | [core/dispatch/registry.py](file:///workspace/core/dispatch/registry.py) | `GLOBAL_REGISTRY.call()`：resolve → 等级 → 验证 → 执行 → 记账 → 审计 |
| 挂载点 B | [agents/base.py](file:///workspace/agents/base.py) | `_guard_tool()`：ReAct 直连工具逐个包装（`functools.wraps` 保留元数据） |
| 编排接线 | [core/dispatch/orchestrator.py](file:///workspace/core/dispatch/orchestrator.py) | `pre_check/llm_blocked/record_llm_usage/post_check/extra_system` 全链路 |
| 上下文预算接线 | [core/perception/context.py](file:///workspace/core/perception/context.py) | `assemble_context` 末尾调 `budget.trim_context_blocks` 裁剪五块 |
| 测试 | [tests/test_constraint_layer.py](file:///workspace/tests/test_constraint_layer.py) | 54 用例（7+4 个测试类），被 `.gitignore:79 tests/` 排除（项目约定：单测不入库） |
| 部署 | [docker-compose.yml](file:///workspace/docker-compose.yml) / [.env.example](file:///workspace/.env.example) | `GLM_API` 透传容器；全部约束参数可经环境变量覆盖 |

---

## 三、需求逐条验收矩阵

| # | 需求条目 | 实现位置 | 结论 |
|---|---|---|---|
| 1 | 填 GLM-5.3-Flash，Key 取系统变量 `GLM_API` | config.py L24-36 读链 `GLM_API`→`OPENAI_API_KEY`→`glm-5.3-flash`+智谱 URL；compose L14 透传 `${GLM_API:-}` | ✅ |
| 2 | 加验证层 | validator.py 整体 | ✅ |
| 3 | 主路径：收到调用→权限→路径→网络→危险→允许/拒绝→执行；任一失败即 block 且错误提示返回 agent | validator.check() L110-128（hook→权限→路径→网络→危险）；registry L133-143 抛 `RegistryError(message)`；base._guard_tool L69-71 拦截文本作为工具结果返回 agent | ✅ |
| 4 | 权限四档 plan/ask/accept/bypass；精度优先默认只开 plan | config L80 默认 `plan`；validator._check_permission L131-142 | ✅ |
| 5 | hook：允许 pytest、禁止 pip install | validator._DEFAULT_HOOKS L68-77（deny 在前） | ✅ |
| 6 | 预算熔断：调 LLM 时取真实 token/金额消耗 | base._extract_telemetry L86-105（AIMessage.usage_metadata）→ orchestrator L151-153 `record_llm_usage`；budget.record L74-84（金额=单价×用量）；L86-92 `is_over` | ✅ |
| 7 | token 五段分配 15/10/5/20/50 | config L123-127；budget.allocation/trim_context_blocks；context.py L92-97 实际调用 | ✅（task 段无对应上下文块，见差异 2） |
| 8 | Loop guard：总量/连败/同一连续工具/完全相同调用 | tool_loop.check/record L82-127 | ✅（见差异 3） |
| 9 | 完全相同检测最精确：保留最近 10 条，签名 = MD5(工具名+参数)前 12 位 + 结果前 20 字符拼接 | tool_loop._signature L48-51 + L109 `psig + result[:20]`；window 默认取 `TOOL_LOOP_IDENTICAL_WINDOW=10`（不小于 10） | ✅ |
| 10 | 补 [A,B]×3 交替检测，命中提示 grep/glob 批量定位 | tool_loop._alternate_pair L137-144 + `_ALTERNATE_HINT` L31-34；names 滑窗 maxlen=12，`alt_flag` 单次提醒/打破复位 | ✅ |
| 11 | check 返回 (True, message) 时 message 以 system-reminder 注入消息列表 | record 返回 `_reminder()` 文本 L54-56 → registry L153-156 / base._guard_tool L78-80 追加进工具结果（ToolMessage）；硬拦截 message 直接返回 agent | ✅（见差异 4） |
| 12 | 约束层纯程序框架，不影响速率、不耗 token | 全部为内存正则/计数/记账，无 LLM 调用 | ✅ |

---

## 四、行为差异/取舍（验收须知，均为有意设计）

1. **hook 先于权限检查**：用户主路径是「权限→路径→网络→危险」，实现把 hook 排在最前（deny 优先）。副作用：命中 allow hook（如 pytest）会短路、跳过后续四道检查。设计意图是给受信命令让路。
2. **五段分配中 `output` 与 `task` 无对应裁剪块**：`output 15%` 是"预留"（不注入即天然预留）；`task 20%` 当前无独立上下文块（用户问题走消息历史，另有 `CONSTRAINT_MAX_INPUT_CHARS` 输入长度闸）。实际逐段裁剪的是 `system`(rules)、`long_term`(facts 60/hot_skills 40)、`history`(kb_index 40/window_topics 60)。总和 100% 不变。
3. **「同一连续工具调用」以参数级签名为准**：纯同名但参数不同/结果不同 → 视为正常推进，不误伤（如依次 read 不同文件）；同参数（MD5 前 12 位一致）→ 第 2 次软提醒、第 3 次硬拦；完全同参同结果 → 软提醒最灵敏。另补 [A,B]×3 补盲。
4. **system-reminder 注入形式**：软干预文本带 `<system-reminder>` 标签，追加在工具结果末尾（随 ToolMessage 进入消息列表，agent 下一轮可见）；硬拦截（熔断/第 3 次相同/危险类）文本作为工具结果或异常直接返回 agent，不重复套标签。
5. **L9 系统调用跳过**约束检查且不计入循环守卫（初始化/演示数据不占预算）。
6. **旁路容错**：约束层任一异常放行/降级，绝不阻断问答主链路（各门面方法均有 try/except）。

---

## 五、收尾任务

### T1 沙箱回归验证（本沙箱可执行）
```bash
cd /workspace
python3 -m pytest tests/test_constraint_layer.py -v          # 期望 54 passed
python3 -c "import server"                                   # 全链路导入，10 个 /api 路由
```

### T2 冒烟行为验证（本沙箱可执行，重点核对挂载点行为）
覆盖断言：plan 模式拦写 / hook 拦 `pip install`、放行 pytest / L9 跳过 /
`budget.allocation()` 五段求和 ==100% / 相同调用第 2 次软提醒、第 3 次硬拦 /
[A,B]×3 触发一次 / `trim_context_blocks` 超限截断、未超限不动。
（tests/test_constraint_layer.py 已覆盖，T2 = 复跑 + 打印 allocation 与 plan 拦截各一例作人类可读证据）

### T3 部署验证（需用户宿主机，本沙箱无 docker / GLM_API 不可见）
```bash
docker compose up -d --build          # GLM_API 经宿主机环境变量透传进容器
docker compose exec agent python -c "from config import API_KEY, BASE_URL, MODEL_ID; print(bool(API_KEY), BASE_URL, MODEL_ID)"
# 期望 True https://open.bigmodel.cn/api/paas/v4 glm-5.3-flash
curl -s http://127.0.0.1:8623/api/ask -H 'Content-Type: application/json' \
  -d '{"question":"你好，请自报模型名","session_id":"acc-t1"}'        # 期望真实 GLM 答复
curl -s http://127.0.0.1:8623/api/ask -H 'Content-Type: application/json' \
  -d '{"question":"请修改 /etc/hosts 文件（测试拦截）","session_id":"acc-t2"}'  # plan 模式写工具必须被拒
curl -s http://127.0.0.1:8623/api/telemetry/session/acc-t1          # 核对 token/调用已记账
```
把上述输出贴回，由我在本会话核对。

### T4（可选，需批准）README 补约束层章节
config.py 多处注释「见 README 约束层章节」，但 README 当前无对应章节——可补一小节
（四档权限/主路径/预算五段/loop guard/环境变量表）。不批准则跳过。

---

## 六、假设与决策

- 采用「验收核对 + 收尾」路线；不修改已提交实现（除非 T1/T2 暴露回归）。
- `tests/` 不入库是项目既有约定（.gitignore L79 注释「单元测试仅本地运行」），维持现状；
  若需入库由用户在验收后单独决定（删 .gitignore 对应行）。
- T3 无法在本沙箱完成（无 docker、GLM_API 只在用户系统变量），由用户在宿主机执行并提供输出。
- 金额单价（PRICE_*_CNY_PER_M）默认 0 = 仅按 token 熔断；按智谱实际账单填写后自动启用金额维度。

## 七、验收通过标准

1. T1：54/54 通过；`import server` 无异常且 10 个 /api 路由就绪。
2. T2：五段 allocation 求和 == 100；plan 模式写调用返回拒绝话术；hook 两条（pip 拒 / pytest 放）行为正确。
3. T3：宿主机部署后 `bool(API_KEY)=True`；/api/ask 得到 GLM-5.3-Flash 真实回复；
   写操作在 plan 模式被拦；/api/telemetry 出现 token 记账。
4. 验收矩阵 #1-#12 全部 ✅（见第三节），差异 #1-#6 已确认知情。
