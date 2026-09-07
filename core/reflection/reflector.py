# -*- coding: utf-8 -*-
"""反思智能体（ReflectionAgent）：自我反思模块的执行者（权限 L2）。

职责（见 docs/memory-system-design.md §3.5 / architecture.md 认知层-反思）：
- distill_skill：把复盘出的四要素直接写入技能记忆（SkillMemory.add_skill，guard L2）；
- distill_from_transcript：复盘文本 → LLM 提炼（skill_writer）→ 逐条入库；
- reflect_on_failure：v0.1 占位——返回复盘引导语（后续接失败会话分析管线）；
- recall_skills：给遇到难点的智能体检索可复用技能（读 L0 开放）。

caller 固定 MemoryCaller("reflector", "L2")：写技能必须 L2，防止普通智能体乱写。
"""
from __future__ import annotations

from typing import Any

from memory.access import MemoryCaller

from .skill_writer import build_skill_entries

__all__ = ["ReflectionAgent"]


class ReflectionAgent:
    """技能提炼 + 失败复盘智能体。storage 为 SkillMemory 或 MemoryManager（鸭子类型）。"""

    caller = MemoryCaller("reflector", "L2")

    def __init__(self, storage: Any):
        """storage：持有 add_skill / search_skills / feedback 的对象。

        传入 MemoryManager 或 SkillMemory 均可（两者接口对齐）。
        """
        self.storage = storage

    # ---------- 技能入库 ----------
    def distill_skill(self, situation: str, goal: str, pain: str,
                      solution: str, tags: list[str] | None = None,
                      trigger: str = "") -> int:
        """四要素直写技能记忆（guard L2）；返回新技能 id。

        调用时机：人工复盘 / 主管智能体授权的确定结论。
        """
        return self.storage.add_skill(
            situation, goal, pain, solution,
            tags=tags, trigger=trigger, caller=self.caller,
        )

    def distill_from_transcript(self, transcript: str,
                                api_key: str | None = None,
                                base_url: str | None = None,
                                model: str | None = None) -> list[int]:
        """复盘文本 → LLM 提炼四要素（无 Key 产出 []）→ 逐条入库；返回技能 id 列表。"""
        ids: list[int] = []
        for entry in build_skill_entries(transcript, api_key=api_key,
                                         base_url=base_url, model=model):
            try:
                ids.append(self.distill_skill(
                    situation=entry["situation"], goal=entry["goal"],
                    pain=entry["pain"], solution=entry["solution"],
                    tags=entry["tags"], trigger=entry["trigger"],
                ))
            except PermissionError:  # 越权（不应发生）——跳过该条
                continue
        return ids

    # ---------- 失败复盘（v0.1 占位） ----------
    def reflect_on_failure(self, session_id: str, detail: str = "") -> dict:
        """失败复盘：v0.1 输出引导语，提示通过 distill_from_transcript 提炼技能。

        # TODO（扩展位）：拉取该谈话 checkpoint 原文 → 自动分析失败原因
        # → 提炼技能 / 回写用户画像。当前仅返回占位引导，不阻塞主流程。
        """
        hint = (
            "复盘引导（v0.1）：请围绕「遇到了什么事 / 当时想达到什么目的 / "
            "卡在哪个痛点 / 最后怎么解决的」四要素复盘本次失败。"
            "可将复盘文本交给 distill_from_transcript 自动提炼为技能记忆；"
            "后续版本将自动拉取谈话原文完成此分析。"
        )
        return {
            "ok": True, "session_id": str(session_id),
            "detail": str(detail)[:500], "message": hint,
        }

    # ---------- 技能检索（给遇到难点的智能体用） ----------
    def recall_skills(self, text: str, top_k: int = 5) -> list[dict]:
        """按关键词检索可复用技能（读取 L0，无需鉴权）。"""
        return self.storage.search_skills(text, top_k=top_k)