# -*- coding: utf-8 -*-
"""工具层-参数校验：按 inputSchema 做类型检查 / 必填校验 / 范围校验等。

校验失败不抛异常，统一返回 (False, 错误提示)——错误提示会作为工具结果
（MCP content 文本）返回给模型，让模型自行修正参数后重试。

支持的 JSON Schema 子集：type / required / enum / minimum / maximum /
exclusiveMinimum / exclusiveMaximum / minLength / maxLength / pattern /
minItems / maxItems / items（一层递归）/ additionalProperties。
"""
from __future__ import annotations

import re

__all__ = ["validate_arguments"]

_TYPE_LABELS = {"string": "字符串", "integer": "整数", "number": "数字",
                "boolean": "布尔值", "array": "数组", "object": "对象", "null": "空值"}


def _type_ok(value, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True  # 未知类型不做拦截（宽松兼容）


def _label(expected) -> str:
    if isinstance(expected, list):
        return " 或 ".join(_TYPE_LABELS.get(e, str(e)) for e in expected)
    return _TYPE_LABELS.get(expected, str(expected))


def _check_value(name: str, value, spec: dict) -> str:
    """校验单个参数值，返回错误提示（空串 = 通过）。"""
    if not isinstance(spec, dict):
        return ""

    expected = spec.get("type")
    if expected:
        # 字符串型约束不匹配时，数字会被 JSON 解析成 number，这里只做严格类型检查
        if isinstance(expected, list):
            if not any(_type_ok(value, e) for e in expected):
                return f"参数校验失败：参数 '{name}' 类型应为 {_label(expected)}，实际为 {type(value).__name__}"
        elif not _type_ok(value, expected):
            return (f"参数校验失败：参数 '{name}' 类型应为 {_label(expected)}"
                    f"（{expected}），实际为 {type(value).__name__}")

    enum = spec.get("enum")
    if enum is not None and value not in enum:
        return f"参数校验失败：参数 '{name}' 取值必须在 {enum} 之内，实际为 {value!r}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            return f"参数校验失败：参数 '{name}' 小于最小值 {spec['minimum']}（实际 {value}）"
        if "maximum" in spec and value > spec["maximum"]:
            return f"参数校验失败：参数 '{name}' 大于最大值 {spec['maximum']}（实际 {value}）"
        if "exclusiveMinimum" in spec and value <= spec["exclusiveMinimum"]:
            return f"参数校验失败：参数 '{name}' 必须大于 {spec['exclusiveMinimum']}（实际 {value}）"
        if "exclusiveMaximum" in spec and value >= spec["exclusiveMaximum"]:
            return f"参数校验失败：参数 '{name}' 必须小于 {spec['exclusiveMaximum']}（实际 {value}）"

    if isinstance(value, str):
        if "minLength" in spec and len(value) < spec["minLength"]:
            return f"参数校验失败：参数 '{name}' 长度不足（最少 {spec['minLength']} 字符）"
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            return f"参数校验失败：参数 '{name}' 长度超限（最多 {spec['maxLength']} 字符）"
        if "pattern" in spec:
            try:
                if not re.search(str(spec["pattern"]), value):
                    return f"参数校验失败：参数 '{name}' 不符合格式要求（pattern: {spec['pattern']}）"
            except re.error:
                pass  # 非法正则视为无约束

    if isinstance(value, (list, tuple)):
        if "minItems" in spec and len(value) < spec["minItems"]:
            return f"参数校验失败：参数 '{name}' 元素不足（最少 {spec['minItems']} 个）"
        if "maxItems" in spec and len(value) > spec["maxItems"]:
            return f"参数校验失败：参数 '{name}' 元素过多（最多 {spec['maxItems']} 个）"
        items = spec.get("items")
        if isinstance(items, dict) and items.get("type"):
            for idx, item in enumerate(value):
                err = _check_value(f"{name}[{idx}]", item, items)
                if err:
                    return err
    return ""


def validate_arguments(schema: dict, args: dict) -> tuple[bool, str]:
    """按 inputSchema 校验入参；返回 (是否通过, 错误提示)。"""
    if not isinstance(args, dict):
        return False, "参数校验失败：调用参数必须是对象（JSON object）"
    if not isinstance(schema, dict):
        return True, ""

    for name in schema.get("required", []) or []:
        if name not in args or args[name] is None:
            return False, f"参数校验失败：缺少必填参数 '{name}'"

    props = schema.get("properties") or {}
    for name, spec in props.items():
        if name not in args:
            continue
        err = _check_value(name, args[name], spec)
        if err:
            return False, err

    if schema.get("additionalProperties") is False:
        extra = [k for k in args if k not in props]
        if extra:
            return False, f"参数校验失败：出现未定义参数 {extra}（本工具不接受额外参数）"

    return True, ""
