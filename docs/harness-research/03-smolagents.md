# HuggingFace smolagents 架构深度分析

> 研究对象：`github.com/huggingface/smolagents`（main 分支，Apache-2.0，纯 Python）。
> 分析基准：`git clone --depth 1` 所得快照，head 提交 `30bb1161`（2026-08-22，"Update contribution guidelines (#2679)"），`src/smolagents/__init__.py:17` 声明版本 `1.27.0.dev0`。
> 证据标注：所有代码引用均来自该快照，路径为仓库内相对路径（如 `src/smolagents/agents.py:268` 表示文件第 268 行）；凡外部/不确定信息均显式标注。

## 0. 命名与文件布局的版本漂移（重要前置说明）

任务描述中提到的若干文件/符号与当前 main 分支的实际代码存在漂移，先列清楚，后文均以真实代码为准：

1. **主循环文件不再是 `agent.py`**：当前 main 把 Agent 相关实现合并回单一文件 `src/smolagents/agents.py`（1813 行），其中依次定义 `RunResult`、`MultiStepAgent`、`ToolCallingAgent`、`CodeAgent`，文件末尾还有反序列化白名单 `AGENT_REGISTRY`（`agents.py:1810`）。历史上曾拆分为 `agent.py`/`code_agent.py`/`toolcalling_agent.py`，现已合并。
2. **`DelegationTool` 类已不存在**：整个 `src/` 中搜不到该符号。子代理委派改由 `managed_agents` 机制直接承担（详见第 8 节）。
3. **模型命名演进**：`models.py` 中 `class InferenceClientModel`（`models.py:1456`）承担了旧 `HfApiModel` 的职责；`OpenAIServerModel = OpenAIModel`（`models.py:1796`）与 `AzureOpenAIServerModel = AzureOpenAIModel`（`models.py:1856`）以向后兼容别名形式保留。全文件无 `HfApiModel` 标识符。
4. **文档目录漂移**：`docs/source/en/` 下没有 `rational_agents.md`/`code_agents.md`；当前概念页只有 `conceptual_guides/intro_agents.md`、`conceptual_guides/react.md`，代码安全与记忆分别落在 `tutorials/secure_code_execution.md`、`tutorials/memory.md`、`tutorials/inspect_runs.md` 等。

## 1. 概览：定位、规模与核心主张

**定位**：smolagents 是 HuggingFace 出品的"极小核心的 agent harness"，刻意把抽象收敛到最少，把代码当作可读的一等公民。README 的三条自我主张是：

- **Simplicity**：agent 逻辑"约 1000 行"（README 指向 `src/smolagents/agents.py`）。实测当前快照中 `agents.py` 为 1813 行、`src/smolagents/` 全部 Python 约 1.36 万行——"约 1000 行"是营销口径与早期版本的真实量级，当前已随功能增长超出。
- **First-class support for Code Agents**："`CodeAgent` writes its actions in code (as opposed to 'agents being used to write code')"——即模型**直接写 Python 代码作为行动**，而不是先想一堆工具名再发 JSON。
- **Model-agnostic / Modality-agnostic / Tool-agnostic**：模型可接本地 transformers、HF Inference、OpenAI/Anthropic 等（经 LiteLLM）；支持文本/图像/音频；工具可来自 MCP server、LangChain、HF Space。

**语言与生态**：Python（pyproject 要求 ≥3.10），Apache-2.0，首次发布约在 2024 年底/2025 年初。Stars：本环境内 GitHub API 未经认证被限流（共享出口 IP 429），无法实时读数；第三方观测口径 2026 年 5–9 月为"约 2.7–2.8 万"，故本文记为"**约 2.7–2.8 万（第三方观测，未实时核验）**"。被转述的里程碑包括：论文 *Executable Code Actions Elicit Better LLM Agents*（2402.01030）等支撑"代码行动优于 JSON 工具调用"；HF 官方博客宣称 GAIA 44.2% 第一（第三方转述，未在本仓库内核实，谨慎引用）。

**核心主张（Code-first）**：与其让模型"从工具列表里挑一个并填 JSON 参数"，不如让模型直接写一小段 Python：组合多个工具、定义中间变量、条件分支、循环，一次行动完成多步操作。官方文档（`docs/source/en/tutorials/secure_code_execution.md`）从**可组合性、对象管理、通用性、预训练语料覆盖**四个角度论证"代码比 JSON 更擅长表达计算机上的动作"。代价是必须解决"执行任意模型生成代码"的安全问题——这构成了整个安全执行子系统的存在理由（见第 6 节）。

## 2. 核心抽象与分层

```
                        ┌─────────────────────────────┐
  user ── task ──▶      │        MultiStepAgent       │  agents.py:268
                        │  run()/_run_stream()/step() │
                        │  tools dict / state / memory│
                        └──────┬──────────────┬───────┘
                               │              │
                  CodeAgent    │   ToolCallingAgent  │  agents.py:1505 / 1215
                  ┌────────────▼───────┐   ┌─────────▼──────────┐
                  │ python_executor    │   │ model.generate(    │
                  │ (PythonExecutor)   │   │  tools_to_call)    │
                  └──────────┬─────────┘   └─────────┬──────────┘
                             │                       │
        local_python_executor / E2B / Docker / Modal / Blaxel     models: Model → ApiModel/Transformers/...
```

**组件清单（文件→职责）**：

| 抽象 | 定义位置 | 说明 |
|---|---|---|
| `MultiStepAgent`(ABC) | `agents.py:268` | 所有 agent 的基类：跑 ReAct 主循环、持 memory/tools/managed_agents/logger/monitor |
| `CodeAgent` / `ToolCallingAgent` | `agents.py:1505` / `1215` | 两种"行动范式"的具体实现（见第 5 节） |
| `Model` | `models.py:452` | 模型抽象，`generate()` 是唯一必须实现的方法；另有流式 `generate_stream`（可选） |
| `Tool` / `BaseTool` | `tools.py:106` / `98` | 工具基类；`@tool` 装饰器把函数转成 Tool（`tools.py:1061`） |
| `ToolCollection` | `tools.py:895` | 批量装载工具：`from_hub`（HF collection）/ `from_mcp`（MCP 服务器） |
| `PythonExecutor` | `local_python_executor.py:1677` | 代码执行器抽象（`send_tools/send_variables/__call__`），CodeAgent 持有其实现 |
| `LocalPythonExecutor` | `local_python_executor.py:1688` | 本地 AST 解释执行器（默认） |
| `E2B/Docker/Modal/Blaxel Executor` | `remote_executors.py:335/551/726/859` | 远程沙箱执行器 |
| `AgentMemory` + `MemoryStep` 族 | `memory.py:214` / `42` | 记忆：`TaskStep`/`ActionStep`/`PlanningStep`/`FinalAnswerStep`/`SystemPromptStep` |
| `Monitor` / `AgentLogger` | `monitoring.py:81` / `130` | token/时长统计与 Rich 控制台日志 |
| `CallbackRegistry` | `memory.py:280` | 按 MemoryStep 子类注册回调的钩子系统 |

关于任务描述中的 **toolbox**：smolagents 没有名为 `toolbox` 的类；工具的运行时容器是 `self.tools: dict[str, Tool]`（按 name 索引，`agents.py:393`），批量"装弹"工具由 `ToolCollection` 完成。关于 **managed_agents**：是 `dict[name → MultiStepAgent]`（`agents.py:369-387`），manager 可把子代理当作工具一样调用（第 8 节）。

## 3. Agent 主循环：真实 step 循环

入口是 `MultiStepAgent.run(task, stream, reset, images, additional_args, max_steps, return_full_result)`（`agents.py:436`）。非流式时它把 `_run_stream` 生成器全部消费掉，断言最后一个 step 是 `FinalAnswerStep`，再决定返回 `RunResult` 还是裸输出（`agents.py:498-538`）。

`_run_stream`（`agents.py:540`）是主循环本体，逐段对应如下（提炼为伪代码，行号均真实）：

```python
# agents.py:543-611（_run_stream 内）
self.step_number = 1; returned_final_answer = False
while not returned_final_answer and self.step_number <= max_steps:      # :545
    if self.interrupt_switch: raise AgentError("Agent interrupted.")   # :546-547（interrupt() 置位, :754）
    if planning_interval 触发(首步或每 N 步):                            # :550-552
        yield 来自 _generate_planning_step 的流式增量; 收尾成 PlanningStep  # :553-567
        planning_step.timing 补齐 → self._finalize_step → memory.steps.append
    # —— 行动步开始 ——
    action_step = ActionStep(step_number, timing=Timing(start_time))     # :571-575
    try:
        for output in self._step_stream(action_step):                    # :578（多态：CodeAgent/ToolCallingAgent）
            yield output                                                 #   流式增量透传
            if isinstance(output, ActionOutput) and output.is_final_answer:
                跑 self.final_answer_checks 校验（失败即抛 AgentError）     # :589-590
                returned_final_answer = True; action_step.is_final_answer=True
    except AgentGenerationError as e: raise e        # 模型实现级错误 → 直接终止 :594-596
    except AgentError as e:                          # 其余 AgentError（解析/执行/工具错误）
        action_step.error = e                        # → 记到步骤上，不中断循环 :597-599
    finally:
        self._finalize_step(action_step)             # 补 end_time + 触发 step_callbacks :620-623
        self.memory.steps.append(action_step)        # 观察/错误进入"记忆"供下一轮输入
        yield action_step; self.step_number += 1
# while 退出后：
if not returned_final_answer and self.step_number == max_steps + 1:       # :606
    final_answer = self._handle_max_steps_reached(task)                   # :625：provide_final_answer 兜底
yield FinalAnswerStep(handle_agent_output_types(final_answer))            # :609-611
```

**闭环的五个环节**（对应任务要求的"模型输出→解析 action→执行→observation→加入 memory"）：

1. **模型输出**：子类把"记忆转 messages"喂给 `self.model.generate(...)`（`write_memory_to_messages`，`agents.py:758`：system prompt + 逐 step `to_messages`），得到 `ChatMessage`；每个行动步的输入/输出/耗时会写回 `ActionStep.model_input_messages/model_output/token_usage`（见 `agents.py:1648-1698`、`1276-1325`）。
2. **解析 action**：范式相关（`CodeAgent` 用 `parse_code_blobs` 切出代码块再 `fix_final_answer_code`；`ToolCallingAgent` 直接读 `chat_message.tool_calls` 或经 `Model.parse_tool_calls` 从文本兜底解析，`agents.py:1327-1334`）。解析失败抛 `AgentParsingError`，被 `except AgentError` 接住后变成该步的 `error`。
3. **执行 action**：`CodeAgent` 调 `self.python_executor(code_action)`；`ToolCallingAgent` 走 `process_tool_calls` → `execute_tool_call(tool_name, arguments)`（`agents.py:1453`），执行前先 `validate_tool_arguments`（参数 schema 校验）再 `tool(**arguments, sanitize_inputs_outputs=True)`。
4. **observation**：执行结果拼成字符串（CodeAgent：`"Execution logs:\n" + logs + "Last output from code snippet:\n" + truncate(...)`；ToolCallingAgent：工具返回值 `str()`，`AgentImage/AgentAudio` 存入 `self.state` 并仅记录"已存 memory"），写入 `memory_step.observations`。
5. **加入 memory**：整个 `ActionStep`（含 model_input_messages、tool_calls、observations、error、token_usage、timing）追加到 `AgentMemory.steps`。下一轮 `write_memory_to_messages` 会把它重放为 `ASSISTANT`（模型输出）、`TOOL_CALL`（"Calling tools:..."）、`TOOL_RESPONSE`（"Observation:..." 或 "Error:... Now let's retry..."）等角色消息（`memory.py:92-150`）。

**max_steps / 重试 / 工具异常语义**：

- `max_steps` 默认 20（`agents.py:300`），可在 `run(max_steps=...)` 覆盖（`:468`）。
- **重试语义的关键设计**：除 `AgentGenerationError`（判定为框架/实现 bug，直接上抛终止）外，解析错误、代码执行错误、工具参数错误、工具运行时错误都被包装为各类 `AgentError` 记在该步上，循环**不中断**；下一轮模型输入里会出现"Error: ... Now let's retry: take care not to repeat previous errors! ..."（`memory.py:138-148`），由模型自己纠错重试。
- 错误类型层次（`utils.py:92-134`）：`AgentError` → `AgentParsingError` / `AgentExecutionError` / `AgentMaxStepsError` / `AgentGenerationError`；`AgentExecutionError` → `AgentToolCallError`（参数校验失败）/ `AgentToolExecutionError`（执行异常，异常消息会提示 "Please try again or use another tool" / 子代理场景提示 "Please try again or request to another team member"，`agents.py:1490-1502`）。
- 工具调用执行器里的错误抛出后同样被 `_run_stream` 捕获并重试。
- 超步：耗尽步数仍无 final answer 时，用记忆做一次"收尾问答"（`provide_final_answer`，`agents.py:810`，提示词模板 `final_answer.pre_messages/post_messages`，见 `code_agent.yaml`），生成兜底答案并把 `AgentMaxStepsError` 记入步骤（`_handle_max_steps_reached`，`agents.py:625-637`）。
- 可选 planning：`planning_interval` 不为空时，首步与每 N 步插入一次独立的"事实盘点+计划更新"（`_generate_planning_step`，`agents.py:639`），产出一个 `PlanningStep`。

## 4. 记忆与状态管理（task / chat_message 状态）

- `AgentMemory`（`memory.py:214`）就是 `system_prompt`（`SystemPromptStep`）+ `steps` 列表；`reset()` 清空 steps 保留 system prompt。它把步骤导出为 `get_succinct_steps()`（去掉冗余的 model_input_messages）/`get_full_steps()`，并支持 `replay()` 与 `return_full_code()`（把历次 `code_action` 拼成完整脚本）。
- `ActionStep`（`memory.py:51`）是一个 dataclass，字段：`step_number/timing/model_input_messages/tool_calls/error/model_output_message/model_output/code_action/observations/observations_images/action_output/token_usage/is_final_answer`。
- 消息类型：模型侧统一用 `ChatMessage`（`models.py:124`），角色枚举 `MessageRole`（`models.py:111`）除 user/assistant/system 外还有 `TOOL_CALL`/`TOOL_RESPONSE` 等 agent 内部角色；`get_clean_message_list`（`models.py:332`）负责把内部角色翻译成各家 API 的角色名（`custom_role_conversions` / `tool_role_conversions`），不支持的模型可整体 `flatten_messages_as_text`。
- 进程内 `state`（`agents.py:331`）承载跨步变量（用户 `additional_args`、`AgentImage/AgentAudio` 产物），对 CodeAgent 会注入执行器命名空间、对 ToolCallingAgent 会在调用参数里做变量替换（`_substitute_state_variables`，`agents.py:1444`）。**注意**：这是"单次 run 内的执行期状态"，不是跨会话持久记忆——官方文档 memory 教程也仅讨论 run 内消息历史。

## 5. 两种行动范式对比：CodeAgent vs ToolCallingAgent

两者共享 `MultiStepAgent` 的全部骨架，差异集中在 `initialize_system_prompt` 与 `_step_stream`：

| 维度 | `CodeAgent`（`agents.py:1505`） | `ToolCallingAgent`（`agents.py:1215`） |
|---|---|---|
| 模型输出形式 | 自然语言 "Thought:" + 一段 Python 代码块 | 结构化 function call（`tool_calls`） |
| 默认系统提示词 | `prompts/code_agent.yaml`（Jinja2，工具被渲染成"可用 python 函数"列表 `tool.to_code_prompt()`） | `prompts/toolcalling_agent.yaml` |
| 可选结构化输出 | `use_structured_outputs_internally=True` 时改用 `structured_code_agent.yaml`，并向模型传 `response_format=CODEAGENT_RESPONSE_FORMAT`（`agents.py:1546-1554, 1656-1658`） | 依赖 API 原生 tool calling |
| 代码块解析 | `parse_code_blobs(output_text, code_block_tags)`；标签默认 `<code></code>`，可配 markdown 风格（`agents.py:1558-1564, 1702-1713`） | `chat_message.tool_calls` 直接可用；API 不返回结构化时用 `model.parse_tool_calls` 从文本解析（`agents.py:1327-1334`） |
| "执行" | `self.python_executor(code_action)`（本地或远程沙箱），产出 `CodeOutput{output, logs, is_final_answer}` | `execute_tool_call`：查名 → 参数校验 → `tool(**args, sanitize_inputs_outputs=True)` |
| 多个动作/步 | 一个代码块可组合多次工具调用、循环、条件 | 一次可并行发多个 tool_call（`ThreadPoolExecutor` + `copy_context`，`agents.py:1424-1434`） |
| 终止信号 | 代码里调用 `final_answer(...)`；执行器把它转成内部 `FinalAnswerException`（`BaseException` 子类，防止被模型代码 `except Exception` 吞掉）向上抛出（`local_python_executor.py:1572, 1630-1636`） | 名为 `final_answer` 的工具被调用即终止（`process_single_tool_call` 中 `is_final_answer = tool_name == "final_answer"`，`agents.py:1406`）；多个 final 或"final 前还调别的工具"都会报错（`agents.py:1339-1351`） |
| 代码执行的 stop 处理 | stop_sequences 含 `"Observation:"/"Calling tools:"` 与代码闭合标签；生成没闭标签会补上以稳定下次生成（`agents.py:1651-1654, 1690-1695`） | stop_sequences 为 `["Observation:", "Calling tools:"]` |

一句话：**CodeAgent 让"行动"拥有编程语言的表达力（组合/复用/通用），ToolCallingAgent 则保持"标准 JSON 工具调用"的最大兼容性**（很多模型不擅长写代码，或无法承担代码执行）。官方立场是 Code-first：`CodeAgent` 是默认推荐的旗舰型，`ToolCallingAgent` 用于兼容与对照。

## 6. 安全执行：从"尽力而为的本地解释器"到"真沙箱"

这是 Code-first 路线绕不开的命题。smolagents 提供两级防护，官方文档（`tutorials/secure_code_execution.md`）明确承认"本地执行本质上仍有风险，没有任何方案 100% 安全"，并列举风险面：LLM 误生成危险代码、供应链攻击、prompt injection（agent 浏览网页被恶意站点注入）、公有 agent 被滥用。

### 6.1 本地层：`LocalPythonExecutor` 的 AST 白名单解释器

默认情况下 `CodeAgent` 不用 Python 原生 `exec`，而是把代码交给一个从零手写的 AST 解释器（`local_python_executor.py`，1768 行）：

- `evaluate_python_code`（`:1583`）先 `ast.parse(code)`，语法错误转成带行号的 `InterpreterError`；随后逐条 `evaluate_ast(node, state, static_tools, custom_tools, authorized_imports)`（`:1417`）。
- **按节点类型的隐式白名单**：`evaluate_ast` 只处理它认识的那一批 AST 节点（Assign/Call/For/While/If/FunctionDef/ClassDef/Lambda/ListComp/Import/... 约 50 种，`:1450-1566`），任何未实现节点统一 `raise InterpreterError(f"{...} is not supported.")`（`:1568-1569`）——即"没被显式允许的语法就等于禁用"。官方文档原话："Any operation that has not been explicitly defined in our custom interpreter will raise an error."
- **import 白名单**：默认仅 `BASE_BUILTIN_MODULES = [collections, datetime, itertools, math, queue, random, re, stat, statistics, time, unicodedata]`（`utils.py:49-61`）；用户通过 `additional_authorized_imports` 放行更多模块，初始化时 `_check_authorized_imports_are_installed()` 会确认模块真实安装（`local_python_executor.py:1727`）。黑名单兜底：`DANGEROUS_MODULES = [builtins, io, multiprocessing, os, pathlib, pty, shutil, socket, subprocess, sys]`、`DANGEROUS_FUNCTIONS = [builtins.compile/eval/exec/globals/locals/__import__, os.popen/system, posix.system]`（`:130-153`）。
- **属性访问受限**：`getattr` 被替换为 `nodunder_getattr`，任何 `__x__` 双下划线属性访问直接报错（`:68-71`），防 `().__class__.__bases__...` 式逃逸；`safer_eval/safer_func` 装饰器对返回值做"危险模块/危险函数"事后检查（`:156-234`）。
- **资源上限**：操作计数上限 `MAX_OPERATIONS = 10_000_000`（每次求值递增计数器，`:1444-1448`）；`while` 上限 `MAX_WHILE_ITERATIONS = 1_000_000`（`:59`）；默认超时 `MAX_EXECUTION_TIME_SECONDS = 30`（`:60`，`timeout()` 装饰器实现，`:285`）；`print` 被 `custom_print` 替换、输出收集进 `state["_print_outputs"]`，最长截断 50_000 字符（`DEFAULT_MAX_LEN_OUTPUT`）。
- **工具不可被覆盖**：`static_tools`（含 final_answer 与用户工具）只读——往同名变量赋值会报错；`custom_tools` 可被覆盖（`:1436-1438` 语义）。
- **重要免责声明**：`LocalPythonExecutor` 类注释明写 "It is not a security sandbox: for isolated execution of untrusted code, use a remote executor."（`:1692-1693`）。它的目标是"防呆 + 抬高攻击门槛"，不是隔离边界。

### 6.2 远程沙箱层：E2B / Docker / Modal / Blaxel

`CodeAgent(executor_type=...)` 取值 `"local" | "blaxel" | "e2b" | "modal" | "docker"`（`agents.py:1535, 1599-1618`），`create_python_executor()` 工厂按类型实例化 `LocalPythonExecutor` 或 `remote_executors.py` 中对应类；远程模式与 `managed_agents` 互斥（`agents.py:1608-1609`）。

`RemotePythonExecutor`（`remote_executors.py:53`）的执行模型是"**把代码文本发到远端内核跑**"：

- `send_tools`：对每个工具收集 `to_dict()["requirements"]` 用 `!pip install` 装包，再把工具类源码（`get_tools_definition_code`，`tools.py:1335`，它会把每个 Tool 实例序列化成一个可导入的 `class SimpleTool(Tool)` + 实例化语句）注入远端命名空间；`final_answer` 会被打补丁成抛远端 `FinalAnswerException`（`:94-96`）。
- `send_variables`：把 `state` 经 `SafeSerializer` 序列化传过去，默认 `allow_pickle=False`（pickle 反序列化可执行任意代码，仅遗留兼容模式才放开，`:60-65, 115-131`）。
- 具体实现 `E2BExecutor`（`:335`，e2b.dev 沙箱）、`DockerExecutor`（`:551`，在容器里跑）、`ModalExecutor`（`:726`）、`BlaxelExecutor`（`:859`）；`CodeAgent` 还实现了上下文管理器 `__enter__/__exit__/cleanup()` 以便释放远端资源（`agents.py:1587-1596`）。
- 仓库根有 `e2b.toml` 模板，说明官方把 E2B 当默认演示沙箱。

### 6.3 提示词层约束

`code_agent.yaml` 的系统提示词给模型立规矩，把沙箱约束前置到模型行为里（`prompts/code_agent.yaml:157-168`）：必须有 Thought 与代码块；只用自己定义过的变量；不得把参数包成 dict 传工具；不重名工具；**"You can use imports in your code, but only from the following list of modules: {{authorized_imports}}"**；state 跨代码块持久等。

## 7. 工具体系

`Tool`（`tools.py:106`，父类 `BaseTool` 只抽象了 `__call__`）要求子类声明五个类属性：`name`（合法 Python 标识符）、`description`、`inputs`（dict[名称 → {type, description, nullable?}]，type 限定在 `AUTHORIZED_TYPES`）、`output_type`、可选 `output_schema`；并实现 `forward()`。实例化即校验（`__init_subclass__` 挂 `validate_after_init`，`:140-142`；`validate_arguments` 还会比对 `forward` 签名与 `inputs` 键是否一一对应，`:198-210`）。

调用语义（`Tool.__call__`，`:231-249`）：首次调用触发懒加载 `setup()`；支持"整个参数字典当作 kwargs"的容错；`sanitize_inputs_outputs=True` 时对入参/出参做 `handle_agent_input_types`/`handle_agent_output_types`（`AgentImage/AgentAudio/AgentVideo` 类型归一，见 `agent_types.py`）——这也是 **tool-calling 场景的工具输出可被模型直接理解**的基础。

创建途径与互操作：
- `@tool` 装饰器（`:1061`）：从函数类型注解 + docstring 生成 JSON schema，动态构造 `SimpleTool(Tool)` 子类，并把源码 `__source__` 存在类上供远程沙箱序列化复用。
- `Tool.from_hub/push_to_hub/save`（Hub 分享，`Tool.from_code`/`from_space`/`from_langchain`/`from_gradio` 包装各类三方工具）。
- `ToolCollection`（`:895`）：`from_hub`（HF collection 里的 Spaces 逐个 `Tool.from_hub`）、`from_mcp`（支持 stdio / streamable HTTP / 老 HTTP+SSE，独立线程跑 asyncio event loop）。
- 执行前还有一道 `validate_tool_arguments`（`tools.py:1361`）做参数名/必填/类型检查（含 int→number 放宽与 nullable）。

内置工具（`default_tools.py`）：`FinalAnswerTool`（`:83`，name=`final_answer`，唯一带"终止"语义的工具）、`PythonInterpreterTool`、`DuckDuckGoSearchTool`、`VisitWebpageTool`、`UserInputTool`、`WikipediaSearchTool`、`SpeechToTextTool` 等；`TOOL_MAPPING`（`:678`）只含 `python_interpreter`/`web_search`/`visit_webpage` 三个，作为 `add_base_tools=True` 时的默认装载集——但 CodeAgent 会跳过 `python_interpreter`（`agents.py:394-400`），因为代码执行由 executor 承担而非工具。

## 8. 多 agent：manager agent + managed subagents

设计极简：**子代理即工具**。`MultiStepAgent.__init__` 收 `managed_agents: list`（`agents.py:303`），`_setup_managed_agents`（`:369-387`）要求每个子代理都有合法 `name` 与 `description`，并给它们补上工具式的外壳字段 `inputs = {task: string, additional_args: object}`、`output_type = "string"`；`_validate_tools_and_managed_agents` 保证工具名与子代理名全局不重（`:404-414`）。

- **对 CodeAgent**：`run()` 里 `self.python_executor.send_tools({**self.tools, **self.managed_agents})`（`:492`），于是子代理在生成的代码里就是普通 python 函数（提示词把每个子代理渲染成 `def {agent.name}(task: str, additional_args: dict[str, Any]) -> str:`，`code_agent.yaml:139-155`）。
- **对 ToolCallingAgent**：`tools_and_managed_agents` 属性合并二者（`:1261-1263`），一并作为 `tools_to_call_from` 传给模型；`execute_tool_call` 里 `available_tools = {**self.tools, **self.managed_agents}`，识别 `is_managed_agent` 后按"团队成员"语义包装错误信息（`:1464-1502`）。
- **子代理侧**：被调用时走 `__call__`（`:868-890`）——套上 `managed_agent.task` 提示词模板（"You're a helpful agent named X... You're helping your manager solve a wider task"），跑自己的 `run()`，再按 `managed_agent.report` 模板 + 可选 `provide_run_summary`（追加 summary_mode 记忆）把报告回给 manager。整套提示词在 `prompts/code_agent.yaml` 的 `managed_agent` 段（`:288-307`）。
- manager 不强制：任意 agent 都可以有 managed_agents，可任意深度嵌套（`save()` 会递归保存 `managed_agents/` 子目录，`agents.py:910-916`）。官方 examples（`docs/source/en/examples/multiagents.md`）示范 manager + 专家子代理编排。
- 早期版本中该能力由 `DelegationTool` 实现，本快照已改为上述"直接注入"方案（见第 0 节）。

## 9. 模型接入与降级策略

`Model` 基类（`models.py:452`）把"各家 API 的差异"收敛到一个方法：`generate(messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs) -> ChatMessage`（`:553`）；可选 `generate_stream`（CodeAgent/ToolCallingAgent 的 `stream_outputs=True` 依赖它，`:1253-1256`）。统一管线在 `_prepare_completion_kwargs`（`:502`）：

- 消息清洗 `get_clean_message_list`（角色映射 / 图片转 URL / 文本展平）；
- 工具描述 `get_tool_json_schema(tool)`（`:540`，OpenAI 风格 function schema）与默认 `tool_choice="required"`；
- `supports_stop_parameter` 探测（`:499`，某些模型不支持 stop 参数时由框架自行 `remove_content_after_stop_sequences`，`:79`、`:1782-1783`）；
- `parse_tool_calls`（`:583`）为"不支持原生 tool calling、只能把工具调用写进文本"的模型兜底解析；
- 参数优先级：显式 kwargs < `self.kwargs`（模型级默认），`REMOVE_PARAMETER` 哨兵允许"显式禁用某参数"（`:544-550`）。

实现族（`models.py`）：
- 本地/自托管：`TransformersModel`（`:860`，可配 `grammar`）、`VLLMModel`（`:633`）、`MLXModel`（`:751`，Apple Silicon）。
- API 族 `ApiModel`（`:1138`）：统一提供 `client` 创建、`RateLimiter` 限速（requests_per_minute）与对 429/rate-limit 的指数退避重试 `Retrying`（`:1173-1183`）。子类：`LiteLLMModel`（`:1205`，经 LiteLLM 打通数百家，ollama/groq/cerebras 自动文本展平）、`InferenceClientModel`（`:1456`，HF Inference Providers：serverless / 专属 endpoint / 本地 URL，provider="auto" 按用户偏好路由）、`OpenAIModel`（`:1646`，OpenAI 兼容 `api_base`，别名 `OpenAIServerModel`）、`AzureOpenAIModel`（`:1799`）。
- 可移植性：`to_dict/from_dict`（`:596-630`）支持模型配置序列化（`agent.save()`/`push_to_hub` 复用），且**出于安全明确不导出 `token/api_key`**（`:620-626`）；`Model.from_dict` 按字典重建。

"降级"体现在两处：功能降级（不支持 stop/原生 tool-call 的模型由框架侧字符串处理补位）与质量降级（CodeAgent 对不擅长写代码的弱模型容易陷入"坏代码循环"，需要更强模型或改走 ToolCallingAgent/结构化输出——这是社区共识，非本仓库内文字）。

## 10. 可观测性：monitor / 日志 / 回调

- `AgentLogger`（`monitoring.py:130`）基于 Rich：`log_code/log_markdown/log_rule/log_task/log_messages`，等级 `LogLevel`（`:120`），运行中 `visualize_agent_tree`（`:232`）渲染 agent 树。
- `Monitor`（`monitoring.py:81`）统计每步时长与 input/output token 累计，并以 `step_callbacks.register(ActionStep, self.monitor.update_metrics)` 的方式自动挂到每个行动步（`agents.py:433-434`），控制台打印 `[Step N: Duration x.xx seconds | Input tokens: ... | Output tokens: ...]`。
- `CallbackRegistry`（`memory.py:280`）是通用钩子：`step_callbacks` 构造参数支持"list（兼容旧接口，只挂 ActionStep）或 dict[StepClass → callback]"（`agents.py:416-432`），回调按 `memory_step.__class__.__mro__` 匹配触发（`memory.py:313-316`）；`Monitor.update_metrics` 只是其中注册的一个。用户可借此接 Langfuse/Arize 之类追踪（官方 inspect_runs 教程即演示逐步检查 memory 与回调）。
- 运行产物：`RunResult`（`agents.py:196`）含 `output/state(success|max_steps_error)/steps/token_usage/timing`；`agent.run` 之外还有 `replay()`、`save()`、`push_to_hub()`/`from_hub()`（Hub 分享 agent，序列化受 `AGENT_REGISTRY` 白名单保护，`:1810`，注释明说防 `importlib` 动态加载造成任意代码执行）。

## 11. 关键代码节选

CodeAgent 一个行动步的核心（`agents.py:1723-1764`，节选）：

```python
### Execute action ###
try:
    code_output = self.python_executor(code_action)
    observation = "Execution logs:\n" + code_output.logs
except Exception as e:
    ...  # 取 _print_outputs 残量，把错误转 AgentExecutionError
truncated_output = truncate_content(str(code_output.output))
observation += "Last output from code snippet:\n" + truncated_output
memory_step.observations = observation
if not code_output.is_final_answer: ...
yield ActionOutput(output=code_output.output, is_final_answer=code_output.is_final_answer)
```

final_answer 变成异常的设计（`local_python_executor.py:1572-1636`，节选）：

```python
class FinalAnswerException(BaseException):   # 继承 BaseException，防被模型代码 except Exception 捕获
    def __init__(self, value): self.value = value
...
def final_answer(*args, **kwargs):           # 执行器把静态工具 final_answer 包成"抛异常"
    raise FinalAnswerException(previous_final_answer(*args, **kwargs))
```

## 12. 优缺点总结

**优点**
1. 极低的学习与阅读成本：一个 `agents.py` 读完即懂主循环；抽象数量少（Agent/Tool/Model/Executor/Memory 五件套）。
2. Code-first 范式在复杂任务上步子少、表达力强（一个代码块=一次行动）。
3. 安全/执行边界做成可插拔抽象（`PythonExecutor`），本地解释器、E2B/Docker/Modal/Blaxel 一键切换，策略清晰。
4. 工具生态互通广（MCP/LangChain/HF Space/Hub）+ 模型接入宽（本地三件套 + LiteLLM + HF + OpenAI/Azure）。
5. 多 agent 采用"子代理即工具"的同构设计，概念负担小、可任意嵌套。
6. 可观测性以回调 + 结构化 step 内存为基础，扩展追踪/评测方便。

**缺点/注意**
1. **本地执行不是沙箱**：默认 `executor_type="local"` 只是 AST 白名单解释器，官方明示对不可信代码要用远程沙箱；生产使用必须自己承担沙箱责任。
2. API 演进激进（实验期）：本快照中 agent 文件合并且类名/模型名持续调整（`MultiStepAgent` vs 旧 `Agent`、`InferenceClientModel` vs 旧 `HfApiModel`、`DelegationTool` 被移除、监控类移位），升级成本与文档滞后需要预期。
3. 无内置图编排/持久会话记忆/审计合规/UI 产品化能力——官方定位就是 harness，长流程、跨会话、强治理场景需自建或换 LangGraph 一类重框架。
4. 对模型要求高：CodeAgent 的效果强依赖模型写代码能力，弱模型易"坏代码循环"。
5. README "~1000 行"已不再精确（agents.py 实为 1813 行），文档与代码存在同步滞后。
6. 未认证 GitHub API 在本环境被限流，Star 数等社区指标无法实时核验（本文采用第三方观测并标注）。

## 13. 对其它 harness 的对比启发

- **对比 OpenAI Agents SDK / AutoGen**：smolagents 更"薄"——不提供托管 UI、群聊拓扑或企业级 guardrail；它证明"把循环写清楚 + 良好的执行边界"足以支撑复杂评测（第三方转述 GAIA 表现）。启发：harness 的核心价值在**循环语义（错误即重试上下文）、执行边界（可插拔沙箱）、工具与代理同构（子代理当工具）**三者的正交设计。
- **对比 LangChain/LangGraph**：前者以"链/图/状态机"为心智模型，适合需要显式分支合并、人工审批节点、跨会话持久化的编排；smolagents 以"单 agent 循环 + 记忆列表 + 委派"为心智模型，胜在透明与易 hack。启发：若任务不需要图编排，单循环 + 子代理委派往往更省成本。
- **对比 Pydantic AI / Instructor 类**：smolagents 不绑定结构化输出的类型系统，但它通过 `use_structured_outputs_internally` + JSON schema 工具描述获得相近收益，说明"结构化约束可以按需叠加而非内建于框架"。
- 总体启发：**主循环应薄、安全边界应分层（本地尽力而为 + 远端真沙箱）、扩展点用"步骤级事件"而非"框架级插件"**，这套取舍让一个千行级库同时具备可读性、安全选项与生态宽度。

## 附：主要证据文件索引（快照内相对路径）

- `src/smolagents/agents.py`（Agent 主循环/两类 agent/多 agent）
- `src/smolagents/tools.py`（Tool/@tool/ToolCollection/参数校验/工具序列化）
- `src/smolagents/models.py`（Model 抽象与全部 provider）
- `src/smolagents/memory.py`（MemoryStep 族/AgentMemory/CallbackRegistry）
- `src/smolagents/monitoring.py`（TokenUsage/Timing/Monitor/AgentLogger/LogLevel）
- `src/smolagents/local_python_executor.py`（AST 解释器与安全限制）
- `src/smolagents/remote_executors.py`（E2B/Docker/Modal/Blaxel）
- `src/smolagents/default_tools.py`、`src/smolagents/utils.py`（内置工具/常量/错误层次）
- `src/smolagents/prompts/{code_agent,structured_code_agent,toolcalling_agent}.yaml`（提示词模板）
- `docs/source/en/tutorials/secure_code_execution.md`（官方安全立场）
- `README.md`（定位主张）
