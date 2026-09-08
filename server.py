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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from agents import Supervisor
from core.dispatch.orchestrator import Orchestrator
from core.perception.session import start_conversation
from core.telemetry import get_recorder
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

# 同一端口托管前端页面：/ui 前缀与根路径均可访问
app.mount("/ui", StaticFiles(directory=BASE_DIR / "ui"), name="ui")


class AskRequest(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str = "default"


class ClearRequest(BaseModel):
    session_id: str = "default"


class EndConversationRequest(BaseModel):
    session_id: str
    user_id: str = "default"


class StartConversationRequest(BaseModel):
    user_id: str = "default"


class AgentService:
    """懒加载单例 Supervisor（多智能体主控）+ Orchestrator（认知层编排）。

    多轮记忆由 memory/ 的 checkpointer 托管；/api/ask 走编排器流水线。
    """

    def __init__(self) -> None:
        self._supervisor: Supervisor | None = None
        self._orchestrator: Orchestrator | None = None

    def supervisor(self) -> Supervisor:
        if self._supervisor is None:
            self._supervisor = Supervisor(
                api_key=config.API_KEY, base_url=config.BASE_URL, model=config.MODEL_ID
            )
        return self._supervisor

    def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            self._orchestrator = Orchestrator(self.supervisor())
        return self._orchestrator

    def ask(self, message: str, session_id: str, user_id: str) -> dict:
        """问答复用编排器：感知 → 上下文组装 → 路由 → 兜底 → 输出契约。"""
        return self.orchestrator().answer(message, session_id, user_id=user_id)

    def start_conversation(self, user_id: str) -> dict:
        """开始新谈话：生成 session_id 并登记（谈话注册表）。"""
        session_id = start_conversation(user_id)
        return {"ok": True, "session_id": session_id, "user_id": user_id}

    def end_conversation(self, session_id: str, user_id: str) -> dict:
        """结束谈话：触发一级总结（并视游标触发二级总结）——分层总结管线入口。"""
        return self.supervisor().end_conversation(session_id, user_id=user_id)

    def clear_session(self, session_id: str) -> list[str]:
        """真清空：清除该会话在全部专职智能体下的 checkpoint 线程与压缩摘要。

        直接操作 checkpointer（不经过 Supervisor），无 Key 兜底模式下同样有效；
        约束层（轮次预算 / 循环熔断标记）一并复位。
        """
        stm = get_short_term()
        cleared = []
        for name in ("customer_service", "presales", "research", "listing"):
            sid = agent_session_id(name, session_id)
            stm.clear(sid)  # checkpoint 线程 + 摘要行一并清除
            cleared.append(sid)
        # 约束层复位：熔断解除、频率窗口与轮次预算清零
        from core.constraint import get_constraint_layer

        get_constraint_layer().reset(session_id)
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
        "specialists": sorted(sup.specialists.keys()),
    }


@app.post("/api/ask")
async def ask(req: AskRequest) -> JSONResponse:
    message = req.message.strip()
    if not message:
        return JSONResponse({"error": "message 不能为空"}, status_code=400)
    reply = service.ask(message, req.session_id, req.user_id.strip() or "default")
    return JSONResponse(reply)


@app.post("/api/conversation/start")
async def conversation_start(req: StartConversationRequest) -> JSONResponse:
    """开始新谈话：返回新 session_id（前端存 localStorage，替代手工生成）。"""
    return JSONResponse(service.start_conversation(req.user_id.strip() or "default"))


@app.post("/api/conversation/end")
async def end_conversation(req: EndConversationRequest) -> JSONResponse:
    """结束谈话：一级总结入库，达 M 个触发二级总结。"""
    sid = req.session_id.strip()
    if not sid:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    result = service.end_conversation(sid, req.user_id.strip() or "default")
    return JSONResponse(result)


@app.post("/api/clear")
async def clear(req: ClearRequest) -> dict:
    """清空指定会话的后端记忆（前端「清空对话」按钮的真清空实现）。"""
    sid = req.session_id.strip()
    if not sid:
        return JSONResponse({"error": "session_id 不能为空"}, status_code=400)
    return {"ok": True, "cleared": service.clear_session(sid)}


# ===== 遥测 API（调试后台 /debug 的数据源；fail-open，库故障返回空数据）=====
@app.get("/api/telemetry/traces")
async def telemetry_traces(
    limit: int = Query(50, ge=1, le=500),
    session_id: str = Query(""),
    route: str = Query(""),
) -> dict:
    """近期 trace 列表（倒序；可按会话 / 路由过滤）。"""
    rec = get_recorder()
    return {"traces": rec.list_traces(limit=limit, session_id=session_id, route=route)}


@app.get("/api/telemetry/traces/{trace_id}")
async def telemetry_trace(trace_id: int) -> JSONResponse:
    """单条 trace + 事件明细（时间线）。"""
    trace = get_recorder().get_trace(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace 不存在"}, status_code=404)
    return JSONResponse(trace)


@app.get("/api/telemetry/summary")
async def telemetry_summary() -> dict:
    """聚合统计：概览卡 + 工具排行 + 智能体分布 + 最近错误。"""
    return get_recorder().summary()


@app.get("/api/telemetry/trend")
async def telemetry_trend(session_id: str = Query(...)) -> dict:
    """某会话逐轮 token 序列（诊断上下文膨胀）。"""
    return {"trend": get_recorder().token_trend(session_id)}


@app.post("/api/telemetry/clear")
async def telemetry_clear() -> dict:
    """清空遥测库（调试期维护）。"""
    get_recorder().clear()
    return {"ok": True}


# 调试后台页面（独立静态页，不与主工作台共用路由）
@app.get("/debug")
async def debug_page() -> FileResponse:
    return FileResponse(BASE_DIR / "ui" / "debug.html")


# 根路径挂载静态页（必须放在所有 API 路由之后，避免吞掉 /api/*）：
# html=True 使 "/" 自动返回 index.html；style.css / app.js 等相对引用同源生效
app.mount("/", StaticFiles(directory=BASE_DIR / "ui", html=True), name="root")


if __name__ == "__main__":
    import uvicorn

    print(f"ECCS Agent 已启动 → http://{HOST}:{PORT}  （{service.supervisor().reason or 'LLM 模式'}）")
    uvicorn.run(app, host=HOST, port=PORT)
