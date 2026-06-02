"""消息规范化模块 — 将 RawMessage 转换为 NormalizedMessage。

处理流程:
1. 时间戳标准化为 ISO 8601 UTC 格式
2. 说话人名称通过别名映射统一
3. 内容类型标记
4. 时间戳置信度评估
5. 生成规范化消息 ID
6. 保留原始字段用于溯源

v0.1 假设: 微信导出的时间戳均为北京时间 (UTC+8)，
不做时区转换，直接保留原始时间戳格式。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from remnant_etl.parsers.base import RawMessage, generate_uuid
from remnant_etl.cleaners.filters import NormalizedMessage, MessageStatus


# 北京时间 UTC+8
_BEIJING_TZ = timezone(timedelta(hours=8))


def normalize_messages(
    raw_messages: list[RawMessage],
    speaker_aliases: dict[str, str] | None = None,
) -> list[NormalizedMessage]:
    """将 RawMessage 列表转换为 NormalizedMessage 列表。

    主要处理:
    1. 生成规范化消息唯一 ID
    2. 时间戳标准化(ISO 8601 UTC 格式)
    3. 评估时间戳置信度
    4. 说话人名称处理（aliases 在 filter_noise 中执行）
    5. 内容类型保持或修正
    6. 初始化状态为 NORMALIZED

    Args:
        raw_messages: 原始消息列表
        speaker_aliases: 说话人别名映射（保留参数，实际规范化在 filter_noise 中执行）

    Returns:
        规范化消息列表
    """
    normalized: list[NormalizedMessage] = []
    aliases = speaker_aliases or {}

    for raw in raw_messages:
        # 时间戳标准化
        ts_normalized = _normalize_timestamp(raw.timestamp)
        ts_confidence = _assess_timestamp_confidence(raw)

        # 说话人名称：原始名称保留，规范化名称先设为原始名
        #（filter_noise 中 SpeakerAliasNormalizer 会进一步处理）
        speaker_original = raw.speaker
        speaker_normalized = aliases.get(raw.speaker, raw.speaker)

        # 创建 NormalizedMessage
        nm = NormalizedMessage(
            id=generate_uuid(),
            raw_message_id=raw.id,
            source_artifact_id=raw.source_artifact_id,
            timestamp=ts_normalized,
            timestamp_confidence=ts_confidence,
            speaker_original=speaker_original,
            speaker_normalized=speaker_normalized,
            person_id=None,
            content=raw.content,
            content_type=raw.content_type,
            status=MessageStatus.NORMALIZED,
            filter_tags=[],
            metadata=dict(raw.metadata),  # 复制元数据
        )

        # 如果原始消息有推断时间戳标记，在 metadata 中保留
        if raw.metadata.get("timestamp_inferred"):
            nm.metadata["timestamp_inferred"] = True

        normalized.append(nm)

    return normalized


def _normalize_timestamp(ts_str: str | None) -> str | None:
    """将时间戳标准化为 ISO 8601 格式。

    支持的输入格式:
    - "2024-01-15T10:30:22" (已经标准化的)
    - "2024-01-15 10:30:22" (微信常见格式)
    - None (无时间戳)

    Args:
        ts_str: 原始时间戳字符串

    Returns:
        ISO 8601 格式的时间戳字符串，或 None
    """
    if ts_str is None:
        return None

    # 已经是 ISO 8601 格式
    if "T" in ts_str:
        return ts_str

    # 常见格式: "2024-01-15 10:30:22"
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue

    # 无法解析的时间戳，原样返回
    return ts_str


def _assess_timestamp_confidence(raw: RawMessage) -> str:
    """评估时间戳的置信度。

    CERTAIN: 时间戳直接从文件解析得到
    INFERRED: 时间戳是通过推断得到的
    MISSING: 无时间戳

    Args:
        raw: 原始消息

    Returns:
        置信度标识: "CERTAIN" / "INFERRED" / "MISSING"
    """
    if raw.timestamp is None:
        return "MISSING"
    if raw.metadata.get("timestamp_inferred"):
        return "INFERRED"
    return "CERTAIN"


__all__ = ["normalize_messages"]