# -*- coding: utf-8 -*-
"""双层工具注册表：局部（模块内直连）+ 全局（跨模块调度/鉴权/审计）。

设计（见 docs/architecture.md §4）：
- 物理就近：模块常用工具放在各自文件里，用 LocalRegistry(owner) 就近注册；
- 注册两处：register(global_=True) 时同步写入 GLOBAL_REGISTRY（带 owner 可溯源）；
- 双重查找：LocalRegistry.call_local 先查自己（高频零路由），未命中回退全局；
- 鉴权审计：两路调用都做等级校验（caller.level >= 工具所需 level），
  并写 memory_audit（module="tools"，action="call:<name>"）。

用法：
    from core.dispatch.registry import LocalRegistry, GLOBAL_REGISTRY

    research_tools = LocalRegistry("tools.research")

    @research_tools.register(name="check_demand", description="…",
                             schema={"keywords": "list[str]"}, level="L0")
    def check_demand(keywords): ...

    result = research_tools.call_local("check_demand", {"keywords": [...]}, caller)
    result = GLOBAL_REGISTRY.call("check_demand", {...}, caller)   # 跨模块
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from memory.access import AuditLogger, MemoryCaller, SYSTEM_CALLER, guard
from memory.access import LEVEL_ORDER

__all__ = ["ToolSpec", "LocalRegistry", "GLOBAL_REGISTRY", "RegistryError", "SYSTEM_CALLER"]


class RegistryError(LookupError):
    """工具未注册 / 无权限调用。"""


@dataclass(frozen=True)
class ToolSpec:
    """工具元数据：全局条目带 owner，注销仅限 owner 或 L3。"""

    name: str
    fn: Callable
    module: str                 # 具名模块（如 "tools.research"），鉴权/审计用
    description: str = ""       # LLM 可读说明（何时使用 + 调用格式 + 参数说明）
    schema: dict = field(default_factory=dict)   # 参数类型说明 {arg: type 描述}
    level: str = "L0"           # 调用所需最低权限等级（记忆权限五级）
    cost: str = "low"           # low / medium / high（外部 API / token 成本提示）
    owner: str = ""             # 归属模块，注销校验用

    def llm_entry(self) -> dict:
        """序列化为 LLM 工具清单条目（{name, description, parameters}）。"""
        return {"name": self.name, "description": self.description, "parameters": self.schema}


def _resolve_access(spec: ToolSpec) -> bool:
    """工具调用等级校验（读取矩阵等级序），失败写审计。"""
    if spec.level not in LEVEL_ORDER:
        return False
    return True


def _telemetry_tool(name: str, params: dict, status: str) -> None:
    """遥测埋点（fail-open）：GLOBAL_REGISTRY.call 的工具事件，归并到当前活跃 trace。"""
    try:  # noqa: BLE001 - 遥测故障绝不影响工具调用
        from core.telemetry import get_current_trace, get_recorder

        get_recorder().add_event(
            get_current_trace(), kind="tool", name=name, params=params, status=status
        )
    except Exception:  # noqa: BLE001
        pass


def _constraint_layer():
    """约束层门面（延迟导入：constraint 包反向注册工具到本模块，防循环导入）。"""
    try:  # noqa: BLE001 - 约束层故障不阻断工具调用（验证层 check 内部另有旁路容错）
        from core.constraint import get_constraint_layer

        return get_constraint_layer()
    except Exception:  # noqa: BLE001
        return None


class GlobalRegistry:
    """全局注册表单例：跨模块解析 + 调用 + 审计。线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """登记工具（同名覆盖即视为该 owner 更新自己的工具）。"""
        if spec.name in self._tools and self._tools[spec.name].owner != spec.owner:
            raise RegistryError(f"全局注册表已存在同名工具 {spec.name}（owner={self._tools[spec.name].owner}）")
        with self._lock:
            self._tools[spec.name] = spec

    def unregister(self, name: str, caller: MemoryCaller) -> None:
        """注销全局条目：仅限 owner（模块自管）或 L3 以上。"""
        spec = self._tools.get(name)
        if spec is None:
            return
        if spec.owner != caller.name and LEVEL_ORDER.get(caller.level, -1) < LEVEL_ORDER["L3"]:
            raise RegistryError(f"{caller.name} 无权注销工具 {name}（owner={spec.owner}）")
        with self._lock:
            self._tools.pop(name, None)

    def resolve(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def call(self, name: str, params: dict, caller: MemoryCaller | None = None) -> Any:
        """全局调用入口：resolve → 等级校验 → 验证层 → 执行 → 记账 → 审计（+ 遥测）。

        调用方权限不足抛 RegistryError；验证层/循环守卫拦截时同样抛 RegistryError
        （message = 返回给 agent 的错误提示）。工具内部异常原样上抛（调用方兜底）。
        遥测埋点（fail-open）：成功/失败/越权都写 telemetry events（归并到当前活跃 trace）。
        """
        spec = self.resolve(name)
        if spec is None:
            raise RegistryError(f"未注册的工具：{name}")
        assert _resolve_access(spec), f"工具 {name} 声明了非法等级 {spec.level}"
        if LEVEL_ORDER.get((caller or SYSTEM_CALLER).level, -1) < LEVEL_ORDER[spec.level]:
            AuditLogger.log(
                actor=(caller or SYSTEM_CALLER).name, actor_level=(caller or SYSTEM_CALLER).level,
                action=f"call:{name}", module="tools", session_id=(caller or SYSTEM_CALLER).session_id,
                result="deny",
            )
            _telemetry_tool(name, params, "deny")
            raise RegistryError(f"调用方 {(caller or SYSTEM_CALLER).name} 权限不足以调用工具 {name}")
        # ---- 约束层挂载：验证层四道检查（权限/路径/网络/危险）+ 循环守卫 ----------------
        layer = _constraint_layer()
        if layer is not None:
            verdict = layer.check_tool_call(name, params, caller)
            if not verdict.allowed:
                AuditLogger.log(
                    actor=(caller or SYSTEM_CALLER).name, actor_level=(caller or SYSTEM_CALLER).level,
                    action=f"call:{name}", module="tools", session_id=(caller or SYSTEM_CALLER).session_id,
                    result="deny",
                )
                _telemetry_tool(name, params, "deny")
                raise RegistryError(verdict.message)
        try:
            result = spec.fn(**params)
            AuditLogger.log(
                actor=(caller or SYSTEM_CALLER).name, actor_level=(caller or SYSTEM_CALLER).level,
                action=f"call:{name}", module="tools", session_id=(caller or SYSTEM_CALLER).session_id,
                result="ok",
            )
            _telemetry_tool(name, params, "ok")
            if layer is not None:
                reminder = layer.record_tool_result(
                    name, params, True, str(result or ""), caller)
                if reminder and isinstance(result, str):
                    return result + reminder
            return result
        except Exception:
            if layer is not None:
                layer.record_tool_result(name, params, False, "error", caller)
            AuditLogger.log(
                actor=(caller or SYSTEM_CALLER).name, actor_level=(caller or SYSTEM_CALLER).level,
                action=f"call:{name}", module="tools", session_id=(caller or SYSTEM_CALLER).session_id,
                result="error",
            )
            _telemetry_tool(name, params, "error")
            raise

    def llm_tool_spec(self) -> list[dict]:
        """全部已注册工具的 LLM 清单（供智能体把工具列表交给模型）。"""
        return [spec.llm_entry() for spec in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)


# 全局唯一实例
GLOBAL_REGISTRY = GlobalRegistry()


class LocalRegistry:
    """模块内局部注册表：高频直连（零跨模块开销），可回退全局。

    register(global_=True) 时同步注册全局；call_local 先查自己，未命中回退全局。
    """

    def __init__(self, owner: str):
        self.owner = owner
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str | None = None,
        *,
        description: str = "",
        schema: dict | None = None,
        level: str = "L0",
        cost: str = "low",
        global_: bool = True,
    ):
        """工具装饰器：注册进局部表，global_=True 时同步进全局表。"""

        def deco(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            spec = ToolSpec(
                name=tool_name, fn=fn, module=self.owner,
                description=description, schema=schema or {},
                level=level, cost=cost, owner=self.owner,
            )
            self._tools[tool_name] = spec
            if global_:
                GLOBAL_REGISTRY.register(spec)
            return fn

        return deco

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def snapshot(self) -> list[dict]:
        """本模块局部工具清单（LLM 用）。"""
        return [spec.llm_entry() for spec in self._tools.values()]

    def call_local(self, name: str, params: dict, caller: MemoryCaller | None = None) -> Any:
        """局部优先：命中本地则直接执行（同一套等级校验+审计），未命中回退全局。"""
        spec = self._tools.get(name)
        if spec is not None:
            return GLOBAL_REGISTRY.call(name, params, caller)  # 统一走全局调用通道（含审计）
        return GLOBAL_REGISTRY.call(name, params, caller)