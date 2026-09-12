# -*- coding: utf-8 -*-
"""工具层-工具基类：BaseTool（类继承方案）+ FunctionTool（既有函数零重写适配）。

注册分发机制（用户规范）：
    class BaseTool:
        name: str = ''
        read_only: bool = True
        def get_schema(self) -> dict: raise NotImplementedError
        def execute(self, args: dict, config: AgentConfig) -> tuple[bool, str]: ...

- read_only 标记工具是否只读，为权限控制提供元数据支撑（暴露进 MCP annotations.readOnlyHint）；
- get_schema 返回 MCP 口径的 inputSchema（JSON Schema 子集：type/required/min/max/enum…）；
- execute 返回 (是否成功, 结果文本)；**异常由上层 registry 统一兜住转给模型**，
  工具实现本身可放心抛错（内层也会尽量转成 (False, 文本)）。

FunctionTool 把项目既有的普通函数（tools/ 下 16 个业务工具，带类型注解）适配成 BaseTool：
按函数签名自动生成 JSON Schema（类型 + 必填），无需重写任何业务代码。
"""
from __future__ import annotations

import inspect
import types
import typing
from abc import ABC, abstractmethod

from .types import AgentConfig

__all__ = ["BaseTool", "FunctionTool", "schema_from_signature"]


class BaseTool(ABC):
    """工具基类：子类只需声明元数据 + 实现 get_schema / execute。"""

    name: str = ""
    description: str = ""
    read_only: bool = True          # 只读标记（权限控制元数据）
    roles: set[str] | None = None   # 阶段二按角色过滤；None = 所有角色可见
    planning_only: bool = False     # True = 仅规划阶段（阶段一）暴露

    @abstractmethod
    def get_schema(self) -> dict:
        """返回 MCP inputSchema（JSON Schema 子集）。"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, args: dict, config: AgentConfig) -> tuple[bool, str]:
        """执行工具，返回 (是否成功, 结果文本)；异常应抛出，由 registry 兜底转给模型。"""
        raise NotImplementedError

    # ---- 接口描述：MCP tools/list 条目 + OpenAI function 条目（模型协商双格式）--------
    def mcp_entry(self) -> dict:
        """MCP tools/list 数组元素：name / description / inputSchema / annotations。"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.get_schema(),
            "annotations": {"readOnlyHint": bool(self.read_only)},
        }

    def openai_entry(self) -> dict:
        """OpenAI function-calling 格式（供 chat.completions 的 tools 参数直接使用）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_schema(),
            },
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} read_only={self.read_only}>"


# ---- 类型注解 → JSON Schema 子集（既有函数的签名自动转 schema）-------------------------
def _schema_for_annotation(ann) -> dict:
    """把单个 Python 类型注解转成 JSON Schema 片段（支持 Optional/Union/list[T]/dict）。"""
    if ann is inspect.Parameter.empty or ann is None:
        return {}
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)

    # Optional[X] / Union[X, None] / X | None：取第一个非 None 分支
    union_types = {typing.Union, types.UnionType}
    if origin in union_types and args:
        non_none = [a for a in args if a is not type(None)]
        return _schema_for_annotation(non_none[0]) if non_none else {}

    # list[T] / set[T] / tuple[T, ...]
    if origin in (list, set, tuple, frozenset):
        item = _schema_for_annotation(args[0]) if args else {}
        schema = {"type": "array"}
        if item:
            schema["items"] = item
        return schema
    if origin is dict:
        return {"type": "object"}

    if ann is bool:
        return {"type": "boolean"}
    if ann is int:
        return {"type": "integer"}
    if ann is float:
        return {"type": "number"}
    if ann is str:
        return {"type": "string"}
    if ann is list:
        return {"type": "array"}
    if ann is dict:
        return {"type": "object"}
    return {}


def schema_from_signature(fn, param_descriptions: dict | None = None) -> dict:
    """按函数签名生成 inputSchema：必填 = 无默认值且非可变参数。

    注意：项目模块普遍使用 `from __future__ import annotations`，
    此时 param.annotation 是字符串（如 "list | None"），必须用 get_type_hints 解析，
    否则 int / float / list 参数会被误判为 string。
    """
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001 - 注解无法解析（前向引用等）时退回字符串注解
        hints = {}
    props: dict[str, dict] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        prop = _schema_for_annotation(hints.get(pname, param.annotation))
        if not prop:
            prop = {"type": "string"}  # 无注解时宽松处理（校验不做类型强约束）
        desc = (param_descriptions or {}).get(pname)
        if desc:
            prop = {**prop, "description": str(desc)}
        props[pname] = prop
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


class FunctionTool(BaseTool):
    """把普通函数适配为 BaseTool（既有 16 个业务工具零重写接入）。"""

    def __init__(self, fn, *, name: str = "", description: str = "",
                 schema: dict | None = None, read_only: bool = True,
                 roles: set[str] | None = None, planning_only: bool = False):
        self._fn = fn
        self.name = name or getattr(fn, "__name__", "function")
        self.description = description or (inspect.getdoc(fn) or "")
        self._schema = schema
        self.read_only = bool(read_only)
        self.roles = roles
        self.planning_only = planning_only

    def get_schema(self) -> dict:
        if self._schema is None:
            self._schema = schema_from_signature(self._fn)
        return self._schema

    def execute(self, args: dict, config: AgentConfig) -> tuple[bool, str]:
        """调用原函数：成功返回 (True, 文本)；异常转 (False, 错误文本) 交给模型。"""
        try:
            result = self._fn(**(args or {}))
        except Exception as exc:  # noqa: BLE001 - 工具内部异常必须回到模型
            return False, f"工具执行失败（{exc.__class__.__name__}）：{exc}"
        return True, str(result or "")
