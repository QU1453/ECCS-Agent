# -*- coding: utf-8 -*-
"""ECCS 客服 Agent 后端（FastAPI）。

职责：
1. 启动本地 Web 服务，同一端口托管 `ui/` 静态页面（浏览器打开即可用）；
2. 暴露 `POST /api/ask`：把网页里输入的问题交给 LangGraph Agent，
   返回 {reply, intent, data}，前端据此渲染气泡与卡片。

运行：
    python server.py          # 默认 http://127.0.0.1:8623
    uvicorn server:app --host 127.0.0.1 --port 8623

密钥：配置统一走 config.py（智能体配置槽），真实 Key 放 .env / 环境变量，
本文件不写入、不打印任何密钥。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from agents import Supervisor, classic_reply
from memory import agent_session_id, get_short_term

BASE_DIR = Path(__file__).resolve().parent
HOST, PORT = config.HOST, config.PORT

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


class ClearRequest(BaseModel):
    session_id: str = "default"


class AgentService:
    """懒加载单例 Supervisor（多智能体主控）；多轮记忆由 memory/ 的 checkpointer 托管。"""

    def __init__(self) -> None:
        self._supervisor: Supervisor | None = None

    def supervisor(self) -> Supervisor:
        if self._supervisor is None:
            self._supervisor = Supervisor(
                api_key=config.API_KEY, base_url=config.BASE_URL, model=config.MODEL_ID
            )
        return self._supervisor

    def ask(self, message: str, session_id: str) -> dict:
        sup = self.supervisor()
        # 真实 LLM：多轮记忆 = LangGraph MemorySaver 按 thread_id(session_id) 隔离
        result = sup.answer(message, session_id) if sup.available else None
        if result and result.get("reply"):
            return result
        # 兜底：未配置 Key / Agent 不可用 / 调用异常（单轮，无记忆）
        return classic_reply(message)

    def clear_session(self, session_id: str) -> list[str]:
        """真清空：清除该会话在全部专职智能体下的 checkpoint 线程与压缩摘要。

        直接操作 checkpointer（不经过 Supervisor），无 Key 兜底模式下同样有效。
        """
        stm = get_short_term()
        cleared = []
        for name in ("customer_service", "presales"):
            sid = agent_session_id(name, session_id)
            stm.clear(sid)  # checkpoint 线程 + 摘要行一并清除
            cleared.append(sid)
        return cleared


service = AgentService()


@app.get("/api/status")
async def status() -> dict:
    sup = service.supervisor()
    return {
        "ok": True,
        "agent": sup.available,
        "mode": "llm" if sup.available else "local-fallback",
        "model": sup.model if sup.available else None,
        "reason": sup.reason,
    }


@app.post("/api/ask")
async def ask(req: AskRequest) -> JSONResponse:
    message = req.message.strip()
    if not message:
        return JSONResponse({"error": "message 不能为空"}, status_code=400)
    reply = service.ask(message, req.session_id)
    return JSONResponse(reply)


@app.post("/api/clear")
async def clear(req: ClearRequest) -> dict:
    """清空指定会话的后端记忆（前端「清空对话」按钮的真清空实现）。"""
    sid = req.session_id.strip()
    if not sid:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    return {"ok": True, "cleared": service.clear_session(sid)}


if __name__ == "__main__":
    import uvicorn

    print(f"ECCS Agent 已启动 → http://{HOST}:{PORT}  （{service.supervisor().reason or 'LLM 模式'}）")
    uvicorn.run(app, host=HOST, port=PORT)
