# 选品（供应商寻找）与 Listing 创建上架 · 方案

> 对应经营链路阶段：**三、选品（在阿里系网站寻找供应商）**、**四、Listing 创建与上架**。
> 目标市场沿用项目定位：**日本**。本文档基于 2026-09-06 检索的公开资料整理，接口名称/限额以各平台官方文档为准。
> 设计原则与现有仓库约定保持一致：`agents/` 一人一智能体文件、`tools/` 共享、`config.py` 统一槽位、**无 Key 也能演示**（本地兜底）。

---

## 0. 现状盘点与路径调整

现有仓库已实现链路末端的**客服智能体**（`agents/customer_service.py` + `tools/` 演示工具 + supervisor 调度）。本次调整是在同一多智能体骨架上**向链路上游扩展**：

```
一/二（已有方向）  三、选品·供应商          四、Listing 创建与上架        五（已有）客服
市场调研   →    1688/阿里系找货源、      →   生成日语 Listing → 平台     →   客服智能体
（后续补）        比价、评估、定供应商        适配 → 审核 → 上架 → 同步      （customer_service）
                  【sourcing_agent】         【listing_agent】
```

三个智能体共用：`config.py` 的 LLM 槽位、`memory/` 的 checkpointer、`tools/` 目录、FastAPI `/api/ask` 与前端卡片协议（`{reply, intent, data}`）。**新增智能体 = agents/ 加一个文件 + supervisor 注册一行**，不碰客服已有代码。

---

## 1. 三、选品（供应商寻找）方案

### 1.1 数据源调研结论（三层，按可接入性排序）

| 层级 | 来源 | 接入条件 | 关键接口/方式 | 结论 |
|---|---|---|---|---|
| L1 演示层 | 内置演示供应商库（JSON） | 无 | `tools/` 本地数据 | **MVP 默认**，与现有"无 Key 兜底"风格一致，大创演示不断线 |
| L2 过渡层 | 第三方聚合数据 API（数据服务商） | 付费开通，无企业资质门槛 | REST 返回 1688 商品/店铺结构化数据 | 学生团队无营业执照时的折中 |
| L3 正式层 | **1688 开放平台**（open.1688.com） | 企业实名认证（营业执照，审核 1–3 工作日）；个人账号权限受限 | 关键字搜索 `alibaba.item.search`（2.0，支持起批量/价格区间/销量排序）、商品详情 `com.alibaba.product.get`（SKU/价格梯度/图集） | 正式路径；需 AppKey/AppSecret + OAuth2 access_token（30 天）+ MD5/HMAC-SHA1 签名 + **IP 白名单**；免费 QPS≤10（建议≤8），默认约 5000 次/日 |

> 明确排除网页爬虫方案：违反平台规则、易封 IP，不进入代码库。

### 1.2 选品与供应商评估模型

**流程**：关键词（中文，面向 1688）→ 搜索候选商品 → 逐商品取详情 → 供应商评估打分 → 输出推荐 TopN + 理由。

**供应商评分维度**（权重可在 config 调）：

| 维度 | 数据来源字段 | 说明 |
|---|---|---|
| 价格竞争力 | 批发价梯度、起批量 MOQ | 结合定价器反推毛利空间 |
| 供应能力 | 经营模式（生产厂家/经销）、销量/成交额 | 生产厂家优先 |
| 信誉 | 实力商家/深度验厂标识、复购率、服务评分 | 平台背书字段 |
| 跨境适配 | 一件代发、跨境专供、现货率、发货时效 | 无货源模式刚需 |
| 合规风险 | 品牌词/图片侵权初筛（关键词黑名单） | 上架前拦截，避免下架罚款 |

输出物：`SupplierReport`（供应商卡片：名称、价格梯度、MOQ、评分、理由、风险标记）。

### 1.3 模块设计（贴合现有结构）

```
agents/sourcing.py              # 选品智能体（LangGraph ReAct，一人认领）
tools/sourcing_1688.py          # L1 演示库 + L3 官方 API 客户端（签名/白名单/限流/重试）
tools/supplier_score.py         # 评分模型（纯函数，可单测）
```

- 智能体 prompt 约定：先调 `search_suppliers(keyword)` 再调 `get_offer_detail(offer_id)`，最后 `score_suppliers()` 生成对比结论；禁止编造价格/MOQ。
- API 未配置（无 AppKey）时自动降级到演示库——与客服智能体 `_HAS_LANGGRAPH` 同款降级模式。
- 前端复用卡片协议：新增 `intent="sourcing"`，渲染供应商对比卡（参照现有订单卡/推荐卡）。

---

## 2. 四、Listing 创建与上架方案

### 2.1 目标平台调研结论（日本市场，按学生团队可接入性排序）

| 平台 | 出店/开发者门槛 | 上架接口 | 适配优先级 |
|---|---|---|---|
| **Qoo10**（eBay Japan 运营） | 出店门槛低；QSM 后台直接申请 API キー | `ItemsBasic.SetNewGoods` 商品登记；认证キー每小时失效，需先调 `CreateCertificationKey` | ★ 首选（真实打通第一家） |
| **Yahoo!ショッピング** | 出店免费；YConnect OAuth，部分 API 权限审批约 1 周 | 商品登録 API（REST/JSON）+ `uploadItemFile` CSV 批量上传 | ★ 第二家 |
| **Amazon JP** | 专业卖家（月费）+ SP-API 开发者注册 | Listings Items API + **Product Type Definitions API**（JSON Schema 驱动校验，最值得学习的范式）+ JSON_LISTINGS_FEED 批量 | 中期目标 |
| **楽天市場** | 出店费用高（初期+月租），学生不现实 | RMS WEB API（serviceSecret + licenseKey，Item API insert/update） | 仅留适配器接口，不实际接入 |

**共性工作流**（各家一致，抽象成统一管线）：素材准备 → 类目映射 → 标题/描述生成（日语）→ 合规校验 → 提交（草稿）→ 发布 → 状态回查。

**业界参照**（店小秘/通途/马帮等 ERP 的成熟能力，作为功能对标）：一键采集→资料库→多平台刊登模板、AI 生成标题/五点/详情、多语言翻译、图片白底/去水印、违禁词与仿品检测、售价估算、上架失败清单。

### 2.2 Listing 生成（LLM 为核心差异化）

输入：选品阶段锁定的 1688 商品（中文标题、属性、价格、图）+ 目标平台。
生成（一次 LLM 调用 + 结构化输出）：

1. **日语标题**：按平台长度限制（如 Qoo10 200 字符、Yahoo 全角限制），前置核心关键词；
2. **卖点五条 / 详情描述**：敬体（です・ます調），符合日本电商文案习惯；
3. **搜索关键词**：日语词 + 罗马音 + 中文原词对照；
4. **类目建议**：候选类目代码（提交前人工确认）；
5. **建议售价**：成本（1688 价 + 国际物流 + 平台佣金）× 汇率缓冲 × 目标利润率，定价器纯函数计算；
6. **合规自检**：违禁词/品牌侵权词黑名单扫描，命中即标记 `risk`，阻止自动上架。

### 2.3 上架管线与状态机

```
draft（LLM 生成草稿）
  → validated（schema 校验 + 合规自检通过）
  → reviewing（人工确认：演示/比赛场景必须有此闸口）
  → publishing（调平台适配器）
  → published / failed（记录平台返回的错误清单，支持整改重发）
  → syncing（定期回查线上状态/价格/库存）
```

**PlatformAdapter 抽象**（工具层，新增平台 = 加一个文件）：

```
tools/platforms/base.py    # Protocol: publish(draft)->job_id / status(job_id)->状态 / update / withdraw
tools/platforms/mock.py    # 演示适配器（默认）：模拟提交与回执，保证无店铺也能完整演示
tools/platforms/qoo10.py   # Qoo10：认证キー获取 → SetNewGoods → 状态回查
tools/platforms/yahoo.py   # 预留
tools/platforms/amazon.py  # 预留（JSON Schema 校验是重点）
```

### 2.4 模块设计

```
agents/listing.py               # Listing 智能体：生成→校验→(经人工确认后)上架，一人认领
tools/listing_gen.py            # 生成 prompt 与结构化输出解析（标题/五点/关键词/类目/售价）
tools/pricing.py                # 定价器（成本+佣金+汇率+利润率，纯函数）
tools/compliance.py             # 违禁词/侵权词黑名单扫描
tools/platforms/                # 平台适配器（见上）
```

- 前端新增 `intent="listing"` 卡片：展示生成的标题/五点/售价/风险标记，按钮"确认上架/重新生成"（对应 reviewing 闸口）。
- `config.py` 扩展槽位（全部只读 `.env`，遵守仓库密钥约定）：`ALIBABA_APP_KEY/SECRET/ACCESS_TOKEN`、`QOO10_USER/PWD/API_KEY` 等。

---

## 3. 里程碑与分工（README 已约定三人三分支、一人一智能体文件）

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M1 演示闭环**（1–2 周） | 数据模型 + 演示供应商库；sourcing/listing 两智能体骨架；LLM 生成日语 Listing；mock 适配器走通 草稿→确认→"上架"；UI 两张新卡片 | 无任何真实 Key，全程可演示（比赛演示场景） |
| **M2 真实打通**（1–2 周） | Qoo10 店铺申请 + `qoo10.py` 适配器真实上架 1 个 SKU；1688 侧按资质走 L2（聚合 API）或 L3（企业认证） | 真实店铺后台能看到 AI 生成的商品 |
| **M3 运营增强** | 供应商评分调权、定价器校准、批量生成/批量上架、失败清单重发、Yahoo 适配器 | 一次关键词 → N 个候选 → 批量上架报告 |

分工建议：A 认领 `agents/sourcing.py` + 1688 工具；B 认领 `agents/listing.py` + 生成/定价/合规工具；C 认领平台适配器 + UI 卡片。Git 冲突面与现有约定一致。

## 4. 风险与合规

1. **资质风险**：1688 正式 API 需企业认证——学生团队先 L1/L2，比赛展示以"架构可插拔"为亮点；
2. **平台规则**：Qoo10 认证キー每小时轮换需自动刷新；Yahoo 部分权限审批慢，M2 只承诺 Qoo10；
3. **侵权风险**：生成内容必须过 `compliance.py` 黑名单 + 人工 reviewing 闸口后才允许真实发布（fail-closed，参照 harness 研究的审批默认拒绝原则）；
4. **密钥安全**：所有平台凭证进 `.env`，`.env.example` 只放占位符，push 前按 README 安全约定核对。

## 5. 参考资料

- 1688 开放平台接入与签名/限流实践：<https://blog.csdn.net/WBKJ_Noah_/article/details/146319159>、<https://www.cnblogs.com/API-19970108110/p/19714577>
- Amazon SP-API Listings 工作流：<https://developer.amazonservices.com/solutions-automate-listing-management-on-amazon>、<https://developer-docs.amazon.com/sp-api/docs/manage-product-listings-guide>
- Qoo10 商品登记 API：<http://api.qoo10.jp/GMKT.INC.Front.OpenApiService/APIList/SetNewGoods.aspx>、<https://qiita.com/Mikeinu/items/eef5b88c5e12cc40c34d>
- Yahoo!ショッピング 商品登録/CSV 上传：<https://developer.yahoo.co.jp/webapi/shopping/editItem.html>
- 楽天 RMS API 封装示例：<https://github.com/t4traw/rms_api>
- 业界 ERP 刊登能力对标：<https://help.dianxiaomi.com/article/orderManagement/1355>、<https://www.tongtool.com/listing.html>
