# -*- coding: utf-8 -*-
"""短期记忆：LangGraph SqliteSaver（thread_id="session:{会话ID}"，万人即万 thread，互不串扰）。

接入方式（不改本模块）：

    from memory import MemoryManager
    mm = MemoryManager()
    graph = create_react_agent(..., checkpointer=mm.short_term.saver)
    result = graph.invoke({"messages": [...]}, mm.chat_config(session_id))

约定：消息状态 channel 名为 "messages"（langgraph MessagesState）。
压缩摘要存本库 summaries 表（不动接入方 state schema），get_history 自动注入 system 消息。
单进程假设；更大并发时换 Postgres checkpointer 即可（接口不变）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph

from .compress import Compressor

_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _to_message(role: str, content: str) -> BaseMessage:
    role = (role or "user").lower()
    cls = {"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}.get(role, HumanMessage)
    return cls(content)


def thread_id_for(session_id: str) -> str:
    """会话 ID → checkpointer 线程命名空间（兼容原 memory/short_term.py 的 "session:" 前缀）。"""
    return f"session:{session_id}"


class ShortTermMemory:
    """短期记忆 = LangGraph checkpoint（会话内消息）+ summaries 表（压缩摘要）。"""

    def __init__(self, db_path: str | Path, window_size: int = 20, compressor: Compressor | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.window_size = max(2, window_size)
        self.compressor = compressor or Compressor()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS summaries("
            "thread_id TEXT PRIMARY KEY, summary TEXT NOT NULL DEFAULT '',"
            "updated_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        self._conn.commit()
        self._saver = SqliteSaver(self._conn)
        self._writer = self._compile_writer()

    # ---- 内部：一个挂在同一 saver 上的最小写图（invoke/update_state 即写入 checkpoint）----
    def _compile_writer(self):
        g = StateGraph(MessagesState)
        g.add_node("noop", lambda state: {})
        g.add_edge(START, "noop")
        g.add_edge("noop", END)
        return g.compile(checkpointer=self._saver)

    @property
    def saver(self) -> SqliteSaver:
        """暴露给接入方：create_react_agent(..., checkpointer=stm.saver)。"""
        return self._saver

    def chat_config(self, session_id: str) -> dict:
        """LangGraph 调用配置：thread_id="session:{会话ID}"，一人一会话一线程。"""
        return {"configurable": {"thread_id": thread_id_for(session_id)}}

    # ---------- LLM 输入接口 ----------
    def add_message(self, session_id: str, role: str, content: str) -> None:
        """写入一条对话消息到该会话 checkpoint（role: user/assistant/system）。"""
        self._writer.invoke({"messages": [_to_message(role, content)]}, self.chat_config(session_id))

    # ---------- 读 ----------
    def get_messages(self, session_id: str) -> list[BaseMessage]:
        state = self._writer.get_state(self.chat_config(session_id))
        return [m for m in ((state.values or {}).get("messages") or []) if isinstance(m, BaseMessage)]

    def get_history(self, session_id: str, with_summary: bool = True) -> list[dict]:
        """取会话上下文：[压缩摘要(如有)] + 当前窗口消息，供 LLM 输入组装。"""
        out: list[dict] = []
        summary = self.get_summary(session_id) if with_summary else ""
        if summary:
            out.append({"role": "system", "content": f"[早前对话摘要]\n{summary}"})
        for m in self.get_messages(session_id):
            out.append({
                "role": _ROLE_MAP.get(getattr(m, "type", "human"), "user"),
                "content": getattr(m, "content", ""),
            })
        return out

    def count_messages(self, session_id: str) -> int:
        return len(self.get_messages(session_id))

    def get_summary(self, session_id: str) -> str:
        row = self._conn.execute(
            "SELECT summary FROM summaries WHERE thread_id=?", (str(session_id),)
        ).fetchone()
        return row[0] if row else ""

    # ---------- 压缩 ----------
    def maybe_compress(self, session_id: str) -> dict:
        """超过阈值触发：旧消息 → LLM 滚动摘要（无 LLM 降级为纯裁剪）→ RemoveMessage 移除。"""
        msgs = self.get_messages(session_id)
        total = len(msgs)
        if not self.compressor.needs_compress(total):
            return {"compressed": False, "messages": total,
                    "reason": f"{total} <= 阈值 {self.compressor.compress_threshold}"}
        keep = self.compressor.keep_recent
        old, recent = msgs[:-keep], msgs[-keep:]
        prev = self.get_summary(session_id)
        new_summary = self.compressor.summarize(old, prev)
        if new_summary and new_summary != prev:
            self._conn.execute(
                "INSERT INTO summaries(thread_id, summary) VALUES(?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET summary=excluded.summary,"
                " updated_at=datetime('now','localtime')",
                (str(session_id), new_summary),
            )
            self._conn.commit()
        removes = Compressor.messages_to_remove(old)
        if removes:
            try:
                self._writer.update_state(self.chat_config(session_id), {"messages": removes})
            except Exception:  # 兜底：同样走 reducer 的 invoke 路径
                self._writer.invoke({"messages": removes}, self.chat_config(session_id))
        return {
            "compressed": True,
            "messages_before": total,
            "removed": len(removes),
            "summary_updated": bool(new_summary and new_summary != prev),
            "messages_after": self.count_messages(session_id),
        }

    # ---------- 维护 ----------
    def clear(self, session_id: str) -> None:
        self._saver.delete_thread(str(session_id))
        self._conn.execute("DELETE FROM summaries WHERE thread_id=?", (str(session_id),))
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
