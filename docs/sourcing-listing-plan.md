# 选品 & Listing 上架智能体 · 方案（v2，以《电商流程与进销存管理表》为准）

> 方向已转型：目标 = 表格「电商流程」Sheet 的 **三、选品（阿里等网站寻找供应商）** 与 **四、Listing 创建与上架** 两个阶段，
> 市场 = **亚马逊美国站**（表格 A14"自动选品、上架智能体：美国为例"）。此前按日本市场（Qoo10/乐天/雅虎）的调研作废。
> 工程约定不变：`agents/` 一人一文件 + supervisor 注册、`tools/` 共享、`config.py` 槽位、**无 Key 也能演示**。

---

## 0. 全链路定位（表格蓝图 → 智能体分工）

| 表格阶段 | 内容 | 智能体 | 状态 |
|---|---|---|---|
| 一、开店 / 二、账户注册 | 站点选择、注册、审核 | —（人工前置条件，不做） | 假设已完成 |
| **三、选品** | 需求/竞争/利润/供应链四步验证 | **sourcing_agent（本次新建）** | ★ 本次 |
| **四、Listing 创建与上架** | 创建 Listing、定价、配送方式、上架 | **listing_agent（本次新建）** | ★ 本次 |
| 五、FBA 发货 | 货件计划、贴标、头程 | 后续 logistics_agent | 暂不做 |
| 六、订单管理与售后 | 进销存台账、库存预警、补货、售后 | 后续 logistics_agent；**已有客服智能体覆盖售后** | 部分已有 |
| 七、结算与回款 | DD+7、结算、对账 | 后续 finance_agent | 暂不做 |

表格 A 列还定义了远景：自动宣传智能体（按选品定期生成卖点/促销视频 → TikTok/YouTube 发布并挂网店链接）——属四之后的长尾，记入 Roadmap 不进本次范围。

---

## 1. 三、选品智能体（sourcing_agent）

### 1.1 业务流程 = 表格的四步验证流水线（阈值直接写死为判定规则）

```
关键词/品类想法
 → ① 需求验证：关键词月搜索量 ≥ 3000，否则淘汰
 → ② 竞争验证：首页前10名 平均评分 ≤ 4.3 且 平均评论数 ≤ 500，否则淘汰
 → ③ 利润验证：FBA 口径净利润率 ≥ 30%（采购+头程+FBA费+佣金+广告+退货+仓储全计入）
 → ④ 供应链验证：1688/工厂询价，确认 MOQ 与交期，首批 50–100 件试水
 → 输出：选品分析表 + 竞品分析表 + FBA利润计算器 + 供应商对比表（四张 Excel 产物）
```

每一步产出一个**结构化判定（pass/fail + 数据 + 理由）**，任何一步 fail 即终止并说明原因——这就是智能体的决策骨架，也是答辩时最好讲的故事："表格里的经验阈值，变成了智能体的硬规则"。

### 1.2 数据源分层（每步独立降级，无 Key 全演示模式可跑）

| 步骤 | L1 演示层（默认） | L2 过渡层 | L3 真实层 |
|---|---|---|---|
| ① 需求验证 | 内置关键词库（搜索量/趋势为演示数据） | 卖家精灵/Jungle Scout 后台导出 CSV 导入 | Jungle Scout API / Helium 10（付费 SaaS，无免费官方源，真实阶段以导出导入为主） |
| ② 竞争验证 | 内置竞品快照 | 同上 CSV 导入 | SP-API Catalog Items（类目/排名；评论数无官方接口，仍以导出为准） |
| ③ 利润验证 | 内置费率表（佣金%/FBA 配送费按尺寸段） | 同左，费率表随官方更新 | **SP-API Product Fees API**（getMyFeesEstimates，有卖家账号即可真实调用） |
| ④ 供应链验证 | 内置供应商库 | 第三方聚合 API（无资质门槛） | 1688 开放平台（企业认证，`alibaba.item.search` + `com.alibaba.product.get`，签名+IP 白名单+QPS≤8） |

> 诚实声明：关键词搜索量与竞品评论数**没有免费官方 API**，行业事实就是买 SaaS 或导出。方案不假装能全自动抓——演示层先行，真实层以"导出 → 导入 → 智能体分析"闭环，这在大创答辩里是合理且站得住的。

### 1.3 模块设计

```
agents/sourcing.py            # 选品智能体：四步流水线编排 + 判定 + 产出四张表
tools/research_demand.py      # ①需求验证（演示库/CSV 导入，统一 search_volume(keyword) 接口）
tools/research_competition.py # ②竞争验证（同上形态）
tools/profit_calc.py          # ③FBA 利润计算器（纯函数：成本项全展开 → 净利率；费率表内置可更新）
tools/supplier_1688.py        # ④1688：演示库 / 聚合 API / 官方 API 三模式客户端 + 供应商对比打分
tools/excel_report.py         # 四张表的 Excel 导出（openpyxl，模板对齐表格定义列）
```

## 2. 四、Listing 智能体（listing_agent）

### 2.1 业务流程（对齐表格三步 + 上架）

```
选品锁定的 1688 货源（中文素材 + 图片 + 采购价）
 → ① 创建 Listing：LLM 生成英文标题/五点/描述/搜索词；UPC/EAN 校验；主图白底校验
 → ② 设置价格：竞品价带 × profit_calc 反推，给出售价/促销价建议
 → ③ 配送方式：FBA vs FBM 对比（资金占用/时效/新手友好度）给出建议
 → 人工确认闸口（必须）
 → SP-API 上架：Product Type Definitions 取 JSON Schema → 校验 → Listings Items 提交
 → 状态回查 → 失败清单整改重发
输出：产品信息表 + 定价策略表 + 物流方式对比表（三张 Excel 产物）
```

### 2.2 关键规则（来自表格，写进生成与校验逻辑）

- **UPC/EAN 必备**：无码 → 提示 GS1 购买或申请 GTIN 豁免，阻断上架；
- **主图纯白底**：图片校验工具（白底占比检测）不过则标记 risk；表格提示 2026 起有"主图真实性校验"，校验器按从严处理；
- **定价**：净利润率仍锚定 ≥30%，定价器与选品阶段共用 `profit_calc.py`（单一事实源）；
- **FBA/FBM**：默认建议"新手测试走 FBM 小批量，验证后转 FBA"（与表格关注事项一致）。

### 2.3 平台适配（Amazon SP-API 唯一主目标）

| 能力 | 接口 | 备注 |
|---|---|---|
| 上架要求查询 | Product Type Definitions API | 按 productType 返回 JSON Schema——**schema 驱动校验**是本阶段技术亮点 |
| 创建/更新 Listing | Listings Items API (v2021-08-01) | SKU 级提交，支持图片 URL |
| 批量 | JSON_LISTINGS_FEED | 后续批量阶段 |
| 费用预估 | Product Fees API | 与 ③ 利润验证共用 |
| 状态/错误 | Listings Items + Notifications | 失败清单来源 |

前置条件（诚实清单）：专业销售计划 $39.99/月 + SP-API 开发者注册 + LWA 授权；**学生团队无店铺时走 SP-API 静态沙箱 + mock 适配器**，演示不受影响。

```
agents/listing.py             # Listing 智能体
tools/listing_gen.py          # LLM 英文文案生成（标题≤200字符等规则内嵌 prompt）+ 结构化输出解析
tools/pricing.py              # 定价策略（复用 profit_calc，加竞品价带）
tools/image_check.py          # 主图白底/尺寸校验（PIL，纯本地）
tools/compliance.py           # 违禁词/侵权词黑名单 + UPC 格式校验
tools/platforms/base.py       # PlatformAdapter 协议：publish/status/update/withdraw
tools/platforms/mock.py       # 演示适配器（默认）
tools/platforms/amazon.py     # SP-API 适配器（沙箱先行）
tools/excel_report.py         # 三张表导出（与选品共用）
```

上架状态机沿用 v1：`draft → validated → reviewing(人工闸口) → publishing → published/failed → syncing`，**真实发布必须过人工闸口（fail-closed）**。

## 3. 工程整合（不动已有代码）

- supervisor 注册两个新智能体，意图路由按关键词分流（选品词 → sourcing，上架/listing 词 → listing），客服原样保留；
- UI 复用 `{reply, intent, data}` 卡片协议，新增 `intent="sourcing"`（四步验证卡：每步 pass/fail+数据）与 `intent="listing"`（文案+定价+风险标记卡）；
- Excel 产物落盘 `outputs/`（新增目录，.gitignore 忽略），前端给下载链接；
- `config.py` 新增槽位（全部只读 .env）：`ALIBABA_APP_KEY/SECRET/ACCESS_TOKEN`、`AMAZON_REFRESH_TOKEN/CLIENT_ID/CLIENT_SECRET`、SaaS 导出目录路径。

## 4. 里程碑与分工

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M1 演示闭环**（1–2 周） | 两个智能体骨架 + 全 L1 演示数据；关键词 → 四步验证报告（四张表）→ Listing 草稿（三张表）→ mock 上架；两张 UI 卡 | 零 Key 全流程可演示 |
| **M2 半真实**（1–2 周） | SP-API 沙箱打通上架；Product Fees API 若有卖家账号则真实；1688 走 L2 聚合 API；CSV 导入通道 | 沙箱可见提交回执；导入真实导出数据后报告真实 |
| **M3 运营增强** | 批量选品/批量上架、失败清单重发、费率表更新机制、（可选）自动宣传智能体 POC | 一次品类词 → N 候选 → 批量上架报告 |

分工：A = sourcing_agent + ①②④ 工具；B = listing_agent + 生成/定价/合规/图片工具；C = SP-API 适配器 + Excel 导出 + UI 卡片。

## 5. 风险与合规

1. **数据可得性**：搜索量/评论数无免费官方 API——已用"L1 演示 + 导出导入"化解，不承诺全自动抓取；
2. **资质**：1688 官方 API 需企业认证；亚马逊需真实店铺——M1/M2 均不依赖，M2 只做沙箱；
3. **侵权**：生成文案过黑名单 + 人工闸口后才允许真实发布；
4. **密钥**：全部进 .env，遵守仓库 push 前核对约定。

## 6. 参考资料

- Amazon SP-API Listings 工作流：<https://developer.amazonservices.com/solutions-automate-listing-management-on-amazon>、<https://developer-docs.amazon.com/sp-api/docs/manage-product-listings-guide>
- SP-API Product Fees（利润验证）：<https://developer-docs.amazon.com/sp-api/docs/product-fees-api-v0-use-case-guide>
- 1688 开放平台接入：<https://blog.csdn.net/WBKJ_Noah_/article/details/146319159>、<https://www.cnblogs.com/API-19970108110/p/19714577>
- 业界刊登能力对标：<https://help.dianxiaomi.com/article/orderManagement/1355>
