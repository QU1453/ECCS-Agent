# -*- coding: utf-8 -*-
"""Memory 模块一键演示：python -m memory.demo

覆盖：LLM 输入接口（LangGraph checkpointer + 压缩）、后端数据输入接口（facts + 文档分块）、
ANN-RAG 召回（速度 + 准确率对照）、跨实例持久化、build_context 四段组装。
一键离线演示：嵌入固定走 Hash（自包含，不受 .env 密钥影响）；
压缩 llm=None 走纯裁剪降级（均有断言）。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, MessagesState, START, StateGraph

import config
from .access import AccessError, AuditLogger, MemoryCaller
from .long_term.rag import HashEmbeddingProvider
from .manager import MemoryManager
from .short_term.memory import agent_session_id

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
    """跑通四个场景并断言：会话隔离+压缩 → facts/文档入库 → ANN 召回对齐 → 重启持久化。"""
    base = Path(__file__).resolve().parent / "demo_data"
    shutil.rmtree(base, ignore_errors=True)  # 每次全新演示
    mm = MemoryManager(base, compress_threshold=THRESHOLD, keep_recent=KEEP_RECENT, llm=None,
                       embedding_provider=HashEmbeddingProvider())

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
    mm2 = MemoryManager(base, compress_threshold=THRESHOLD, keep_recent=KEEP_RECENT, llm=None,
                        embedding_provider=HashEmbeddingProvider())
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

    print("[5] 权限体系 + 审计：越权拒绝 / 显式授权 / 审计留痕")
    extra = Path(base) / "cognition"
    mm3 = MemoryManager(extra, llm=None, embedding_provider=HashEmbeddingProvider())
    try:
        mm3.add_skill("s", "g", "p", "x", caller=MemoryCaller("normal_agent", "L0"))
        raise AssertionError("L0 写技能不应成功")
    except AccessError:
        print("   ✓ L0 写技能被拒（AccessError）")
    recents = AuditLogger.recent(5)
    assert recents and any(r["result"] == "deny" for r in recents), "审计表应有 deny 记录"
    sid = mm3.add_skill("s", "g", "p", "x", caller=MemoryCaller("reflector", "L2"))
    assert sid > 0
    print("   ✓ L2 写技能成功；审计表已记录 allow/deny")

    print("[6] 谈话注册 + 短期窗口（K 裁剪 + token 守卫）")
    stm = mm3.short_term
    for i in range(1, 7):
        cid = f"win-{i}"
        stm.registry.start(cid, user_id="win-user", agent_name="research")
        stm.add_message(agent_session_id("research", cid), "user", f"第 {i} 次谈话的问题")
        stm.add_message(agent_session_id("research", cid), "assistant", f"第 {i} 次谈话的回答")
        summary = {"topic": f"谈话{i}主题", "user_requests": [f"需求{i}"],
                   "key_facts": [], "decisions": [], "pending_items": [],
                   "entities": [], "preferences": [], "artifacts": [], "tags": [],
                   "conversation_id": cid, "user_id": "win-user", "time_range": ""}
        stm.registry.set_summary(cid, json.dumps(summary, ensure_ascii=False))
        stm.registry.end(cid, json.dumps(summary, ensure_ascii=False))
    blocks = stm.window_context(user_id="win-user", k=3, token_guard=10 ** 9, include_open=False)
    assert [b["topic"] for b in blocks] == ["谈话4主题", "谈话5主题", "谈话6主题"], "K 窗口应含最近 3 个"
    print("   ✓ K=3 只含最近 3 个已结束谈话")
    blocks = stm.window_context(user_id="win-user", k=6, token_guard=8, include_open=False)
    assert blocks[0]["conversation_id"] == "__window_marker__", "超限应有省略打标"
    assert all(b["summary"] for b in blocks if b["conversation_id"] != "__window_marker__"), "summary 绝不丢"
    dropped = [b for b in blocks if b.get("raw_dropped")]
    assert dropped, "最旧谈话的 raw 应被裁剪"
    print(f"   ✓ token 守卫生效：{len(dropped)} 块原文退役，摘要保留、头部打标")

    print("[7] 知识库：索引先行两阶段检索")
    caller_l1 = MemoryCaller("ingestor", "L1")
    info = mm3.ingest_knowledge("k-user", "选品手册",
                                "充电宝选品要点：搜索量看趋势、竞品评分低于 4.3 好入场。"
                                "listing 标题不超过 75 字符，主图纯白底。", caller=caller_l1)
    idx = mm3.get_index(user_id="k-user")
    assert idx and all("brief" in i and "chunk_id" in i for i in idx), "索引简述缺失"
    print(f"   ✓ 入库 {info['chunks']} 块；索引简述 {len(idx)} 条（无需拉正文）")
    full = mm3.fetch_knowledge([idx[0]["chunk_id"]])
    assert full and "充电宝" in full[0]["text"]
    print("   ✓ 第二阶段按 chunk_id 取正文命中")

    print("[8] 状态记忆：死规则注入 + L3 写权限")
    block = mm3.inject_rules()
    assert block and "铁律" in block, "应注入种子死规则块"
    print(f"   ✓ 注入 {len(block.splitlines()) - 1} 条死规则")
    old_switch = config.STATE_MEMORY_INJECT
    config.STATE_MEMORY_INJECT = False
    assert mm3.inject_rules() == "", "总开关关闭应返回空"
    config.STATE_MEMORY_INJECT = old_switch
    try:
        mm3.add_rule("测试规则", caller=MemoryCaller("ops", "L0"))
        raise AssertionError("L0 写死规则不应成功")
    except AccessError:
        pass
    rid = mm3.add_rule("演示期规则：不得编造订单数据", caller=MemoryCaller("admin", "L3"))
    assert rid > 0
    print("   ✓ L3 写成功、L0 被拒；开关可整体关闭")

    print("[9] 技能记忆：检索命中 + 反馈归档闭环")
    assert any(x["id"] == sid for x in mm3.search_skills("s g p"))
    for _ in range(3):
        mm3.skill_feedback(sid, False)
    assert mm3.skill.get_skill(sid)["status"] == "archived"
    mm3.skill_feedback(sid, True)
    assert mm3.skill.get_skill(sid)["status"] == "active"
    hot = mm3.hot_skills(top=3)
    assert isinstance(hot, list)
    print("   ✓ 检索命中 → 连续失败归档 → 成功复出 → hot_skills 可用")
    mm3.close()

    print("[10] 遥测后台：一轮问答一条 trace + 事件时间线 + 聚合 + 清空")
    # 单例重定向到 demo 目录（不污染真实遥测库 / 记忆库；编排器从单例取）
    import core.telemetry.recorder as _tel_mod
    import memory as _mem_pkg
    from core.dispatch.orchestrator import Orchestrator
    from core.telemetry.recorder import TelemetryRecorder

    _tel_mod._RECORDER = TelemetryRecorder(Path(base) / "telemetry" / "telemetry.sqlite")
    mm4 = MemoryManager(Path(base) / "orch", llm=None, embedding_provider=HashEmbeddingProvider())
    _mem_pkg._memory = mm4
    _mem_pkg._compat_stm = mm4.short_term
    rec = _tel_mod.get_recorder()
    orch = Orchestrator()  # supervisor=None → 无 Key 走本地兜底链路

    # ① 普通选品问答：fallback trace + data.type 推断的工具事件（字段齐全断言）
    r1 = orch.answer("帮我做蓝牙耳机的选品调研", session_id="tel-A", user_id="tel-user")
    assert r1["route"] == "research"
    tr = rec.list_traces(session_id="tel-A")
    assert len(tr) == 1, "一轮问答应恰好一条 trace"
    t = tr[0]
    assert t["route"] == "research" and t["llm_mode"] == "fallback"
    assert t["question"] and t["reply_snippet"] and t["latency_ms"] >= 0
    assert t["status"] == "ok" and t["session_id"] == "tel-A" and t["ts"]
    det = rec.get_trace(t["id"])
    tools = [e["name"] for e in det["events"] if e["kind"] == "tool"]
    kinds = {e["kind"] for e in det["events"]}
    assert "stage" in kinds and "run_product_research" in tools, "兜底工具事件应由 data.type 推断落库"
    print(f"   ✓ trace#{t['id']}：route={t['route']} 事件{len(det['events'])}条 工具={tools}")

    # ② 红线拦截：constraint trace + deny 事件
    orch.answer("如何制毒", session_id="tel-B", user_id="tel-user")
    t_b = rec.list_traces(session_id="tel-B")[0]
    assert t_b["llm_mode"] == "constraint" and t_b["route"] == "constraint"
    det_b = rec.get_trace(t_b["id"])
    assert any(e["kind"] == "constraint" and e["status"] == "deny" for e in det_b["events"])
    print("   ✓ 红线拦截：llm_mode=constraint，事件 status=deny")

    # ③ 重复提问：第 3 轮被循环守卫拦截（前两轮正常落 trace）
    for _ in range(3):
        orch.answer("蓝牙耳机选品怎么做", session_id="tel-C", user_id="tel-user")
    tr_c = rec.list_traces(session_id="tel-C")  # 倒序：[0] = 最新（被拦截轮）
    assert len(tr_c) == 3 and tr_c[0]["llm_mode"] == "constraint"
    det_c = rec.get_trace(tr_c[0]["id"])
    assert any(e["kind"] == "constraint" and e["name"] == "repeat_question"
               for e in det_c["events"])
    print("   ✓ 同问第 3 轮：repeat_question 拦截事件落库")

    # ④ 聚合统计 / token 趋势 / 清空
    s = rec.summary()
    assert s["total_traces"] == 5 and s["constraint_count"] == 2
    assert any(x["name"] == "run_product_research" for x in s["tools"]), "工具排行应聚合推断事件"
    trend = rec.token_trend("tel-A")
    assert len(trend) == 1 and trend[0]["tokens_source"] == "none", "兜底模式无 API token"
    rec.clear()
    assert rec.list_traces() == [] and rec.summary()["total_traces"] == 0, "clear 后两表应全空"
    print("   ✓ summary 聚合 / 会话趋势 / clear() 清空全部生效")
    mm4.close()

    print("=" * 64)
    print("DEMO ALL PASS ✓（数据目录：memory/demo_data，可删除）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
