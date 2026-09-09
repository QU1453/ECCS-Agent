# -*- coding: utf-8 -*-
"""约束层（core/constraint）：规则约束 + 框架约束 + 循环守卫子智能体 + 局部工具注册表。

职责：在认知流水线外再包一圈“行为边界”——
- 规则约束（rules.py）：内容红线（注入/越狱/套密钥/敏感内容），输入否决 + 输出脱敏；
- 框架约束（framework.py）：结构性预算（长度/频率/会话轮次），防刷与费用失控；
- 循环守卫（loop_guard.py）：重复提问 / 雷同回复 / 兜底熔断三类循环信号检测；
- 局部注册表（tools.py）：约束层自有工具（LLM 描述遵循项目统一范式）。

统一门面 ConstraintLayer（layer.py）：编排器只跟它打交道；
旁路容错——约束层自身故障时降级为“无约束”，绝不阻断问答主链路。
"""
from .budget import BudgetGuard
from .framework import FrameworkGuard, FrameworkVerdict
from .layer import (ConstraintLayer, ConstraintVerdict, ToolCallVerdict,
                    ensure_current_session, get_constraint_layer, get_current_session,
                    set_current_session)
from .loop_guard import LoopGuard, LoopSignal
from .rules import RuleGuard, RuleVerdict
from .tool_loop import ToolLoopGuard
from .validator import ToolValidator, ToolVerdict

__all__ = [
    "ConstraintLayer", "ConstraintVerdict", "ToolCallVerdict", "get_constraint_layer",
    "set_current_session", "ensure_current_session", "get_current_session",
    "RuleGuard", "RuleVerdict",
    "FrameworkGuard", "FrameworkVerdict",
    "LoopGuard", "LoopSignal",
    "ToolValidator", "ToolVerdict",
    "ToolLoopGuard", "BudgetGuard",
]

# 触发局部工具注册表登记（导入即注册，与 tools/ 模块同模式）
from . import tools  # noqa: E402,F401  (副作用导入：注册约束层工具到局部+全局注册表)
