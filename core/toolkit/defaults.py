# -*- coding: utf-8 -*-
"""工具层-默认装配：内置工具 + 既有业务工具适配（零重写）+ 角色映射。

build_default_registry() 组装一个开箱可用的 ToolRegistry：
1. 注册内置工具 planning_tool / read_file（类继承方案）；
2. 把项目既有 tools/ 下的业务工具（普通函数，带类型注解）适配成 FunctionTool——
   按函数签名自动生成 inputSchema，不重写任何业务代码；
3. 显式声明每个工具的角色与只读性（阶段二按角色过滤；只读模式隐藏写工具），
   遵循原则一「只暴露任务需要的工具」：内部辅助函数（lookup_order/recommend_for/
   register_return）与约束层自查工具都不进业务工具箱。
"""
from __future__ import annotations

import inspect

from .base import FunctionTool, schema_from_signature
from .builtin_tools import PlanningTool, ReadFileTool
from .registry import ToolRegistry

__all__ = ["build_default_registry", "get_default_registry", "reset_default_registry",
           "BUSINESS_TOOLS"]

# 业务工具 → 可见角色（None = 所有角色可见）。
# 角色与 ROLE 常量保持一致的语义：客服/售前 ｜ 选品研究 ｜ Listing 工作台。
BUSINESS_TOOLS: dict[str, set[str] | None] = {
    # ---- 客服 / 售前 ----
    "query_order_info": {"customer_service", "presales"},
    "track_logistics": {"customer_service", "presales"},
    "handle_return": {"customer_service"},           # 写操作（会登记售后单）
    "recommend_products": {"customer_service", "presales"},
    # ---- 选品研究 ----
    "check_demand": {"research"},
    "check_competition": {"research"},
    "calc_profit": {"research"},
    "run_product_research": {"research"},
    # ---- Listing 工作台 ----
    "search_supplier": {"listing"},
    "compare_supplier": {"listing"},
    "draft_listing": {"listing"},
    "check_images": {"listing"},
    "price_strategy": {"listing"},
    "recommend_fulfillment": {"listing"},
}

_REGISTRY: ToolRegistry | None = None


def build_default_registry() -> ToolRegistry:
    """组装默认注册表（内置工具 + 既有业务工具适配）。"""
    reg = ToolRegistry()
    reg.register(PlanningTool())
    reg.register(ReadFileTool())

    try:  # 业务工具适配：函数签名 → inputSchema；描述优先用注册表元数据（更完整）
        import tools as tools_pkg
        from core.dispatch.registry import GLOBAL_REGISTRY
        from core.constraint.validator import ToolValidator

        validator = ToolValidator()  # 复用「写类工具」判定，推导 read_only 权限元数据
        for name, roles in BUSINESS_TOOLS.items():
            fn = getattr(tools_pkg, name, None)
            if not callable(fn):
                continue
            spec = GLOBAL_REGISTRY.resolve(name)
            description = (spec.description if spec else "") or (inspect.getdoc(fn) or "")
            param_desc = ({k: str(v) for k, v in (spec.schema or {}).items()}
                          if spec else {})
            reg.register(FunctionTool(
                fn, name=name, description=description,
                schema=schema_from_signature(fn, param_desc),
                read_only=not validator._is_write(name),
                roles=roles,
            ))
    except Exception:  # noqa: BLE001 - 适配失败不阻断内置工具可用（旁路容错）
        pass
    return reg


def get_default_registry() -> ToolRegistry:
    """进程级单例（首次调用时装配）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


def reset_default_registry() -> None:
    """重置单例（测试用）。"""
    global _REGISTRY
    _REGISTRY = None
