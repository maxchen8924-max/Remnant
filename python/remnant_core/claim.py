"""Claim 提取与对齐骨架。

负责从 LLM 响应中提取事实声明（Claim），
并与记忆分块（MemoryChunk）进行证据对齐。

核心流程:
1. 从 LLM 响应文本中提取 Claim
2. 为每个 Claim 匹配证据（Claim-Evidence 对齐）
3. 验证证据充分性，标记 INSUFFICIENT_EVIDENCE
"""

from __future__ import annotations

import abc
from typing import Any

from remnant_core.models import ClaimSchema, EvidenceSchema, MemoryChunkSchema


class ClaimExtractorBase(abc.ABC):
    """Claim 提取器基类。"""

    @abc.abstractmethod
    def extract(
        self, response_text: str, scope_id: str, session_id: str
    ) -> list[ClaimSchema]:
        """从 LLM 响应文本中提取事实声明。

        Args:
            response_text: LLM 生成的响应文本
            scope_id: 关系作用域 ID
            session_id: 交互会话 ID

        Returns:
            提取出的 ClaimSchema 列表
        """
        ...


class ClaimAlignerBase(abc.ABC):
    """Claim 对齐器基类 — 将 Claim 与 Chunk 证据对齐。"""

    @abc.abstractmethod
    def align(
        self,
        claims: list[ClaimSchema],
        chunks: list[MemoryChunkSchema],
    ) -> list[EvidenceSchema]:
        """将 Claim 与 Chunk 进行证据对齐。

        Args:
            claims: 事实声明列表
            chunks: 记忆分块列表

        Returns:
            EvidenceSchema 列表
        """
        ...


class DefaultClaimExtractor(ClaimExtractorBase):
    """默认 Claim 提取器 — 使用 LLM 提取声明。

    M1 阶段实现具体逻辑。
    """

    def extract(
        self, response_text: str, scope_id: str, session_id: str
    ) -> list[ClaimSchema]:
        """M1 阶段实现。"""
        return []


class DefaultClaimAligner(ClaimAlignerBase):
    """默认 Claim 对齐器。

    M1 阶段实现具体逻辑。
    """

    def align(
        self,
        claims: list[ClaimSchema],
        chunks: list[MemoryChunkSchema],
    ) -> list[EvidenceSchema]:
        """M1 阶段实现。"""
        return []