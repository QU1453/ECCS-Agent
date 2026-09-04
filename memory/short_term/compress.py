# -*- coding: utf-8 -*-
"""记忆压缩（Memory Compression）：超阈值消息 → LLM 滚动摘要 + 旧消息裁剪。

- llm 依赖注入（langchain BaseChatModel，接入方传项目里的 ChatOpenAI 即可）；
- 无 LLM / LLM 调用失败时自动降级：只做窗口裁剪，不产生摘要，保证记忆上限可控；
- 摘要与裁剪均不动接入方的 state schema（摘要由 ShortTermMemory 独立存储）。
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, RemoveMessage

_ROLE_CN = {"human": "用户", "ai": "客服", "system": "系统", "tool": "工具"}


def _content_text(content) -> str:
    """消息 content 统一转文本（兼容 str / content blocks 列表两种形态）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # 兼容 content blocks
        return " ".join(str(x) for x in content)
    return str(content)


class Compressor:
    """滚动摘要压缩器。available=False 时运行在纯裁剪降级模式。"""

    def __init__(self, llm=None, compress_threshold: int = 30, keep_recent: int = 10):
        self.llm = llm
        self.compress_threshold = max(compress_threshold, keep_recent + 1)
        self.keep_recent = keep_recent

    @property
    def available(self) -> bool:
        return self.llm is not None

    def needs_compress(self, msg_count: int) -> bool:
        """消息数超过阈值时返回 True（阈值自动抬升到 keep_recent+1 以上）。"""
        return msg_count > self.compress_threshold

    def summarize(self, msgs: list[BaseMessage], previous_summary: str = "") -> str:
        """把旧消息压缩合并进滚动摘要；无 LLM / 失败时返回原摘要（不丢信息）。"""
        if not self.available or not msgs:
            return previous_summary
        lines = [
            f"{_ROLE_CN.get(getattr(m, 'type', ''), str(getattr(m, 'type', '')))}: {_content_text(getattr(m, 'content', ''))}"
            for m in msgs
        ]
        prompt = (
            "你是客服对话记忆压缩器。请把下面的对话压缩为一段简洁的滚动摘要，"
            "保留：用户诉求、关键事实（订单号/金额/时间/结论）、未完成事项。\n"
            + (f"已有此前摘要：\n{previous_summary}\n" if previous_summary else "")
            + "新增对话：\n" + "\n".join(lines)
            + "\n只输出摘要正文，不要解释。"
        )
        try:
            resp = self.llm.invoke(prompt)
            text = getattr(resp, "content", "") or ""
            return text if isinstance(text, str) else "\n".join(str(x) for x in text)
        except Exception:  # 网络/额度异常：保底返回原摘要
            return previous_summary

    @staticmethod
    def messages_to_remove(msgs: list[BaseMessage], keep_last: int = 0) -> list[RemoveMessage]:
        """生成 RemoveMessage 列表（langgraph add_messages reducer 认识它），用于裁剪 checkpoint。"""
        targets = msgs[:-keep_last] if keep_last else msgs
        return [RemoveMessage(id=m.id) for m in targets if getattr(m, "id", None)]
