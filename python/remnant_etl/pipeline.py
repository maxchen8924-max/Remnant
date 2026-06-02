"""ETL Pipeline 入口 — Protocol + ABC 定义。

定义 ETL 管道各阶段的抽象接口，确保解析器、清洗器、分块器
实现统一的协议，便于管道编排和扩展。
"""

from __future__ import annotations

import abc
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Parser(Protocol):
    """数据解析器协议。

    将原始数据文件（source_artifact）解析为原始消息列表（raw_message）。
    """

    supported_file_type: str

    def parse(self, file_path: str, artifact_id: str) -> list[dict[str, Any]]:
        """解析文件，返回原始消息字典列表。

        Args:
            file_path: 原始文件路径
            artifact_id: source_artifact 的 UUID v7

        Returns:
            原始消息字典列表，每个字典包含 raw_message 表字段
        """
        ...


@runtime_checkable
class Cleaner(Protocol):
    """清洗器协议。

    对 normalized_message 进行清洗和过滤。
    """

    filter_tag: str

    def clean(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """清洗消息列表，返回过滤后的消息。

        Args:
            messages: 规范化消息字典列表

        Returns:
            清洗后的消息列表，被过滤的消息标记 filter_tags
        """
        ...


@runtime_checkable
class Chunker(Protocol):
    """分块器协议。

    将清洗后的规范化消息序列分块为 memory_chunk。
    """

    chunk_type: str

    def chunk(
        self,
        messages: list[dict[str, Any]],
        overlap: int = 2,
    ) -> list[dict[str, Any]]:
        """将消息序列分块。

        Args:
            messages: 规范化消息列表（按时间排序）
            overlap: 相邻 chunk 之间的重叠消息数

        Returns:
            记忆分块字典列表
        """
        ...


class BaseParser(abc.ABC):
    """解析器基类，提供通用工具方法。"""

    supported_file_type: str = ""

    @abc.abstractmethod
    def parse(self, file_path: str, artifact_id: str) -> list[dict[str, Any]]:
        """子类必须实现解析逻辑。"""
        ...

    def validate_file(self, file_path: str) -> bool:
        """验证文件是否存在且可读。"""
        import os

        return os.path.isfile(file_path) and os.access(file_path, os.R_OK)


class BaseCleaner(abc.ABC):
    """清洗器基类。"""

    filter_tag: str = ""

    @abc.abstractmethod
    def clean(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """子类必须实现清洗逻辑。"""
        ...


class BaseChunker(abc.ABC):
    """分块器基类。"""

    chunk_type: str = ""

    @abc.abstractmethod
    def chunk(
        self,
        messages: list[dict[str, Any]],
        overlap: int = 2,
    ) -> list[dict[str, Any]]:
        """子类必须实现分块逻辑。"""
        ...


class ETLPipeline:
    """ETL 管道 — 串联解析、清洗、分块。

    使用示例::

        pipeline = ETLPipeline(
            parser=WechatTxtParser(),
            cleaners=[DuplicateCleaner(), SystemMessageCleaner()],
            chunker=SlidingWindowChunker(overlap=2),
        )
        result = pipeline.run("/path/to/wechat.txt", artifact_id="uuid-v7")
    """

    def __init__(
        self,
        parser: Parser,
        cleaners: list[Cleaner] | None = None,
        chunker: Chunker | None = None,
    ) -> None:
        self.parser = parser
        self.cleaners = cleaners or []
        self.chunker = chunker

    def run(self, file_path: str, artifact_id: str) -> dict[str, Any]:
        """执行完整 ETL 管道。

        Args:
            file_path: 原始文件路径
            artifact_id: source_artifact UUID v7

        Returns:
            包含 raw_messages, normalized_messages, chunks 的字典
        """
        raw_messages = self.parser.parse(file_path, artifact_id)

        normalized_messages = list(raw_messages)
        for cleaner in self.cleaners:
            normalized_messages = cleaner.clean(normalized_messages)

        chunks: list[dict[str, Any]] = []
        if self.chunker is not None:
            chunks = self.chunker.chunk(normalized_messages)

        return {
            "raw_messages": raw_messages,
            "normalized_messages": normalized_messages,
            "chunks": chunks,
        }