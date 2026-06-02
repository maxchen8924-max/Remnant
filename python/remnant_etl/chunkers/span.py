"""溯源映射和哈希 — 为 chunk 中每条消息建立字符级溯源。

核心功能:
1. attach_source_spans() — 为 chunk 中每条消息建立字符级溯源映射
2. generate_chunk_hash() — SHA-256 内容哈希，用于去重和完整性校验

溯源映射（ChunkSpan）记录了 chunk.content 中每条消息的
字符偏移范围，使得从搜索结果可以精确追溯到原始 normalized_message。

拼接格式: [说话人] 消息内容\\n
与 conversation.py 中 _build_chunk_dict 保持一致。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from remnant_etl.cleaners.filters import NormalizedMessage
from remnant_etl.parsers.base import generate_uuid


@dataclass
class ChunkSpan:
    """分块溯源映射 — 记录 chunk.content 中的字符级偏移。

    对应 memory_chunk_span 表的每一行，使得从 chunk 的搜索结果
    可以精确追溯到具体的 normalized_message。

    Attributes:
        id: 溯源映射唯一 ID
        chunk_id: 所属 chunk ID
        normalized_message_id: 溯源的规范化消息 ID
        char_start: 在 chunk.content 中的起始字符偏移（含）
        char_end: 在 chunk.content 中的结束字符偏移（不含）
        source_speaker: 这段内容的说话人
        source_timestamp: 这段内容的时间戳
    """

    id: str
    chunk_id: str
    normalized_message_id: str
    char_start: int
    char_end: int
    source_speaker: str
    source_timestamp: str | None


def attach_source_spans(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为 chunk 列表中的每条消息建立字符级溯源映射。

    遍历每个 chunk 的 messages 列表，根据拼接格式
    [说话人] 消息内容\\n 计算每条消息在 content 中的字符偏移。

    Args:
        chunks: chunk 字典列表，每个包含 content 和 messages

    Returns:
        更新后的 chunk 列表，每个 chunk 新增 "spans" 字段
    """
    for chunk in chunks:
        messages: list[NormalizedMessage] = chunk.get("messages", [])
        spans: list[ChunkSpan] = []
        current_pos = 0

        for msg in messages:
            # 构造这条消息在 chunk 中的文本表示
            # 格式与 _build_chunk_dict 保持一致
            line = f"[{msg.speaker_normalized}] {msg.content}\n"

            char_start = current_pos
            char_end = current_pos + len(line)
            # 最后一个消息的末尾换行符可能不存在
            # 如果是最后一条，不包含末尾换行
            if msg is messages[-1]:
                # 最后一条消息不用换行，content 末尾无 \n
                content_without_trailing_newline = chunk["content"]
                if content_without_trailing_newline.endswith("\n"):
                    char_end = char_start + len(f"[{msg.speaker_normalized}] {msg.content}"),
                else:
                    char_end = char_start + len(f"[{msg.speaker_normalized}] {msg.content}")

            span = ChunkSpan(
                id=generate_uuid(),
                chunk_id=chunk["id"],
                normalized_message_id=msg.id,
                char_start=char_start,
                char_end=char_end,
                source_speaker=msg.speaker_normalized,
                source_timestamp=msg.timestamp,
            )
            spans.append(span)
            current_pos = char_end

            # 如果不是最后一条消息，加上换行符的长度
            if msg is not messages[-1]:
                current_pos = char_end
            else:
                # 最后一条消息，偏移到末尾
                pass

        chunk["spans"] = spans

    return chunks


def generate_chunk_hash(content: str) -> str:
    """为 chunk 内容生成 SHA-256 哈希。

    用于去重和完整性校验。相同内容的 chunk 会有相同哈希，
    可用于检测重复导入。

    Args:
        content: chunk 的文本内容

    Returns:
        SHA-256 哈希的十六进制字符串
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def attach_source_spans_v2(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为 chunk 列表中的每条消息建立字符级溯源映射（v2精确版）。

    通过重新拼接 chunk 的 content 来精确计算每条消息的字符偏移，
    确保溯源映射与实际 content 完全对齐。

    Args:
        chunks: chunk 字典列表，每个包含 content 和 messages

    Returns:
        更新后的 chunk 列表，每个 chunk 新增 "spans" 字段
    """
    for chunk in chunks:
        messages: list[NormalizedMessage] = chunk.get("messages", [])
        spans: list[ChunkSpan] = []

        # 重新拼接 content 以精确计算偏移
        lines: list[str] = []
        for msg in messages:
            line = f"[{msg.speaker_normalized}] {msg.content}"
            lines.append(line)

        content = "\n".join(lines)
        # 更新 chunk 的 content 以确保一致性
        chunk["content"] = content

        current_pos = 0
        for idx, msg in enumerate(messages):
            line = f"[{msg.speaker_normalized}] {msg.content}"
            char_start = current_pos
            char_end = current_pos + len(line)

            span = ChunkSpan(
                id=generate_uuid(),
                chunk_id=chunk["id"],
                normalized_message_id=msg.id,
                char_start=char_start,
                char_end=char_end,
                source_speaker=msg.speaker_normalized,
                source_timestamp=msg.timestamp,
            )
            spans.append(span)

            # 更新偏移：+1 for \n (between lines)
            current_pos = char_end + 1  # \n 占1个字符

        chunk["spans"] = spans

    return chunks


__all__ = [
    "ChunkSpan",
    "attach_source_spans",
    "attach_source_spans_v2",
    "generate_chunk_hash",
]