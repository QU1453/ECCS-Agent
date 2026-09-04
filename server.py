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
from tools import create_order, get_products, lookup_order, pay_order

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


# ===== 自营商城（demo 用最小闭环：商品 → 下单 → 模拟支付 → 问客服）=====
@app.get("/shop")
async def shop() -> FileResponse:
    return FileResponse(BASE_DIR / "ui" / "shop.html")


@app.get("/api/shop/products")
async def shop_products() -> list[dict]:
    """商品列表（商城货架，实时读库）。"""
    return list(get_products().values())


class BuyRequest(BaseModel):
    product_code: str
    qty: int = 1


@app.post("/api/shop/buy")
async def shop_buy(req: BuyRequest) -> JSONResponse:
    """下单：生成未付款订单，返回订单号（前端再调 /api/shop/pay 完成模拟支付）。"""
    try:
        order = create_order(req.product_code.strip(), max(1, int(req.qty)))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"order_no": order["order_no"], "total": order["total"],
                         "status": order["status"], "product": order["product"]})


class PayRequest(BaseModel):
    order_no: str


@app.post("/api/shop/pay")
async def shop_pay(req: PayRequest) -> JSONResponse:
    """模拟支付：订单未付款 → 已付款（真实版替换为支付网关回调）。"""
    order = pay_order(req.order_no.strip())
    if order is None:
        return JSONResponse({"error": "订单不存在"}, status_code=404)
    return JSONResponse({"order_no": order["order_no"], "status": order["status"],
                         "paid_at": order["paid_at"]})


@app.get("/api/shop/orders/{order_no}")
async def shop_order_detail(order_no: str) -> JSONResponse:
    """订单详情（我的订单页：状态 + 轨迹），与客服回答同源同库。"""
    order = lookup_order(order_no)
    if order is None:
        return JSONResponse({"error": "订单不存在"}, status_code=404)
    return JSONResponse({
        "order_no": order["order_no"],
        "status": order["status"],
        "qty": order["qty"],
        "total": order["total"],
        "paid_at": order["paid_at"],
        "carrier": order["carrier"],
        "steps": order["steps"],
        "product": order["product"],
    })


class AskRequest(BaseModel):
    message: str
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


if __name__ == "__main__":
    import uvicorn

    print(f"ECCS Agent 已启动 → http://{HOST}:{PORT}  （{service.supervisor().reason or 'LLM 模式'}）")
    uvicorn.run(app, host=HOST, port=PORT)
