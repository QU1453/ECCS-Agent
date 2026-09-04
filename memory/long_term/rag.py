# -*- coding: utf-8 -*-
"""嵌入层：EmbeddingProvider 接口 + 缓存。

- OpenAIEmbeddingProvider：复用项目 OpenAI 兼容配置（OPENAI_API_KEY / OPENAI_BASE_URL，
  模型默认 text-embedding-3-small，可用 OPENAI_EMBEDDING_MODEL 覆盖）；
- HashEmbeddingProvider：本地确定性降级（无 Key 演示管道用，非语义真向量）；
- EmbeddingCache：text_hash → 向量（SQLite BLOB），重复文本零重复计算，批量入库走批量 embed。

接口可替换（BGE / 本地模型 / 其他服务商），存储层不动；未来换 pgvector 等同理。
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from abc import ABC, abstractmethod
from array import array

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u2e80-\u9fff\u3040-\u30ff]")


def text_hash(text: str) -> str:
    """文本内容指纹（SHA-256）：嵌入缓存的 key，同文本只算一次向量。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vec_to_blob(vec: list[float]) -> bytes:
    """float 向量 → SQLite BLOB（float32 数组字节）。"""
    return array("f", vec).tobytes()


def blob_to_vec(blob: bytes) -> list[float]:
    """SQLite BLOB → float 向量（vec_to_blob 的逆操作）。"""
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


class EmbeddingProvider(ABC):
    """嵌入提供方接口。dim 在首次给出向量前可能未知（OpenAI 需探测）。"""

    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbeddingProvider(EmbeddingProvider):
    """本地确定性降级：hash 词袋 + L2 归一化。演示管道用，语义质量有限。"""

    def __init__(self, dim: int = 256):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """词袋哈希向量（token → 桶计数 → L2 归一化）；确定性、零网络依赖。"""
        out = []
        for t in texts:
            v = [0.0] * self._dim
            for tok in _TOKEN_RE.findall((t or "").lower()):
                v[hash(tok) % self._dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容嵌入（密钥只从环境变量/入参读取，本模块不落盘任何密钥）。"""

    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        from langchain_openai import OpenAIEmbeddings  # 延迟导入：无 Key 时不必装/不触发

        self.model = model or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self._client = OpenAIEmbeddings(
            model=self.model,
            api_key=api_key or os.getenv("OPENAI_API_KEY") or None,
            base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
        )
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        """向量维度（首次访问时用一条探测文本实测并缓存）。"""
        if self._dim is None:
            self._dim = len(self.embed(["dim probe"])[0])
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本 → 向量（OpenAI 兼容 embedding 接口）。"""
        return self._client.embed_documents(list(texts))


def pick_provider(explicit: EmbeddingProvider | None = None) -> EmbeddingProvider:
    """显式传入优先；否则有 OPENAI_API_KEY 用 OpenAI 兼容，否则本地降级。"""
    if explicit is not None:
        return explicit
    if os.getenv("OPENAI_API_KEY", "").strip():
        return OpenAIEmbeddingProvider()
    return HashEmbeddingProvider()


class EmbeddingCache:
    """text_hash → 向量缓存（复用长期库连接），保证同文本只算一次。"""

    def __init__(self, conn: sqlite3.Connection, provider: EmbeddingProvider):
        self._conn = conn
        self.provider = provider
        conn.execute(
            "CREATE TABLE IF NOT EXISTS embed_cache("
            "text_hash TEXT PRIMARY KEY, dim INTEGER NOT NULL, vector BLOB NOT NULL)"
        )
        conn.commit()
        row = conn.execute("SELECT dim FROM embed_cache LIMIT 1").fetchone()
        self._dim: int | None = row[0] if row else None

    @property
    def dim(self) -> int:
        """当前维度：缓存表已有记录用缓存值，否则取 Provider 实测值。"""
        return self._dim if self._dim is not None else self.provider.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入（读缓存 → 只对未命中文本调 Provider → 回填缓存）。"""
        if not texts:
            return []
        hashes = [text_hash(t) for t in texts]
        found: dict[str, list[float]] = {}
        for i in range(0, len(hashes), 500):  # 分块 IN 查询，避开 SQL 变量上限
            batch = hashes[i:i + 500]
            sql = f"SELECT text_hash, vector FROM embed_cache WHERE text_hash IN ({','.join('?' * len(batch))})"
            for h, blob in self._conn.execute(sql, batch):
                found[h] = blob_to_vec(blob)
        missing = [t for t, h in zip(texts, hashes) if h not in found]
        if missing:
            vecs = self.provider.embed(missing)
            dim = len(vecs[0])
            if self._dim is None:
                self._dim = dim
            if any(len(v) != dim for v in vecs) or dim != self._dim:
                raise ValueError(f"嵌入维度不一致：期望 {self._dim}，实际含 {dim}")
            new_rows = [
                (text_hash(t), dim, vec_to_blob(v)) for t, v in zip(missing, vecs)
            ]
            for h, _d, blob in new_rows:  # 回填内存，再落库
                found[h] = blob_to_vec(blob)
            self._conn.executemany(
                "INSERT OR REPLACE INTO embed_cache(text_hash, dim, vector) VALUES(?,?,?)",
                new_rows,
            )
            self._conn.commit()
        return [found[h] for h in hashes]

    def get_by_hash(self, h: str) -> list[float] | None:
        """按文本指纹取向量（重排阶段用）；无缓存返回 None。"""
        row = self._conn.execute("SELECT vector FROM embed_cache WHERE text_hash=?", (h,)).fetchone()
        return blob_to_vec(row[0]) if row else None
