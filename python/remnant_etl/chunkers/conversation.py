"""对话分块算法 — 动态语义分块。

将连续时间排列的消息序列分割为具有上下文完整性的对话段（ConversationSegment），
再通过规则策略在段内切出满足 token 限制的 memory_chunk。

v0.1 使用基于时间间隔和长度的规则策略替代 embedding 语义分块，
embedding_fn 参数保留供后续版本升级。

核心算法:
1. build_conversation_segments() — 按时间间隔分对话段
2. semantic_chunk() — 在段内按 token 限制切分
3. _find_split_points() — 贪心策略寻找切分点
4. _merge_short_chunks() — 合并过短的 chunk
5. _add_overlaps() — 在相邻 chunk 添加重叠
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from remnant_etl.cleaners.filters import NormalizedMessage, MessageStatus
from remnant_etl.parsers.base import generate_uuid


@dataclass
class ChunkConfig:
    """分块配置 — 控制分块行为的参数集合。

    Attributes:
        max_tokens: 单个 chunk 的最大 token 数
        min_tokens: 单个 chunk 的最小 token 数（低于此值会合并）
        time_gap_threshold: 时间间隔阈值（秒），超过此值视为新对话段
        overlap_messages: 相邻 chunk 的重叠消息数
        max_messages_per_chunk: 单个 chunk 的最大消息数
    """

    max_tokens: int = 512
    min_tokens: int = 50
    time_gap_threshold: int = 1800  # 30分钟
    overlap_messages: int = 2
    max_messages_per_chunk: int = 100


# 默认配置
CHUNK_CONFIG = ChunkConfig()


@dataclass
class ConversationSegment:
    """对话段 — 一段连续时间范围内的消息集合。

    Attributes:
        id: 段唯一 ID
        messages: 段内消息列表（按时间排序）
        time_start: 段起始时间（ISO 8601）
        time_end: 段结束时间（ISO 8601）
        speaker_count: 段内不同说话人数量
        message_count: 段内消息数量
    """

    id: str
    messages: list[NormalizedMessage]
    time_start: str | None
    time_end: str | None
    speaker_count: int
    message_count: int


def build_conversation_segments(
    messages: list[NormalizedMessage],
    time_gap_threshold: int = 1800,
) -> list[ConversationSegment]:
    """按时间间隔将消息序列分割为对话段。

    当两条消息之间的时间间隔超过阈值（默认30分钟），
    认为属于不同对话段。

    Args:
        messages: 规范化消息列表（应按时间排序）
        time_gap_threshold: 时间间隔阈值（秒）

    Returns:
        对话段列表
    """
    if not messages:
        return []

    segments: list[ConversationSegment] = []
    current_msgs: list[NormalizedMessage] = [messages[0]]

    for i in range(1, len(messages)):
        prev_msg = messages[i - 1]
        curr_msg = messages[i]

        # 检查时间间隔
        gap = _time_gap_seconds(prev_msg.timestamp, curr_msg.timestamp)
        if gap is not None and gap > time_gap_threshold:
            # 时间间隔超过阈值，开始新段
            segment = _make_segment(current_msgs)
            segments.append(segment)
            current_msgs = [curr_msg]
        else:
            current_msgs.append(curr_msg)

    # 最后一段
    if current_msgs:
        segment = _make_segment(current_msgs)
        segments.append(segment)

    return segments


def _make_segment(messages: list[NormalizedMessage]) -> ConversationSegment:
    """从消息列表构造 ConversationSegment。"""
    timestamps = [m.timestamp for m in messages if m.timestamp is not None]
    speakers = set(m.speaker_normalized for m in messages)

    return ConversationSegment(
        id=generate_uuid(),
        messages=messages,
        time_start=min(timestamps) if timestamps else None,
        time_end=max(timestamps) if timestamps else None,
        speaker_count=len(speakers),
        message_count=len(messages),
    )


def _time_gap_seconds(ts1: str | None, ts2: str | None) -> float | None:
    """计算两个时间戳之间的间隔秒数。

    Args:
        ts1: 较早的时间戳（ISO 8601 格式）
        ts2: 较晚的时间戳（ISO 8601 格式）

    Returns:
        间隔秒数，无法计算时返回 None
    """
    if ts1 is None or ts2 is None:
        return None

    fmt = "%Y-%m-%dT%H:%M:%S"
    try:
        from datetime import datetime

        dt1 = datetime.strptime(ts1, fmt)
        dt2 = datetime.strptime(ts2, fmt)
        return abs((dt2 - dt1).total_seconds())
    except (ValueError, TypeError):
        return None


def semantic_chunk(
    messages: list[NormalizedMessage],
    config: ChunkConfig | None = None,
    source_artifact_id: str = "",
    embedding_fn: Callable[[str], list[float]] | None = None,
) -> list[dict[str, Any]]:
    """对规范化消息执行语义分块。

    v0.1 实现策略:
    1. 过滤掉 FILTERED 状态的消息（但不完全排除，保留索引）
    2. 按时间间隔分对话段
    3. 在段内按 token 限制切分
    4. 合并过短 chunk
    5. 添加重叠

    Args:
        messages: 规范化消息列表（按时间排序）
        config: 分块配置
        source_artifact_id: 数据来源 ID
        embedding_fn: 语义 embedding 函数（v0.1 未使用，保留接口）

    Returns:
        memory_chunk 字典列表，每个包含 id, content, token_count 等字段
    """
    if config is None:
        config = CHUNK_CONFIG

    if not messages:
        return []

    # 过滤掉 FILTERED 消息用于分块，但保留原始索引用于溯源
    active_messages = [m for m in messages if m.status != MessageStatus.FILTERED]

    if not active_messages:
        return []

    # 1. 按时间间隔分对话段
    segments = build_conversation_segments(
        active_messages, time_gap_threshold=config.time_gap_threshold
    )

    # 2. 在每个段内切分
    all_chunks: list[dict[str, Any]] = []

    for segment in segments:
        seg_chunks = _chunk_segment(segment, config, source_artifact_id)
        all_chunks.extend(seg_chunks)

    # 3. 合并过短 chunk
    all_chunks = _merge_short_chunks(all_chunks, config)

    # 4. 添加重叠
    all_chunks = _add_overlaps(all_chunks, config)

    return all_chunks


def _chunk_segment(
    segment: ConversationSegment,
    config: ChunkConfig,
    source_artifact_id: str,
) -> list[dict[str, Any]]:
    """在单个对话段内按 token 限制切分。

    Args:
        segment: 对话段
        config: 分块配置
        source_artifact_id: 数据来源 ID

    Returns:
        chunk 字典列表
    """
    msgs = segment.messages
    if not msgs:
        return []

    # 构造分块内容
    chunk_dicts: list[dict[str, Any]] = []
    current_msgs: list[NormalizedMessage] = []
    current_tokens = 0

    for msg in msgs:
        msg_tokens = _estimate_tokens(msg.content)
        msg_with_speaker = f"[{msg.speaker_normalized}] {msg.content}"
        msg_with_speaker_tokens = _estimate_tokens(msg_with_speaker)

        # 如果添加这条消息超过限制，且当前已有消息，则切分
        if (
            current_msgs
            and current_tokens + msg_with_speaker_tokens > config.max_tokens
        ):
            chunk_dicts.append(
                _build_chunk_dict(current_msgs, source_artifact_id, config)
            )
            current_msgs = [msg]
            current_tokens = msg_with_speaker_tokens
        else:
            current_msgs.append(msg)
            current_tokens += msg_with_speaker_tokens

        # 检查消息数量限制
        if len(current_msgs) >= config.max_messages_per_chunk:
            chunk_dicts.append(
                _build_chunk_dict(current_msgs, source_artifact_id, config)
            )
            current_msgs = []
            current_tokens = 0

    # 剩余消息
    if current_msgs:
        chunk_dicts.append(
            _build_chunk_dict(current_msgs, source_artifact_id, config)
        )

    return chunk_dicts


def _build_chunk_dict(
    messages: list[NormalizedMessage],
    source_artifact_id: str,
    config: ChunkConfig,
) -> dict[str, Any]:
    """从消息列表构造 chunk 字典。

    拼接格式: [说话人] 消息内容\\n
    """
    lines: list[str] = []
    for msg in messages:
        lines.append(f"[{msg.speaker_normalized}] {msg.content}")

    content = "\n".join(lines)
    token_count = _estimate_tokens(content)
    timestamps = [m.timestamp for m in messages if m.timestamp is not None]
    speakers = set(m.speaker_normalized for m in messages)

    from datetime import datetime

    time_start = min(timestamps) if timestamps else None
    time_end = max(timestamps) if timestamps else None

    return {
        "id": generate_uuid(),
        "source_artifact_id": source_artifact_id,
        "chunk_type": "conversation_segment",
        "content": content,
        "token_count": token_count,
        "time_range_start": time_start,
        "time_range_end": time_end,
        "message_count": len(messages),
        "speaker_count": len(speakers),
        "messages": messages,  # 保留原始消息用于溯源
        "overlap_previous": 0,
        "overlap_next": 0,
    }


def _merge_short_chunks(
    chunks: list[dict[str, Any]], config: ChunkConfig
) -> list[dict[str, Any]]:
    """合并过短的 chunk。

    如果相邻两个 chunk 的 token 数之和不超过 max_tokens，
    且消息数之和不超过 max_messages_per_chunk，则合并。

    Args:
        chunks: chunk 字典列表
        config: 分块配置

    Returns:
        合并后的 chunk 列表
    """
    if not chunks:
        return chunks

    merged: list[dict[str, Any]] = []
    current = chunks[0]

    for i in range(1, len(chunks)):
        next_chunk = chunks[i]

        # 检查是否可以合并
        combined_tokens = current["token_count"] + next_chunk["token_count"]
        combined_msgs = current["message_count"] + next_chunk["message_count"]

        # 只合并在 min_tokens 以下的短 chunk
        if (
            current["token_count"] < config.min_tokens
            and combined_tokens <= config.max_tokens
            and combined_msgs <= config.max_messages_per_chunk
        ):
            # 合并: 拼接内容、合并消息
            all_messages: list[NormalizedMessage] = []
            all_messages.extend(current.get("messages", []))
            all_messages.extend(next_chunk.get("messages", []))

            lines = [f"[{m.speaker_normalized}] {m.content}" for m in all_messages]
            content = "\n".join(lines)

            timestamps = [m.timestamp for m in all_messages if m.timestamp]
            speakers = set(m.speaker_normalized for m in all_messages)

            current = {
                "id": generate_uuid(),
                "source_artifact_id": current.get("source_artifact_id", ""),
                "chunk_type": "conversation_segment",
                "content": content,
                "token_count": _estimate_tokens(content),
                "time_range_start": min(timestamps) if timestamps else None,
                "time_range_end": max(timestamps) if timestamps else None,
                "message_count": len(all_messages),
                "speaker_count": len(speakers),
                "messages": all_messages,
                "overlap_previous": current.get("overlap_previous", 0),
                "overlap_next": 0,
            }
        else:
            merged.append(current)
            current = next_chunk

    merged.append(current)
    return merged


def _add_overlaps(
    chunks: list[dict[str, Any]], config: ChunkConfig
) -> list[dict[str, Any]]:
    """在相邻 chunk 之间添加重叠消息。

    从前一个 chunk 的末尾取 overlap_messages 条消息
    添加到下一个 chunk 的开头。

    Args:
        chunks: chunk 字典列表
        config: 分块配置

    Returns:
        添加了重叠的 chunk 列表
    """
    if len(chunks) <= 1 or config.overlap_messages <= 0:
        return chunks

    for i in range(1, len(chunks)):
        prev_msgs = chunks[i - 1].get("messages", [])
        if not prev_msgs:
            continue

        # 从前一个 chunk 末尾取重叠消息
        overlap_count = min(config.overlap_messages, len(prev_msgs))
        overlap_msgs = prev_msgs[-overlap_count:]

        # 标记重叠数
        chunks[i]["overlap_previous"] = overlap_count
        chunks[i - 1]["overlap_next"] = overlap_count

        # 将重叠消息追加到当前 chunk 内容前面
        current_msgs: list[NormalizedMessage] = list(chunks[i].get("messages", []))
        # 只添加不重复的重叠消息
        existing_ids = {m.id for m in current_msgs}
        for om in overlap_msgs:
            if om.id not in existing_ids:
                current_msgs.insert(0, om)

        # 重新构建内容
        if current_msgs != chunks[i].get("messages", []):
            lines = [f"[{m.speaker_normalized}] {m.content}" for m in current_msgs]
            chunks[i]["content"] = "\n".join(lines)
            chunks[i]["token_count"] = _estimate_tokens(chunks[i]["content"])
            chunks[i]["messages"] = current_msgs
            chunks[i]["message_count"] = len(current_msgs)

    return chunks


def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数量。

    简单估算策略:
    - 中文字符 ≈ 1.5 token/字
    - 英文单词 ≈ 0.75 token/word
    - 标点和空白 ≈ 0.5 token/字符

    这只是粗略估算，用于分块时控制大小。
    实际 embedding 时的 token 数可能不同。

    Args:
        text: 待估算的文本

    Returns:
        估算的 token 数量
    """
    if not text:
        return 0

    token_count = 0
    chinese_char_count = 0
    english_word_count = 0
    other_char_count = 0

    # 分词估算
    import re

    # 统计中文字符
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_char_count = len(chinese_chars)

    # 统计英文单词
    english_words = re.findall(r"[a-zA-Z]+", text)
    english_word_count = len(english_words)

    # 其他字符（标点、空白等）
    other_char_count = len(text) - chinese_char_count - sum(len(w) for w in english_words)

    token_count = int(
        chinese_char_count * 1.5
        + english_word_count * 0.75
        + other_char_count * 0.3
    )

    return max(token_count, 1)


__all__ = [
    "ChunkConfig",
    "CHUNK_CONFIG",
    "ConversationSegment",
    "build_conversation_segments",
    "semantic_chunk",
    "_estimate_tokens",
]