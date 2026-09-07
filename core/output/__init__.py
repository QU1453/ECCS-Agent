# -*- coding: utf-8 -*-
"""认知层-输出：回复清洗校验（validator） + 结构化包装（formatter）。"""
from .formatter import wrap
from .validator import sanitize_reply

__all__ = ["sanitize_reply", "wrap"]