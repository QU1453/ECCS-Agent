# ECCS Agent 记忆系统开发文档

> 版本：v0.1（设计稿）
> 适用范围：ECCS-Agent 项目的 memory/ 与 agents/ 模块改造
> 状态：方案定稿，待开发

---

## 1. 背景与目标

现有记忆系统只有「短期（SqliteSaver + 消息条数压缩）」和「长期（facts + 文档分块 + ANN 召回）」两层，无法支撑卖家工作台多阶段、多智能体协作的诉求。本文档将记忆体系重构为 **五大模块 + 分层总结管线 + 权限体系**：

| 模块 | 一句话定义 |
| --- | --- |
| 短期记忆 | 最近 K 次谈话的原文窗口（默认 5 次，可调高），全部塞进 LLM 上下文 |
| 长期记忆 | 二级总结产出的范式化条目（用户画像 / 关键事实 / 未完成事项…） |
| 知识库 | 大批有用文件/资料，**索引先行**两阶段检索：先看索引简述 → 再取所需正文 |
| 状态记忆 | 每次必须注入 LLM 的**死规则**，只能由高权限 agent / 用户写入 |
| 技能记忆 | 「事情 / 目的 / 痛点 / 解法」四要素，应对 LLM 高频难点，由专门 agent 写入 |

核心变化：**记忆不再按"消息条数"压缩，而是按"谈话"为单位做分层总结接力**——原文窗口只保留最近 K 次谈话，更早的谈话被一级总结 → 二级总结逐层提炼后进入长期记忆，原文可丢弃。

---

## 2. 体系总览

```
                          ┌─────────────────────────────────────────────┐
                          │              权限体系（第 6 章）              │
                          │  L0 普通智能体 / L1 总结·上传 / L2 专业·提炼   │
                          │  L3 管理 / L9 人类（写审计，全操作留痕）        │
                          └─────────────────────────────────────────────┘
                                            │ 所有读写都经过鉴权
  ┌───────────────┐     对话结束触发         ┌──────────────────────────────┐
  │  对话（谈话）  │ ──────────────────────► │ 一级总结（专职总结智能体）        │
  │  session_id   │  原文 + 一级总结          │ 范式 JSON，保留细节              │
  └───────────────┘                          └──────────────┬───────────────┘
        │  最近 K=5 个对话的原文                             │ 每 M=5 个对话触发
        │  全部塞进上下文窗口                                 ▼
        ▼                                          ┌──────────────────────┐
  ┌───────────────┐                               │ 二级总结（滚动合并）      │
  │   短期记忆     │                               │ 废无用信息，留关键信息    │
  │ （本次必带）   │                               └──────────┬───────────┘
  └───────────────┘                                          ▼
                                                 ┌──────────────────────┐
   ┌──────────────┐                             │      长期记忆          │
   │  知识库       │◄── 对话中大批有用文件入库      │  范式化条目（facts 扩展）│
   │ 索引→内容     │                              └──────────────────────┘
   │ 两阶段检索    │
   └──────────────┘        ┌──────────────┐     ┌──────────────────────┐
                           │  状态记忆      │     │  技能记忆             │
                           │ 死规则·每次注入 │     │ 事/的/痛/解·反思入库   │
                           │ L3 写入       │     │ L2 专门 agent 写入    │
                           └──────────────┘     └──────────────────────┘
```

---

## 3. 各模块详细设计

### 3.1 短期记忆：最近 K 次谈话的上下文窗口

- **单位**：以「谈话」（= 一次会话 session_id）为记忆粒度，不再按消息条数。
- **窗口**：默认 `K = 5` 个最近谈话的 **原文 + 各自一级总结**，全部塞进上下文窗口；K 可配置调高（5 → 8 → 10）。
- **Token 守卫**（设计补充建议 #1）：5 个谈话原文可能超限。组装时估算 token，超 `CONTEXT_TOKEN_GUARD`（默认 24000）时按「最新优先」整段丢弃最旧谈话，并在上下文头部打标 `[已省略更早谈话 n 次]`；**先丢原文、绝不丢一级总结**（总结体积小、信息密度高）。
- **存储**：继续复用 LangGraph `SqliteSaver`（thread_id = `session:{id}`），新增 `conversation_registry` 表管理「谈话生命周期」（开始/结束/状态/一级总结归属）。
- 谈话结束的判定（触发总结）：用户显式结束 / 开启新谈话 / 超过空闲时长（UI 按钮或 `end_conversation` API）。

### 3.2 长期记忆：二级总结产出的范式化条目

- **一级总结**（对话结束后立即执行，保留细节）：由**专职总结智能体**（`agents/summarizer.py`，权限 L1）按固定范式输出 JSON（见 4.2）。
- **二级总结**（每 `M = 5` 个谈话执行一次，默认间隔可配）：把最近 M 个一级总结**滚动合并**，废除无用信息（闲聊、重复、已解决旧事），只保留关键信息，按固定范式写入长期记忆。
- **关键信息的保留口径**（v0.1 默认规则，细则后续迭代）：用户画像、长期偏好、未完成事项、反复出现的关键事实、重要决策与理由、产出物引用（表格/文档 ID）。
- **条目标配**：`confidence` 置信度、`source_conversations` 来源谈话 ID 列表，可回溯。

### 3.3 知识库：索引先行，两阶段检索

对话过程中用户/流程产生的大批有用文件（1688 页面、竞品 Listing、政策文档等）入库时**分块并自动生成索引**：

1. **入库**：长文本分块（沿用 `chunker`）→ 每块由 LLM 生成**索引条目**（1–2 句大致描述 + 关键词 + 所属文档 + 块长度）。
2. **检索（两步走，Agent 用索引省 token）**：
   - `get_index(user_id, filter)` → 只返回索引（brief/keywords/title），agent **先读索引**，分析哪些块相关；
   - `fetch_knowledge(chunk_ids)` → 只取被选中的块全文，组装上下文。
3. 现有 ANN `recall` 语义召回 **保留作为索引粗筛加速**（先 ANN top-n 索引 → agent 精选 → 取正文）；无嵌入条件时降级为「全量索引列表 + 关键词过滤」。

### 3.4 状态记忆：死规则，每次必注入

- **定义**：必须**每次**向 LLM 记录、不可遗漏的铁律。例如：不得编造订单号、回复跟随用户语言、不得暴露工具内部 JSON、不得读写本机 C 盘、密钥不入库。
- **写入权限**：仅 **L3（高权限 agent / supervisor）/ L9（用户）** 可写、修改、启停；普通智能体只能被动接收。
- **注入方式**：组装上下文时，把所有 `enabled=True` 且 `scope` 匹配（见 6 章）的规则拼成「铁律」块，置于 system prompt 固定位置。
- **scope 分组**（设计补充建议 #2）：规则可声明作用于 global / 指定 agent 类型 / 指定用户，避免无关规则污染各专项智能体的上下文。

### 3.5 技能记忆：事 / 的 / 痛 / 解

- **四要素范式**：

  ```json
  {
    "situation": "事情/场景（一句话描述遇到什么情况）",
    "goal": "目的（当时想达成什么）",
    "pain": "痛点（卡在哪里、什么难点）",
    "solution": "解法（最终如何解决）",
    "tags": ["关键词"],
    "trigger": "触发条件（什么情况下该命中此技能，可空）"
  }
  ```

- **写入**：由**专门的技能提炼智能体**（复盘/反思 agent，权限 L2）从失败会话、agent 求助记录中提炼写入；supervisor 授权后也可手动入库。
- **使用**：agent 遇难点时 `search_skills(描述)` 检索 top-k；`successes+评分` 高的**热技能**默认预注入 top-3（`SKILL_HOT_INJECT_TOP`）。
- **反馈闭环**（设计补充建议 #3）：技能被采用后回报“成功/失败”，更新 `successes/failures/score`，连续失败自动降级、归档；有效技能晋升预注入名单。

---

## 4. 分层总结管线

### 4.1 触发时机

```
谈话结束 ──► 一级总结（立即，专职总结智能体）
每累计 M=5 个未二级总结的一级总结 ──► 二级总结（滚动合并）──► 长期记忆
```

### 4.2 一级总结范式（保留细节，供 K 窗口内原文替代与二级总结输入）

```json
{
  "conversation_id": "session:xxx",
  "user_id": "u1",
  "time_range": "2026-09-03 10:00 ～ 10:32",
  "topic": "对话主题（一句话）",
  "user_requests": ["诉求1", "诉求2"],
  "key_facts": [{ "k": "订单号", "v": "2026081200012" }],
  "decisions": ["结论/决定…"],
  "pending_items": ["未完成事项…"],
  "entities": ["涉及的商品/供应商/文档"],
  "preferences": ["情绪与偏好观察"],
  "artifacts": ["产出物引用：表格名/文档ID"],
  "tags": ["退货", "日本站"]
}
```

### 4.3 二级总结范式（写入长期记忆）

```json
{
  "entry_type": "user_profile | fact | pending_item | preference",
  "user_id": "u1",
  "content": "精炼后的关键信息正文",
  "confidence": 0.0,
  "source_conversations": ["session:1", "session:2"],
  "tags": [],
  "status": "active"
}
```

### 4.4 时序示例

```
谈话1..5 结束 → 各出一级总结（细节保留，原文在窗口内）
第5次谈话结束 → 一级总结5完成 → 触发二级总结(1..5) → 长期记忆 +1 条画像/待办
谈话6 开始 → 短期窗口 = 谈话2..6 原文（谈话1 原文丢弃，由二级总结接力）
谈话10 结束 → 二级总结(6..10) → 长期记忆 +2（滚动，不重复）
```

---

## 5. 与现有代码的映射（改造点）

| 现有实现 | 升级为 | 动作 |
| --- | --- | --- |
| `memory/short_term/memory.py`（按消息条数压缩） | 按「谈话」为粒度的窗口组装 | 改造：新增 conversation_registry、K 窗口组装、token 守卫 |
| `memory/short_term/compress.py` | （保留作窗口内兜底） | 保留：单谈话内部超长时仍可裁剪 |
| `memory/long_term/memory.py` 的 facts | 长期记忆范式化条目 | 扩展：新增 `long_term_entries` 表 |
| `memory/long_term/` 的 documents/chunks + ANN | 知识库索引先行 | 改造：新增 `kb_index` 表 + `get_index` / `fetch_knowledge` |
| 无 | 状态记忆 | 新增 `memory/state/`：死规则表 + 注入器 |
| 无 | 技能记忆 | 新增 `memory/skill/`：四要素表 + 检索 + 反馈 |
| 无 | 权限体系 | 新增 `memory/access.py`：等级校验 + 审计表 |
| `agents/supervisor.py` | 挂接新智能体 | 改造：注册总结智能体、技能提炼智能体、结束谈话路由 |
| `memory/manager.py` | 五模块统一入口 | 改造：MemoryManager 聚合五大模块 + caller 鉴权 |

目标目录结构：

```
memory/
├── access.py            # 权限体系（等级 / 校验 / 审计）
├── manager.py           # 统一入口（改造）
├── short_term/          # 谈话窗口 + 一级总结（改造）
├── long_term/           # 长期记忆范式条目（扩展）
├── knowledge/           # 知识库：索引→内容 两阶段（新增）
├── state/               # 状态记忆：死规则（新增）
└── skill/               # 技能记忆：事/的/痛/解（新增）
agents/
├── summarizer.py        # 专职总结智能体（一级 + 二级，新增）
├── skill_writer.py      # 技能提炼/复盘智能体（新增）
└── supervisor.py        # 路由与谈话结束编排（改造）
```

---

## 6. 权限体系

### 6.1 等级定义

| 等级 | 身份 | 能力概述 |
| --- | --- | --- |
| L0 | 普通对话智能体（客服/售前/选品/Listing） | 读自己会话 + 知识库 + 技能；不得持久化写他人模块 |
| L1 | 总结智能体、上传/入库管道 | + 写长期记忆条目、写知识库 |
| L2 | 技能提炼智能体、复盘智能体 | + 写/改技能记忆、技能晋升降级 |
| L3 | 管理智能体（supervisor）、受权高权限 agent | + 写/改状态记忆、删除/修正各模块数据 |
| L9 | 人类用户 | 全部权限 + 审计查看 |

### 6.2 读写矩阵

| 模块 | 读 | 写 | 改/删 |
| --- | --- | --- | --- |
| 短期记忆 | L0（仅本人会话） | L0（仅本人会话） | L0 本人 / L9 |
| 长期记忆 | L0（按 user 分区） | L1（总结管线） | L3 / L9 |
| 知识库 | L0（先索引后内容） | L1（入库管道） | L3 / L9 |
| 技能记忆 | L0（检索） | L2（专门 agent） | L2（晋升降级）/ L3 |
| 状态记忆 | 全量自动注入（不可选读） | L3 | L3 / L9 |

### 6.3 鉴权与审计

- 所有记忆 API 调用携带 `caller = MemoryCaller(agent_name, level, session_id)`；写操作先过 `access.guard(module, op, caller)`。
- 默认拒绝，显式授权；越权即记审计并抛错。
- `memory_audit` 表记录：时间、actor、level、action、module、target_id、session_id、result。

---

## 7. 数据表结构草案（SQLite）

```sql
-- 谈话注册表（短期记忆生命周期）
conversation_registry(
  session_id TEXT PRIMARY KEY, user_id TEXT, status TEXT,       -- open / closed / summarized
  started_at TEXT, ended_at TEXT,
  summary_json TEXT,                    -- 一级总结范式 JSON
  rolled_up INTEGER DEFAULT 0           -- 是否已参与二次总结
);

-- 长期记忆范式条目
long_term_entries(
  id INTEGER PRIMARY KEY, user_id TEXT, entry_type TEXT,
  content TEXT, confidence REAL, source_conversations TEXT,     -- JSON 数组
  tags TEXT, status TEXT, created_by TEXT, created_at TEXT
);

-- 知识库索引（每块一条简述）
kb_index(
  id INTEGER PRIMARY KEY, doc_id INTEGER, chunk_id INTEGER,
  brief TEXT, keywords TEXT, title TEXT, created_by TEXT, created_at TEXT
);

-- 状态记忆：死规则
state_memory(
  id INTEGER PRIMARY KEY, rule_text TEXT, scope TEXT,          -- global / agent_type / user
  agent_types TEXT, priority INTEGER, enabled INTEGER DEFAULT 1,
  created_by TEXT, updated_at TEXT
);

-- 技能记忆：事/的/痛/解
skill_memory(
  id INTEGER PRIMARY KEY, situation TEXT, goal TEXT, pain TEXT, solution TEXT,
  tags TEXT, trigger TEXT, successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0,
  score REAL DEFAULT 0, status TEXT, created_by TEXT, updated_at TEXT
);

-- 记忆审计
memory_audit(
  id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, actor_level TEXT,
  action TEXT, module TEXT, target_id TEXT, session_id TEXT, result TEXT
);
```

---

## 8. 新增配置槽（config.py）

| 槽位 | 默认 | 说明 |
| --- | --- | --- |
| `SHORT_TERM_CONVERSATIONS` | 5 | 短期窗口内的谈话数 K（可调高 8/10） |
| `L2_SUMMARY_INTERVAL` | 5 | 每 M 个谈话触发二级总结 |
| `CONTEXT_TOKEN_GUARD` | 24000 | 窗口组装 token 上限，超限裁剪最旧原文 |
| `STATE_MEMORY_INJECT` | true | 死规则注入开关 |
| `SKILL_HOT_INJECT_TOP` | 3 | 热技能预注入条数 |
| `SUMMARIZER_MODEL` | = MODEL_ID | 总结智能体模型（默认 glm-5.3-flash） |

---

## 9. 开发计划（阶段拆分）

| 阶段 | 内容 | 产出 | 验收标准 |
| --- | --- | --- | --- |
| P0 | 权限层 | `memory/access.py` + 审计表 + manager 鉴权 | 越权写入被拒且留审计 |
| P1 | 谈话注册 + 短期窗口 | conversation_registry + K 窗口组装 + token 守卫 | 5 谈话原文正确塞入/裁剪 |
| P2 | 一级总结 | `agents/summarizer.py` + 对话结束触发 | 产出合规范式 JSON |
| P3 | 二级总结 → 长期记忆 | M 间隔滚动合并 + long_term_entries | 第 5/10/15 次谈话后条目正确落库 |
| P4 | 知识库索引 | kb_index 生成 + get_index / fetch_knowledge | 先索引后内容两阶段跑通 |
| P5 | 状态记忆 | state_memory + 注入器 + L3 写 API | 死规则每次进上下文、低权限写入被拒 |
| P6 | 技能记忆 | skill_memory + `agents/skill_writer.py` + 反馈闭环 | 提炼/检索/晋升降级闭环 |
| P7 | 集成 | supervisor 路由 + 结束谈话编排 + UI 联动 | 卖家工作台全链路可演示 |
| P8 | 收尾 | demo.py 扩展 + 文档同步 + 推送（密钥检查） | 演示全过、分支推送 |

---

## 10. 待定问题（后续迭代）

1. 二级总结「关键信息 vs 无用信息」的精确判定规则 —— 先按 3.2 默认口径，积累案例后细调。
2. K 与 M 的最优取值 —— 以 token 实测校准（K=5、M=5 起步）。
3. 索引简述由嵌入模型廉价款还是总结 LLM 生成 —— 先走总结 LLM（质量优先），量大再切嵌入。
4. 多用户/多站点（美/日）下的长期记忆分区策略 —— 按 user_id 分区，站点作为 tags。

---

## 11. 设计补充建议（相对原始需求的增强）

1. **Token 守卫**：5 轮原文可能超窗，必须自适应裁剪「先丢原文、不丢总结」。
2. **状态记忆 scope 分组**：死规则按 global/agent/用户分组注入，避免污染专项智能体上下文。
3. **技能记忆反馈闭环**：加上使用成败回报 → 晋升/降级机制，否则技能库会越写越烂。
4. **范式校验器**：一级/二级总结统一 JSON 输出，入库前做 schema 校验，坏产出回退不落库。
5. **原文的可追溯保留**：二级总结后原文不销毁而是标记 `rolled_up`，进入冷存储（仍可审计回查），仅从"上下文窗口"退役。