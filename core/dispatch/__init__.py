# -*- coding: utf-8 -*-
"""调度控制（dispatch）：编排器 + 双层工具注册表 + 工具路由兜底。

注意：Orchestrator 依赖 agents 包（业务层），为避免
core.dispatch <-> agents 循环导入，编排器不在本包 __init__ 预导入，
使用方请直接 `from core.dispatch.orchestrator import Orchestrator`。
"""
from .registry import (
    GLOBAL_REGISTRY,
    LocalRegistry,
    RegistryError,
    ToolSpec,
)

__all__ = ["GLOBAL_REGISTRY", "LocalRegistry", "RegistryError", "ToolSpec"]