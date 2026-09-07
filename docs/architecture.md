# ECCS Agent 架构开发文档

> 版本：v0.1（设计稿）
> 适用范围：ECCS-Agent 项目整体架构（认知层 + 双层工具注册表 + 记忆系统）
> 状态：方案定稿，待开发

---

## 1. 项目定位与转型路径

开发路径已转向「**选品 + Listing 上架**」两个阶段（对应《电商流程与进销存管理表(2).xlsx》第三、四部分），面向**卖家工作台**。

- 产品形态：卖家工作台（选品工作台 / Listing 工作台）
- 技术底座：FastAPI + LangGraph + 多智能体 + 五模块记忆系统
- 用户：卖家自己（不再只是买家客服）

## 2. 三大分层总览

```
┌─────────────────────────────────────────────────────────────┐
│  core/   认知层：怎么想、怎么调度                               │
│  感知(输入/上下文) · 思考(ReAct/多智能体) · 调度(编排/双层注册表)  │
│  反思(复盘/技能提炼) · 输出(格式化/合规校验)                     │
├─────────────────────────────────────────────────────────────┤
│  agents/ + tools/  业务层：做什么（选品 / Listing / …）        │
│  业务子智能体只写业务逻辑，工具经【双层注册表】调用               │
├─────────────────────────────────────────────────────────────┤
│  memory/  记忆层：记得什么（短/长/知识库/状态/技能 + 权限）      │
│  所有记忆读写带 caller 鉴权，写操作可审计                        │
└─────────────────────────────────────────────────────────────┘
              三层只见接口，改动不跨层污染
```

---

## 3. 认知层 core/（五大认知模块 = 子智能体 + 工具）

> 设计原则：认知层大多是**子智能体**构成，每个模块内部自带子智能体与其局部工具；工具统一经双层注册表调度。

```
core/
├── __init__.py
├── perception/            # 一、感知（上下文管理 / 输入管理）
│   ├── context.py         #   上下文组装：短期窗口 + 长期 + 知识库索引 + 状态死规则
│   ├── input.py           #   输入管理：清洗/去重/意图初判/多语检测
│   └── session.py         #   谈话生命周期：开始/结束/触发一级总结
├── cognition/             # 二、思考推理
│   ├── react.py           #   ReAct 循环引擎（从 agents/base.py 提炼为通用引擎）
│   └── planner.py         #   多智能体协作：任务分解/合并/成果传递
├── dispatch/              # 三、调度控制器（编排层）
│   ├── orchestrator.py    #   编排器：意图路由 → 选子智能体 → 执行序
│   ├── registry.py        #   ★ 双层工具注册表（局部 + 全局）
│   └── dispatcher.py      #   工具路由智能体（模糊/多步工具链时才介入）
├── reflection/            # 四、自我反思
│   ├── reflector.py       #   反思循环：复盘失败 → 提炼技能记忆 → 改进
│   └── skill_writer.py    #   技能提炼（对接 memory/skill/）
└── output/                # 五、输出
    ├── formatter.py       #   输出格式化：卡片/表格/中日双语文案
    └── validator.py       #   输出校验：合规/不暴露内部JSON/不编造
```

---

## 4. 双层工具注册表（与 memory 权限体系对接）

### 4.1 设计决策

- **物理就近**：模块常用工具直接放进各自目录（感知→ core/perception/，业务→ tools/ 领域文件，反思 → core/reflection/）。
- **注册两处**：每个工具定义时，先注册到所属模块的**局部注册表**（模块内直连），再**同步注册进全局注册表**（跨模块调度/鉴权/审计）。
- **双重查找**：子智能体调用时先查局部注册表（高频、零路由开销），未命中再查全局（跨模块、低频）。
- **单元归属**：局部注册表由模块自管；全局注册表条目带 `owner` 字段，注销仅限 owner 或 L3。

### 4.2 数据结构

```python
# 全局注册表条目
{
    "name": "check_demand",
    "module": "tools.research",
    "fn": <callable>,
    "description": "验证关键词月搜索量与BSR…",
    "schema": {"keywords": "list[str]"},
    "level": "L0",            # 调用所需最低记忆权限等级
    "cost": "medium",          # 调用成本（估算 token / 外部 API）
    "scope": "global",         # 生效范围
    "owner": "tools.research", # 归属模块（注销校验）
}
```

### 4.3 注册与调用 API

```python
# 局部注册表定义（模块内直连）
research_registry = LocalRegistry("tools.research")

@research_registry.register(global_=True, name="check_demand",
                            description="…", schema={"keywords": "list[str]"},
                            level="L0", cost="medium")
def check_demand(keywords: list[str]) -> dict: ...

# 全局命中 / 局部未命中回退
result = registry.call("check_demand", {"keywords": [...]}, caller)
```

### 4.4 鉴权与审计集成

- 两路调用（局部直连 / 全局回退）都经过 `level` 校验（caller 权限 >= 工具所需最低等级）。
- 写操作级调用（如"写入技能记忆"）额外走 `memory/access.py` 的 `guard(module, op, caller)`。
- 审计：`memory_audit` 表记录工具名、调用方、参数摘要、结果状态，跨认知/业务/记忆三层统一留痕。

---

## 5. 业务层（agents/ + tools/）

```
agents/
├── __init__.py
├── supervisor.py            #（改）主控路由：选品 / Listing / 兜底 + 谈话结束编排
├── base.py                  #（不变）ReActAgentBase
├── research_agent.py        #【新】选品智能体：四步验证编排
├── listing_agent.py         #【新】Listing 智能体：草稿/合规/定价/配送
├── summarizer.py            #【新】总结智能体（一级/二级）
├── skill_writer.py          #【新】技能提炼/复盘智能体
├── customer_service.py      #（意向删除，先保留）
└── presales.py              #（意向删除，先保留）

tools/
├── __init__.py
├── registry.py              #（新）tools 域的局部注册表容器
├── catalog.py               #（不变）商品库
├── research.py              #【新】选品四步验证工具
├── supplier.py              #【新】供应商询价对比（演示 + 1688 槽位）
├── listing.py               #【新】Listing 草稿/图片合规/定价/FBA-FBM
├── order.py                 #（意向删除，先保留）
└── after_sales.py           #（意向删除，先保留）
```

业务子智能体：只写业务逻辑与提示词；一切工具调用经注册表 `registry.call`，不直接 import 其它模块的"执行函数"（除本地常量）。

---

## 6. 记忆层（memory/，详见 memory-system-design.md）

```
memory/
├── access.py            # 权限等级 / guard / 审计
├── manager.py           # MemoryManager 统一入口（聚合五模块 + 鉴权）
├── short_term/          # 谈话窗口 + 一级总结
├── long_term/           # 二级总结范式条目
├── knowledge/           # 知识库：索引→内容 两阶段
├── state/               # 状态记忆：死规则
└── skill/               # 技能记忆：事/的/痛/解
```

---

## 7. 请求处理流程（端到端）

```
用户输入
   │
   ▼
core/perception/input.py     输入清洗 + 意图初判 + 多语检测
   │
   ▼
core/perception/context.py   组装上下文（短期窗口+长期+知识库索引+状态死规则）
   │
   ▼
core/dispatch/orchestrator.py 意图路由 → 选子智能体（research/listing/兜底）
   │
   ▼
agents/research_agent.py     ReAct 循环（core/cognition/react.py）
   │   │  工具调用 → 本地注册表 → 全局注册表 → 鉴权+审计 → memory 读写
   │   ▼
core/reflection/reflector.py  失败复盘 → skill_writer → memory/skill
   │
   ▼
core/output/formatter+validator  格式化卡片/表格 + 合规校验
   │
   ▼
返回前端（卖家工作台）
```

---

## 8. 与《开发计划》的集成

| 阶段 | 原计划 | 本次架构追加 |
| --- | --- | --- |
| P0 | memory/access.py | + core/dispatch/registry.py（双层注册表骨架 + 与 access 对接） |
| P1-P3 | 短期窗口 + 两级总结 | 感知层 context.py 组装时调用短期窗口；总结 = 感知 session 触发 |
| P4 | 知识库 | 感知层 context 带知识库索引；检索走 registry |
| P5 | 状态记忆 | 上下文集成的死规则注入 |
| P6 | 技能记忆 | reflection/reflector.py + skill_writer.py 对接 |
| P7 | 集成 | dispatch/orchestrator.py 替换 supervisor 意图路由 |

---

## 9. 遗留决策（后续迭代确认）

1. ReAct 引擎从 agents/base.py 提炼到 core/cognition/react.py 后，旧 agent 是否全部切换（先切选品/Listing，客服暂留旧实现）。
2. 感知层意图初判与调度层编排器的职责边界——初判只打分，编排器最终决策。
3. 多层注册表（core 域 / tools 域 / memory 域）的父子层级深度，先按"局部=模块，全局=应用"两层。