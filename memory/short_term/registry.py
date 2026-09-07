# -*- coding: utf-8 -*-
"""谈话注册表（ConversationRegistry）：以「谈话」为记忆粒度的生命周期管理。

设计（见 docs/memory-system-design.md §3.1）：
- 谈话 = 一次会话（session_id）的完整生命周期，替代旧"按消息条数"的压缩口径；
- 每次谈话结束后由总结管线写入一级总结（summary_json），再按 M 个一批做二级总结；
- 短期窗口只保留最近 K 个谈话的原文；更早谈话原文退役（rolled_up 标记，冷查询仍可回查）。

本类复用 ShortTermMemory 的同一 SQLite 连接（self._conn），不另开库、不加锁。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime


class ConversationRegistry:
    """谈话注册表：start / update_agent / end / 总结归属 / 滚动合并游标。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        # 说明：agent_name=该谈话最后处理的智能体（原文取回用）；rolled_up=是否已参与二级总结
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS conversation_registry("
            "session_id TEXT PRIMARY KEY,"
            "user_id TEXT DEFAULT '',"
            "agent_name TEXT DEFAULT '',"
            "status TEXT DEFAULT 'open',"
            "started_at TEXT, ended_at TEXT,"
            "summary_json TEXT DEFAULT '',"
            "rolled_up INTEGER DEFAULT 0"
            ")"
        )
        self._conn.commit()

    # ---------- 生命周期 ----------
    def start(self, session_id: str, user_id: str = "", agent_name: str = "") -> None:
        """登记谈话开始（幂等：已存在则不动）。"""
        self._conn.execute(
            "INSERT OR IGNORE INTO conversation_registry"
            "(session_id, user_id, agent_name, status, started_at)"
            " VALUES(?,?,?,?,?)",
            (str(session_id), str(user_id), agent_name, "open",
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        self._conn.commit()

    def update_agent(self, session_id: str, agent_name: str) -> None:
        """记录该谈话最近一次由哪个智能体处理（结束总结/原文取回都依赖它）。"""
        self._conn.execute(
            "UPDATE conversation_registry SET agent_name=? WHERE session_id=?",
            (agent_name, str(session_id)),
        )
        self._conn.commit()

    def end(self, session_id: str, summary_json: str = "") -> None:
        """结束谈话：记录结束时间；带 summary 时直接标记 summarized。"""
        status = "summarized" if summary_json else "closed"
        self._conn.execute(
            "UPDATE conversation_registry SET status=?, ended_at=?, summary_json=? WHERE session_id=?",
            (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), summary_json, str(session_id)),
        )
        self._conn.commit()

    def set_summary(self, session_id: str, summary_json: str) -> None:
        """写入/覆盖一级总结（P2 总结管线调用）。"""
        self._conn.execute(
            "UPDATE conversation_registry SET summary_json=?, status='summarized' WHERE session_id=?",
            (summary_json, str(session_id)),
        )
        self._conn.commit()

    def get(self, session_id: str) -> dict | None:
        """读单个谈话记录；不存在返回 None。"""
        row = self._conn.execute(
            "SELECT session_id, user_id, agent_name, status, started_at, ended_at,"
            " summary_json, rolled_up FROM conversation_registry WHERE session_id=?",
            (str(session_id),),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    # ---------- 窗口组装 / 二级总结游标 ----------
    def recent_closed(self, k: int, user_id: str = "") -> list[dict]:
        """最近 k 个已结束的谈话（按结束时间倒序，供 K 窗口组装）。"""
        sql = ("SELECT session_id, user_id, agent_name, status, started_at, ended_at,"
               " summary_json, rolled_up FROM conversation_registry"
               " WHERE status IN ('closed','summarized')")
        args: list = []
        if user_id:
            sql += " AND user_id=?"
            args.append(str(user_id))
        sql += " ORDER BY COALESCE(ended_at, started_at) DESC, rowid DESC LIMIT ?"
        args.append(int(k))
        rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def open_conversations(self, user_id: str = "") -> list[dict]:
        """当前进行中的谈话（窗口组装时附在已结束谈话之后）。"""
        sql = "SELECT session_id, user_id, agent_name, status, started_at, ended_at," \
              " summary_json, rolled_up FROM conversation_registry WHERE status='open'"
        args: list = []
        if user_id:
            sql += " AND user_id=?"
            args.append(str(user_id))
        rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def pending_rollup(self, limit: int = 0) -> list[dict]:
        """未做二级总结的已结束谈话（按结束时间升序，满 M 个触发合并）。"""
        n = int(limit) if limit else -1
        rows = self._conn.execute(
            "SELECT session_id, user_id, agent_name, status, started_at, ended_at,"
            " summary_json, rolled_up FROM conversation_registry"
            " WHERE rolled_up=0 AND status IN ('closed','summarized')"
            " ORDER BY COALESCE(ended_at, started_at) ASC, rowid ASC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def mark_rolled_up(self, session_ids: list[str]) -> int:
        """标记一批谈话已参与二级总结；返回实际更新的行数。"""
        if not session_ids:
            return 0
        cur = self._conn.execute(
            f"UPDATE conversation_registry SET rolled_up=1 WHERE session_id IN "
            f"({','.join('?' * len(session_ids))})",
            [str(s) for s in session_ids],
        )
        self._conn.commit()
        return cur.rowcount

    # ---------- 内部 ----------
    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "session_id": row[0], "user_id": row[1], "agent_name": row[2],
            "status": row[3], "started_at": row[4], "ended_at": row[5],
            "summary_json": row[6] or "", "rolled_up": bool(row[7]),
        }


def parse_summary(summary_json: str) -> dict | None:
    """一级总结 JSON 反序列化（坏数据返回 None，调用方按无总结处理）。"""
    if not summary_json:
        return None
    try:
        return json.loads(summary_json)
    except (json.JSONDecodeError, TypeError):
        return None


def summary_topic(summary_json: str) -> str:
    """从一级总结 JSON 中提取主题（窗口摘要行展示用；无总结返回空串）。"""
    data = parse_summary(summary_json)
    return (data or {}).get("topic", "")