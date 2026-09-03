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
- **卡片式智能回复**：物流轨迹卡、商品推荐卡，信息一目了然
- **快捷提问**：物流 / 退货 / 推荐等高频问题一键触发
- **演示路由**：界面内置关键词意图匹配，无需后端即可演示完整对话链路
- **EXE 目标**：`pywebview`（WebView2）封装界面 → PyInstaller 打包单文件

## 技术架构

| 层 | 方案 |
| --- | --- |
| 桌面容器 | Python + pywebview（Windows WebView2） |
| 界面 | 原生 HTML / CSS / JS（`ui/`，可直接独立预览） |
| 演示引擎 | 前端关键词意图路由（`app.js` → `window.askAgent`） |
| 智能体（规划） | LLM 意图识别 → 工具调用（订单 / 售后）→ 知识库（RAG）→ 回复生成 |
| 打包 | PyInstaller（onefile） |

前后端通过 `window.askAgent(q)` 桥接：当前为前端模拟实现，接入 Python 后端时仅需注入真实实现，界面无需改动。

## 目录结构

```
大创一/
├── .gitignore        # 密钥 / 依赖 / 产物防护规则
├── README.md
└── ui/
    ├── index.html    # 对话窗口骨架
    ├── style.css     # 设计系统（暖纸 / 深墨 / 柿子橙）
    └── app.js        # 交互 + 模拟 Agent 引擎 + pywebview 桥接点
```

## 本地运行

预览对话界面（无需任何依赖）：

```bash
python -m http.server 8623 --directory ui
# 浏览器打开 http://localhost:8623/index.html
```

桌面窗口版（`main.py`，开发中）：

```bash
pip install pywebview
python main.py
```

## 安全说明

> 本项目仓库内**禁止出现任何 API Key / 密钥**。

- 真实调用 LLM、订单 API 所需的密钥一律保存在本地 `.env`，由 `.gitignore` 拦截
- 每次 `git push` 前需核对暂存文件清单，确认无密钥类文件后再上传

## Roadmap

- [ ] Python 后端：LLM 意图路由 + 工具调用（订单查询 / 售后办理）
- [ ] 日本语客服（日语识别与回复、敬语风格）
- [ ] 知识库 RAG：商品资料、日本物流时效、退换货与关税政策
- [ ] pywebview 封装 + PyInstaller 打包单 EXE
- [ ] 人工接管、会话记录等运营能力

## 演示数据声明

界面内商品图、订单号、物流轨迹均为演示用模拟数据，与真实订单系统无关。
