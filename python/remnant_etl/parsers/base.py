"""解析器基类和共享数据结构。

定义 RawMessage dataclass、BaseParser ABC、generate_uuid() 工具函数，
为所有数据源解析器提供统一接口和共享基础设施。
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def generate_uuid() -> str:
    """生成 UUID v7 格式的唯一标识符。

    v0.1 使用 uuid4 作为回退，保证全局唯一性。
    后续版本将迁移到真正的 UUID v7（时间排序）。

    Returns:
        36 字符的 UUID 字符串
    """
    return str(uuid.uuid4())


@dataclass
class RawMessage:
    """原始消息数据结构 — 解析器输出的最小单元。

    每条原始消息对应 source_artifact 中的一条记录，
    将被写入 raw_message 表。不可变，解析后不再修改。

    Attributes:
        id: 消息唯一 ID（UUID）
        source_artifact_id: 所属数据来源文件 ID
        timestamp: 消息时间戳（ISO 8601 格式字符串，解析时不保证时区）
        speaker: 说话人原始名称
        content: 消息正文（原始文本，可能包含未清洗内容）
        content_type: 内容类型标记（text / image / voice / file / system / recall）
        metadata: 扩展元数据 JSON 字典
        parse_status: 解析状态（OK / PARTIAL / SKIPPED）
    """

    id: str
    source_artifact_id: str
    timestamp: str | None
    speaker: str
    content: str
    content_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    parse_status: str = "OK"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，方便写入数据库。"""
        import json

        return {
            "id": self.id,
            "source_artifact_id": self.source_artifact_id,
            "timestamp": self.timestamp,
            "speaker": self.speaker,
            "content": self.content,
            "content_type": self.content_type,
            "parse_status": self.parse_status,
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
        }


class BaseParser(abc.ABC):
    """解析器抽象基类。

    所有数据源解析器必须继承此类并实现 parse 方法。
    提供文件验证、编码检测等通用能力。
    """

    supported_file_type: str = ""

    @abc.abstractmethod
    def parse(self, file_path: str, artifact_id: str) -> list[RawMessage]:
        """解析文件，返回原始消息列表。

        Args:
            file_path: 原始文件路径
            artifact_id: source_artifact 的 UUID

        Returns:
            RawMessage 列表，按时间排序
        """
        ...

    def validate_file(self, file_path: str) -> bool:
        """验证文件是否存在且可读。

        Args:
            file_path: 文件路径

        Returns:
            文件是否可读
        """
        import os

        return os.path.isfile(file_path) and os.access(file_path, os.R_OK)