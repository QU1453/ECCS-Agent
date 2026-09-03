# ECCS Agent

**跨境电商客服智能体（日本市场）** — 面向日本消费者的电商 AI 客服，可打包为本地桌面 EXE。

> 大学生创新创业大赛项目 · E-Commerce Cross-border Customer Service Agent

---

## 项目简介

跨境电商场景下，海外（日本）消费者咨询商品、物流、退换货等高频问题存在时差、多语言与重复接待成本。本项目构建一个 **AI 客服智能体**，以本地桌面应用形态交付：

- 顾客打开即用（单 EXE，无需部署服务端）；
- 智能体自动完成**商品推荐 / 订单物流查询 / 退换货办理**等问答；
- 为后续接入大语言模型（LLM）意图路由、日本语客服与知识库检索预留接口。

## 功能特性

- **单窗口对话界面**：顾客侧对话体验，AI 左、顾客右，输入中动画与时间戳
- **Python Agent 后端**：FastAPI 提供 `/api/ask`，LangGraph 智能体接收网页输入并调用工具
- **卡片式智能回复**：物流轨迹卡、商品推荐卡，信息一目了然
- **快捷提问**：物流 / 退货 / 推荐等高频问题一键触发
- **双保险演示**：配置 `OPENAI_API_KEY` 走真实 LLM；未配置时自动退回本地规则引擎，演示不断线
- **EXE 目标**：`pywebview`（WebView2）封装界面 → PyInstaller 打包单文件

## 技术架构

| 层 | 方案 |
| --- | --- |
| 桌面容器 | Python + pywebview（Windows WebView2，开发中） |
| 后端服务 | FastAPI + uvicorn（`server.py`，同一端口托管前端） |
| 智能体 | LangGraph ReAct（`agents/`）：supervisor 主控调度专职智能体，LLM 自主决策 → 工具调用 → 回复生成 |
| 客服工具 | `tools/`：订单查询 / 物流跟踪 / 退换货办理 / 商品推荐（演示数据，多智能体共享） |
| 界面 | 原生 HTML / CSS / JS（`ui/`，可直接独立预览） |
| 记忆 | `memory/`：LangGraph MemorySaver 短期会话记忆（thread_id 隔离，多轮上下文自动携带） |
| 兜底引擎 | 未配置 Key 时 `agents/customer_service.py` 内置关键词路由，效果与前端演示一致 |
| 容器化 | Docker + docker-compose（`Dockerfile` / `docker-compose.yml` / `.dockerignore`） |
| 打包 | PyInstaller（onefile，规划中） |

数据链路：`网页输入 → POST /api/ask → supervisor 调度专职智能体 → 工具调用 → 返回 {reply, intent, data} → 前端渲染气泡/卡片`。

**记忆机制**：LLM 模式下，多轮对话记忆由 `memory/` 提供的 LangGraph checkpointer（MemorySaver）托管——按 `session_id` 映射 thread_id，自动携带历史上下文，server 端无需自行管理会话；进程内有效，重启清空（需要持久化时替换为 SqliteSaver 落盘）。未配置 Key 的兜底模式为单轮无记忆。长期记忆（用户画像 / 跨会话偏好）规划中，届时在 `memory/` 下新增 `long_term.py`。

**多智能体扩展**：新增智能体 = 在 `agents/` 加一个文件（参考 `customer_service.py`）并在 `supervisor.py` 注册；工具放 `tools/` 供所有智能体共享，互不干扰。三人三分支协作时，可各自认领一个智能体文件开发，Git 冲突面最小。

## 目录结构

```
大创一/
├── .gitignore        # 密钥 / 依赖 / 产物防护规则
├── .dockerignore     # 密钥 / 非运行文件不进入镜像
├── README.md
├── Dockerfile        # 单服务镜像（Python 3.12 slim）
├── docker-compose.yml# 一键编排：端口 8623，Key 走环境变量注入
├── server.py         # FastAPI 后端入口：托管 ui + /api/ask
├── config.py         # 智能体配置槽：API Key / 请求地址 / 模型 ID 统一入口
├── agents/           # 智能体目录（多智能体协作，一人一文件）
│   ├── supervisor.py       # 主控智能体：统一入口，调度专职智能体
│   └── customer_service.py # 客服智能体（LangGraph + 无 Key 本地兜底）
├── tools/            # 工具目录（各智能体共享）
│   ├── catalog.py    # 商品演示库
│   ├── order.py      # 订单 / 物流查询
│   ├── after_sales.py# 退换货办理
│   └── recommend.py  # 商品推荐
├── memory/           # 记忆目录（多智能体共享）
│   └── short_term.py # 短期会话记忆：MemorySaver 单例 + thread_id 规则
├── requirements.txt  # Python 依赖
├── .env.example      # 密钥配置样例（复制为 .env 后填写，不入库）
└── ui/
    ├── index.html    # 对话窗口骨架
    ├── style.css     # 设计系统（暖纸 / 深墨 / 柿子橙）
    └── app.js        # 交互 + 内置演示路由（预留 /api/ask 桥接）
```

## 智能体配置槽（API / 请求地址 / 模型 ID）

所有智能体的 LLM 配置集中在 `config.py` 一个槽位，三个字段：

| 槽位 | 变量 | 说明 | 示例 |
| --- | --- | --- | --- |
| API Key | `OPENAI_API_KEY` | 真实密钥，只放 `.env` / 环境变量，绝不入库 | `sk-...` |
| 请求地址 | `OPENAI_BASE_URL` | OpenAI 官方留空；第三方 / 自部署（DeepSeek、通义、本地 vLLM 等）填 base_url | `https://api.deepseek.com/v1` |
| 模型 ID | `OPENAI_MODEL` | OpenAI 兼容的模型名 | `gpt-4o-mini` / `deepseek-chat` |

填写方式（二选一）：

```bash
# 方式 A：本地 .env（推荐；.env 已被 .gitignore 拦截）
cp .env.example .env
# 编辑 .env，取消注释并填三个槽位

# 方式 B：环境变量（Docker / 云环境）
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export OPENAI_MODEL=deepseek-chat
```

约定：智能体文件（`agents/`）一律从 `config.py` 取值，不自行读环境变量——换模型 / 换服务商只改这一处；三个槽位全留空时自动走本地规则兜底，演示不断线。

## 本地运行

方式一 · 启动 Agent 后端（推荐，浏览器即全功能）：

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入 OPENAI_API_KEY（不填也能跑，走本地兜底）
python server.py
# 浏览器打开 http://127.0.0.1:8623
```

方式二 · 仅预览对话界面（无需任何依赖，走前端内置演示）：

```bash
python -m http.server 8623 --directory ui
# 浏览器打开 http://localhost:8623/index.html
```

方式三 · Docker 一键运行（环境与依赖全部封装在容器内）：

```bash
# 需要本机已安装 Docker / Docker Compose
cp .env.example .env      # 可选：填入 OPENAI_API_KEY（不填走本地兜底）
docker compose up -d --build
# 浏览器打开 http://127.0.0.1:8623
# 停止：docker compose down
```

> 镜像内**不烧录密钥**：`.dockerignore` 排除 `.env`，Key 由 compose 从宿主机 `.env` 注入环境变量；无 Key 时容器内 Agent 自动退回本地规则兜底。

桌面窗口版（`main.py`，开发中）：

```bash
pip install pywebview
python main.py
```

## 安全说明

> 本项目仓库内**禁止出现任何 API Key / 密钥**。

- 真实调用 LLM 所需的密钥一律保存在本地 `.env`（由 `.gitignore` 拦截），代码仅从环境变量读取
- `.env.example` 只含占位符，可安全入库；**绝不把真实 `.env` 提交**
- 每次 `git push` 前需核对暂存文件清单，确认无密钥类文件后再上传

## 协作约定（重要，团队须遵守）

1. **不要随意创建新版本 / 复制新版本文档**：代码、文档、设计稿一律在原文件上迭代，禁止动不动另存为"xxx_v2 / 最终版 / 新版本"之类的新文件或新分支，避免仓库里出现一堆重复版本。
2. **不要读写本机 C 盘文件**：本项目的所有源码与产物只在项目目录（仓库工作区）内读写，任何操作都不允许涉及 C 盘路径（如 `C:\...`），防止误改系统文件、泄漏本地数据。
3. **每次上传仓库前必须检查密钥文件**：`git push` / 提交前，先 `git status` + `git diff --cached --name-only` 核对暂存清单，确认没有 `.env`、密钥、token、证书等 API Key 相关文件被纳入上传；发现即拦截修正后再推。

## Roadmap

- [x] Python Agent 后端：LangGraph LLM 意图 + 工具调用（订单 / 物流 / 售后 / 推荐）
- [ ] 日本语客服（日语识别与回复、敬语风格）
- [ ] 知识库 RAG：商品资料、日本物流时效、退换货与关税政策
- [ ] pywebview 封装 + PyInstaller 打包单 EXE
- [ ] 人工接管、会话记录等运营能力

## 演示数据声明

界面内商品图、订单号、物流轨迹均为演示用模拟数据，与真实订单系统无关。
