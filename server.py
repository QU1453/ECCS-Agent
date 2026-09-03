# -*- coding: utf-8 -*-
"""ECCS 客服 Agent 后端（FastAPI）。

职责：
1. 启动本地 Web 服务，同一端口托管 `ui/` 静态页面（浏览器打开即可用）；
2. 暴露 `POST /api/ask`：把网页里输入的问题交给 LangGraph Agent，
   返回 {reply, intent, data}，前端据此渲染气泡与卡片。

运行：
    python server.py          # 默认 http://127.0.0.1:8623
    uvicorn server:app --host 127.0.0.1 --port 8623

密钥：OPENAI_API_KEY 从环境变量或项目根目录 `.env` 读取（详见 .env.example），
本文件不写入、不打印任何密钥。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import Agent, classic_reply

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # 读取本地密钥配置（已被 .gitignore 拦截）

HOST = os.getenv("SERVER_HOST", "127.0.0.1")
PORT = int(os.getenv("SERVER_PORT", "8623"))
API_KEY = os.getenv("OPENAI_API_KEY", "").strip() or None
BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

app = FastAPI(title="ECCS Agent", version="0.1.0")

# 本地演示：允许静态预览（python -m http.server 另起端口）跨域调用后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 同一端口托管前端页面
app.mount("/ui", StaticFiles(directory=BASE_DIR / "ui"), name="ui")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "ui" / "index.html")


class AskRequest(BaseModel):
    message: str
    session_id: str = "default"


class AgentService:
    """懒加载单例 Agent + 会话记忆（最多保留最近 20 条）。"""

    def __init__(self) -> None:
        self._agent: Agent | None = None
        self.sessions: dict[str, list[dict]] = {}

    def agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(api_key=API_KEY, base_url=BASE_URL, model=MODEL)
        return self._agent

    def ask(self, message: str, session_id: str) -> dict:
        agent = self.agent()
        history = self.sessions.setdefault(session_id, [])
        # 真实 LLM：携带上下文多轮对话
        result = agent.answer(message, history) if agent.available else None
        if result and result.get("reply"):
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": result["reply"]})
            del history[:-20]  # 控制记忆长度
            return result
        # 兜底：未配置 Key / Agent 不可用 / 调用异常
        return classic_reply(message)


service = AgentService()


@app.get("/api/status")
async def status() -> dict:
    agent = service.agent()
    return {
        "ok": True,
        "agent": agent.available,
        "mode": "llm" if agent.available else "local-fallback",
        "model": agent.model if agent.available else None,
        "reason": agent.reason,
    }


@app.post("/api/ask")
async def ask(req: AskRequest) -> JSONResponse:
    message = req.message.strip()
    if not message:
        return JSONResponse({"error": "message 不能为空"}, status_code=400)
    reply = service.ask(message, req.session_id)
    return JSONResponse(reply)


if __name__ == "__main__":
    import uvicorn

    print(f"ECCS Agent 已启动 → http://{HOST}:{PORT}  （{service.agent().reason or 'LLM 模式'}）")
    uvicorn.run(app, host=HOST, port=PORT)
