# -*- coding: utf-8 -*-
"""Memory 模块一键演示：python -m memory.demo

覆盖：LLM 输入接口（LangGraph checkpointer + 压缩）、后端数据输入接口（facts + 文档分块）、
ANN-RAG 召回（速度 + 准确率对照）、跨实例持久化、build_context 四段组装。
无 OPENAI_API_KEY 时嵌入走 Hash 降级、压缩走纯裁剪降级（均有断言）。
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, MessagesState, START, StateGraph

from .manager import MemoryManager

THRESHOLD, KEEP_RECENT = 30, 10
N_MSG = 36  # > 阈值，保证压缩触发


def _toy_graph(saver):
    """最小演示图：模拟接入方把 saver 挂到自己的 LangGraph Agent 上。"""

    def bot(state: MessagesState):
        user = state["messages"][-1].content
        return {"messages": [AIMessage(f"已记录：{user}")]}

    g = StateGraph(MessagesState)
    g.add_node("bot", bot)
    g.add_edge(START, "bot")
    g.add_edge("bot", END)
    return g.compile(checkpointer=saver)


DOC = (
    "退货政策：自签收之日起 7 天内可无理由退货，商品需保持原包装与配件齐全。"
    "质量问题退货运费由商家承担，非质量问题由买家承担往返运费。"
    "退款将在仓库验收后 3 个工作日内原路退回。\n\n"
    "物流说明：国内默认顺丰速运，付款后 48 小时内发货。"
    "日本市场经保税仓直发，清关一般需要 2-3 天，全程可在小程序查询轨迹。\n\n"
    "商品参数：云感无线蓝牙耳机 Pro 采用主动降噪，续航 36 小时，"
    "支持蓝牙 5.3 双设备连接，充电盒提供额外 3 次补电。\n\n"
    "优惠活动：满 300 减 30 优惠券每日 10 点限量发放；"
    "老客推荐新客下单双方各得 20 元无门槛券；会员日全场 95 折。"
    "会员权益：年费会员享全年免运费与优先客服通道；学生认证可领 50 元新人礼包；"
    "企业采购提供专属折扣与批量开票服务，请联系在线客服获取报价。"
    "售后进度可在订单详情页实时查看，仓库验收后自动触发退款，无需人工催单。"
)


def main() -> int:
    base = Path(__file__).resolve().parent / "demo_data"
    shutil.rmtree(base, ignore_errors=True)  # 每次全新演示
    mm = MemoryManager(base, compress_threshold=THRESHOLD, keep_recent=KEEP_RECENT, llm=None)

    print("=" * 64)
    print("[1] LLM 输入接口：LangGraph checkpointer + 会话隔离 + 记忆压缩")
    graph = _toy_graph(mm.saver)
    cfg_a = mm.chat_config("session-A")
    for i in range(N_MSG):
        graph.invoke({"messages": [HumanMessage(f"问题 {i}：这是第 {i} 条消息")]}, cfg_a)
        mm.add_message("session-B", "user", f"会话B消息 {i}")  # 跨会话对照
    rep = mm.maybe_compress("session-A")
    print(f"   压缩报告：{rep}")
    expected_before = 2 * N_MSG  # 每轮 invoke：用户消息 + bot 回复 = 2 条
    assert rep["compressed"] is True
    assert rep["messages_before"] == expected_before
    assert rep["removed"] == expected_before - KEEP_RECENT
    assert rep["messages_after"] == KEEP_RECENT
    assert rep["summary_updated"] is False  # 无 Key：降级为纯裁剪
    hist_a = mm.get_history("session-A")
    hist_b = mm.get_history("session-B")
    print(f"   A 窗口 {len(hist_a)} 条 / B 窗口 {len(hist_b)} 条（各自隔离）")
    assert len(hist_a) == KEEP_RECENT and len(hist_b) == N_MSG
    assert all("会话B" not in str(h["content"]) for h in hist_a)
    print("   ✓ 压缩触发、窗口收敛、会话 A/B 互不串扰（无 Key：降级为纯裁剪，无摘要）")

    print("[2] 后端数据输入接口：结构化事实 + 长文本分块入库")
    mm.save_fact("user-1", "last_order_no", "2026081200012")
    mm.save_fact("user-1", "language_pref", "日本語")
    mm.save_fact("user-2", "last_order_no", "2026081200999")  # 其他用户
    info = mm.add_document("user-1", DOC, title="客服知识手册")
    print(f"   facts={len(mm.get_facts('user-1'))} 条；文档分块 {info['chunks']} 块")
    assert info["chunks"] >= 2

    print("[3] ANN-RAG 召回：速度优先 + 精确重排（对照暴力精确检索）")
    q = "退货流程和退款时效"
    t0 = time.perf_counter()
    hits = mm.recall("user-1", q, top_k=5)
    ms = (time.perf_counter() - t0) * 1000
    print(f"   召回 {len(hits)} 条，耗时 {ms:.1f} ms；Top1: {hits[0]['text'][:28]}…")
    assert hits and any("退货" in h["text"] or "退款" in h["text"] for h in hits)
    brute = mm.long_term.brute_force_recall("user-1", q, top_k=5)
    inter = {h["chunk_id"] for h in hits} & {b["chunk_id"] for b in brute}
    r5 = len(inter) / len(brute) if brute else 0.0
    print(f"   recall@5（对齐精确检索）：{r5:.0%}（Hash 降级向量；配真嵌入更高）")
    assert r5 >= 0.6
    assert all(h["user_id"] == "user-1" for h in hits)  # 万人隔离
    print("   ✓ 命中正确主题、只在本用户分区内检索")

    print("[4] 跨实例持久化（SQLite 落盘 + .hnsw 索引重载）")
    mm.close()
    mm2 = MemoryManager(base, compress_threshold=THRESHOLD, keep_recent=KEEP_RECENT, llm=None)
    assert len(mm2.get_history("session-A")) == KEEP_RECENT
    assert len(mm2.get_facts("user-1")) == 2
    hits2 = mm2.recall("user-1", q, top_k=5)
    assert {h["chunk_id"] for h in hits2} == {h["chunk_id"] for h in hits}
    ctx = mm2.build_context("session-A", "user-1", query="优惠活动")
    print(f"   build_context：{ {k: len(v) for k, v in ctx.items()} }")
    assert set(ctx) == {"summary", "history", "facts", "recalled"}
    assert ctx["recalled"] and any("优惠" in h["text"] for h in ctx["recalled"])
    print("   ✓ 重启后短期/长期/索引全部一致")
    mm2.close()

    print("=" * 64)
    print("DEMO ALL PASS ✓（数据目录：memory/demo_data，可删除）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
