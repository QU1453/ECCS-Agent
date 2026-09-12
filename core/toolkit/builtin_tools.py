# -*- coding: utf-8 -*-
"""工具层-内置工具：planning_tool（阶段一规划）+ read_file（只读示例）。

两个工具都用「类继承 BaseTool」方案手写，作为注册分发机制的范例：
- planning_tool：仅规划阶段（planning_only=True）暴露，前 N 轮只给模型这一个工具，
  让它先把任务拆成计划，再进入执行阶段暴露真正的工具集；
- read_file：read_only=True，schema 与用户给的接口描述示例一致
  （path 必填；offset/limit 分页读大文件），是「只读工具」的权限元数据样例。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import config

from .base import BaseTool
from .types import AgentConfig, estimate_planning_rounds

__all__ = ["PlanningTool", "ReadFileTool"]


class PlanningTool(BaseTool):
    """规划工具：把任务拆成可执行步骤（阶段一唯一暴露的工具）。"""

    name = "planning_tool"
    description = (
        "Plan a task before acting. Use it only in the planning phase: "
        "break the user's goal into ordered steps, list the tools you will need, "
        "and state the files or data each step touches."
    )
    read_only = True
    planning_only = True
    roles = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The user's goal / task to plan"},
                "known_context": {"type": "string",
                                  "description": "Any facts already known (optional)"},
                "steps": {"type": "array", "description": "Draft steps, if already formed",
                          "items": {"type": "string"}},
            },
            "required": ["task"],
        }

    def execute(self, args: dict, config_: AgentConfig) -> tuple[bool, str]:
        task = str(args.get("task") or "").strip()
        if not task:
            return False, "参数错误：task 不能为空"
        draft = [str(s).strip() for s in (args.get("steps") or []) if str(s).strip()]
        suggested_rounds = estimate_planning_rounds(len(draft) or 1)
        plan = {
            "task": task,
            "known_context": str(args.get("known_context") or ""),
            "steps": draft or [
                "明确目标与验收标准",
                "定位相关信息（检索/列目录/读文件）",
                "执行最小必要改动",
                "验证结果并汇报",
            ],
            "suggested_planning_rounds": suggested_rounds,
            "hint": "先完成本计划，再进入执行阶段调用具体工具；执行阶段不要重复规划。",
        }
        return True, json.dumps(plan, ensure_ascii=False)


class ReadFileTool(BaseTool):
    """只读文件工具：按 offset/limit 分页读取（大文件友好）。"""

    name = "read_file"
    description = "Read a file. Use offset/limit for large files."
    read_only = True
    roles = None

    def get_schema(self) -> dict:
        # 与用户规范中的接口描述示例保持一致
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "Start line (0-based)", "minimum": 0},
                "limit": {"type": "integer", "description": "Max lines to read",
                          "minimum": 1, "maximum": 2000},
            },
            "required": ["path"],
        }

    def execute(self, args: dict, config_: AgentConfig) -> tuple[bool, str]:
        raw = str(args.get("path") or "").strip()
        if not raw:
            return False, "参数错误：path 不能为空"
        offset = int(args.get("offset") or 0)
        limit = int(args.get("limit") or 200)

        path = Path(os.path.expanduser(raw))
        if not path.is_absolute():
            path = Path(config.BASE_DIR) / path
        real = os.path.realpath(path)

        # 兜底路径策略：只在允许的根目录内读写（与验证层同源，宁紧勿松）
        roots = [os.path.realpath(os.path.expanduser(r)) for r in config.TOOL_PATH_ROOTS]
        if not any(real == r or real.startswith(r + os.sep) or real.startswith(r + "/")
                   for r in roots):
            return False, (f"路径检查失败：{raw} 越出允许的根目录（{config.TOOL_PATH_ROOTS}）")
        if not os.path.isfile(real):
            return False, f"文件不存在：{raw}"

        try:
            text = Path(real).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return False, f"读取失败（{exc.__class__.__name__}）：{exc}"

        lines = text.splitlines()
        selected = lines[offset: offset + max(limit, 0)]
        return True, json.dumps({
            "path": str(path),
            "offset": offset,
            "limit": limit,
            "total_lines": len(lines),
            "returned": len(selected),
            "content": "\n".join(selected),
        }, ensure_ascii=False)
