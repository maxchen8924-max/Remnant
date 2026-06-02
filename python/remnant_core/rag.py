"""RAG Pipeline 骨架 — Protocol + ABC 定义。

检索增强生成（RAG）管道负责:
1. 全文搜索（FTS5）+ 向量检索（sqlite-vec）
2. 结果融合与重排序
3. 证据验证（Claim-Evidence 对齐）
"""

from __future__ import annotations

import abc
from typing import Any, Protocol, runtime_checkable

from remnant_core.models import ClaimSchema, EvidenceSchema, MemoryChunkSchema


@runtime_checkable
class Retriever(Protocol):
    """检索器协议。"""

    def search_fts(self, query: str, scope_id: str, top_k: int = 10) -> list[dict[str, Any]]:
        """FTS5 全文搜索。"""
        ...

    def search_vector(
        self, query: str, scope_id: str, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """向量相似度搜索。"""
        ...


@runtime_checkable
class Reranker(Protocol):
    """重排序器协议。"""

    def rerank(
        self, query: str, results: list[dict[str, Any]], top_k: int = 5
    ) -> list[dict[str, Any]]:
        """对检索结果重排序。"""
        ...


@runtime_checkable
class EvidenceValidator(Protocol):
    """证据验证器协议。"""

    def validate(
        self, claims: list[ClaimSchema], chunks: list[MemoryChunkSchema]
    ) -> list[EvidenceSchema]:
        """验证 claim 与 chunk 的证据关联。"""
        ...


class BaseRetriever(abc.ABC):
    """检索器基类。"""

    @abc.abstractmethod
    def search_fts(self, query: str, scope_id: str, top_k: int = 10) -> list[dict[str, Any]]:
        """子类必须实现 FTS5 检索。"""
        ...

    @abc.abstractmethod
    def search_vector(
        self, query: str, scope_id: str, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """子类必须实现向量检索。"""
        ...


class BaseReranker(abc.ABC):
    """重排序器基类。"""

    @abc.abstractmethod
    def rerank(
        self, query: str, results: list[dict[str, Any]], top_k: int = 5
    ) -> list[dict[str, Any]]:
        """子类必须实现重排序。"""
        ...


class BaseEvidenceValidator(abc.ABC):
    """证据验证器基类。"""

    @abc.abstractmethod
    def validate(
        self, claims: list[ClaimSchema], chunks: list[MemoryChunkSchema]
    ) -> list[EvidenceSchema]:
        """子类必须实现证据验证。"""
        ...


class RAGPipeline:
    """RAG Pipeline 入口 — 串联检索、重排序、证据验证。

    使用示例::

        pipeline = RAGPipeline(
            retriever=SqliteRetriever(db),
            reranker=CrossEncoderReranker(),
            validator=DefaultEvidenceValidator(),
        )
        result = pipeline.run("爸爸喜欢吃什么？", scope_id="uuid-v7")
    """

    def __init__(
        self,
        retriever: Retriever,
        reranker: Reranker | None = None,
        validator: EvidenceValidator | None = None,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.validator = validator

    def run(
        self,
        query: str,
        scope_id: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """执行完整 RAG 管道。

        Args:
            query: 用户查询文本
            scope_id: 关系作用域 ID
            top_k: 检索返回数量

        Returns:
            包含 fts_results, vector_results, reranked_results 的字典
        """
        fts_results = self.retriever.search_fts(query, scope_id, top_k)
        vector_results = self.retriever.search_vector(query, scope_id, top_k)

        merged_results = fts_results + vector_results
        reranked_results = merged_results

        if self.reranker is not None:
            reranked_results = self.reranker.rerank(query, merged_results, top_k)

        return {
            "fts_results": fts_results,
            "vector_results": vector_results,
            "reranked_results": reranked_results,
        }