# -*- coding: utf-8 -*-
"""MemoryManager：Agent 记忆统一入口。

两类输入接口（对接入方零侵入，模块可整体搬移）：
- LLM 输入接口（对话消息）：add_message / chat_config / get_history / maybe_compress / saver
- 后端数据输入接口：save_fact（结构化 KV）/ add_document（长文本 → 分块 → ANN 入库）

检索：recall（ANN 速度优先 + 精确重排，高准确率）；组装：build_context 四段上下文。

换库扩展：替换 EmbeddingProvider / AnnIndex / 存储实现即可，本类签名不变
（如未来切 Postgres/pgvector / Redis / 分片索引）。
"""
from __future__ import annotations

from pathlib import Path

from .long_term.memory import LongTermMemory
from .long_term.rag import pick_provider
from .short_term.compress import Compressor
from .short_term.memory import ShortTermMemory

__all__ = ["MemoryManager"]


class MemoryManager:
    def __init__(
        self,
        base_dir: str | Path | None = None,
        *,
        short_term: ShortTermMemory | None = None,
        long_term: LongTermMemory | None = None,
        window_size: int = 20,
        compress_threshold: int = 30,
        keep_recent: int = 10,
        llm=None,                        # langchain BaseChatModel（如 ChatOpenAI），None=压缩降级
        embedding_provider=None,         # EmbeddingProvider，None=按环境自动选择
        chunk_size: int = 300,
        chunk_overlap: int = 50,
        ann_M: int = 32,
        ann_ef_construction: int = 200,
        ann_ef_search: int = 64,
        ann_overfetch: int = 50,
        auto_save: bool = True,
    ):
        base = Path(base_dir) if base_dir else Path(__file__).resolve().parent
        # 实例注入优先（如 get_memory() 复用 get_short_term() 单例，全程单连接）；
        # 未注入时按 base_dir 自建（原行为不变）
        self.short_term = short_term or ShortTermMemory(
            base / "short_term" / "data" / "short_term.sqlite",
            window_size=window_size,
            compressor=Compressor(llm=llm, compress_threshold=compress_threshold, keep_recent=keep_recent),
        )
        self.long_term = long_term or LongTermMemory(
            base / "long_term" / "data" / "long_term.sqlite",
            base / "long_term" / "data" / "memories.hnsw",
            provider=embedding_provider or pick_provider(),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            M=ann_M,
            ef_construction=ann_ef_construction,
            ef_search=ann_ef_search,
            overfetch=ann_overfetch,
            auto_save=auto_save,
        )

    # ================= LLM 输入接口（对话消息） =================
    @property
    def saver(self):
        """接入方挂载点：create_react_agent(..., checkpointer=mm.saver)。"""
        return self.short_term.saver

    def chat_config(self, session_id: str) -> dict:
        """graph.invoke 的配置：thread_id=会话ID（一会话一线程，万人隔离）。"""
        return self.short_term.chat_config(session_id)

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """记录一条对话消息（role: user/assistant/system）。"""
        self.short_term.add_message(session_id, role, content)

    def get_history(self, session_id: str, with_summary: bool = True) -> list[dict]:
        """短期上下文：[压缩摘要] + 窗口内消息，供 LLM 输入组装。"""
        return self.short_term.get_history(session_id, with_summary=with_summary)

    def maybe_compress(self, session_id: str) -> dict:
        """超过阈值触发压缩：LLM 滚动摘要 + 旧消息裁剪（无 LLM 自动降级）。"""
        return self.short_term.maybe_compress(session_id)

    # ================= 后端数据输入接口 =================
    def save_fact(self, user_id: str, key: str, value, source: str = "backend") -> None:
        """结构化事实（订单号/偏好/状态等）：精确 KV upsert，天然高准确率。"""
        self.long_term.save_fact(user_id, key, value, source=source)

    def get_facts(self, user_id: str) -> list[dict]:
        """取用户全部结构化事实 [{key, value, source, updated_at}]。"""
        return self.long_term.get_facts(user_id)

    def delete_fact(self, user_id: str, key: str) -> bool:
        """删除一条事实；key 不存在返回 False。"""
        return self.long_term.delete_fact(user_id, key)

    def add_document(self, user_id: str, text: str, title: str | None = None,
                     source: str = "backend") -> dict:
        """长文本/知识入库：自动分块 → 向量化 → ANN 索引。返回 {doc_id, chunks}。"""
        return self.long_term.add_document(user_id, text, title=title, source=source)

    # ================= RAG 检索 =================
    def recall(self, user_id: str, query: str, top_k: int = 5) -> list[dict]:
        """语义召回长期记忆：ANN 粗排（user 分区过滤）→ 精确 cosine 重排 → top-k。"""
        return self.long_term.recall(user_id, query, top_k=top_k)

    # ================= 组装与维护 =================
    def build_context(self, session_id: str, user_id: str | None = None,
                      query: str | None = None, top_k: int = 5) -> dict:
        """四段组装：summary / history / facts / recalled。user_id 缺省回落 session_id。"""
        uid = str(user_id or session_id)
        return {
            "summary": self.short_term.get_summary(session_id),
            "history": self.short_term.get_history(session_id, with_summary=False),
            "facts": self.long_term.get_facts(uid),
            "recalled": self.recall(uid, query, top_k=top_k) if query else [],
        }

    def clear(self, session_id: str | None = None, user_id: str | None = None) -> None:
        """清除记忆：session_id 清短期会话，user_id 清长期记忆；都不传则无操作。"""
        if session_id:
            self.short_term.clear(session_id)
        if user_id:
            self.long_term.clear(user_id)

    def close(self) -> None:
        """关闭短期 / 长期存储连接（auto_save 时长期索引先落盘）。"""
        self.short_term.close()
        self.long_term.close()
