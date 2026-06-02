"""清洗过滤器 — 消息清洗管道核心模块。

实现 7 个过滤器和 1 个规范化器:
- SystemMessageFilter: 过滤系统消息
- RecallMessageFilter: 过滤撤回消息
- FinancialEventFilter: 标记金融事件
- EmojiPlaceholderFilter: 标记纯表情/贴图消息
- DuplicateMessageFilter: 去重
- ShortFragmentFilter: 标记极短片段
- NoTimestampFilter: 标记无时间戳消息
- SpeakerAliasNormalizer: 说话人别名统一

v0.1 核心原则: filter_noise 不删除消息，只标记 FILTERED。
"""

from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from remnant_etl.parsers.base import RawMessage


class MessageStatus(str, Enum):
    """消息清洗状态枚举。"""
    NORMALIZED = "NORMALIZED"
    CLEANED = "CLEANED"
    FILTERED = "FILTERED"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class NormalizedMessage:
    """规范化消息 — 清洗管道的中间数据结构。

    将 RawMessage 转换为标准化格式，同时保留原始字段
    用于溯源和审计。清洗管道不删除消息，只修改 status 和 filter_tags。

    Attributes:
        id: 消息唯一 ID（继承自 RawMessage 或新生成）
        raw_message_id: 对应的 raw_message ID
        source_artifact_id: 所属数据来源文件 ID
        timestamp: 标准化后的 ISO 8601 UTC 时间戳
        timestamp_confidence: 时间戳置信度 (CERTAIN / INFERRED / MISSING)
        speaker_original: 说话人原始名称
        speaker_normalized: 规范化后的说话人名称
        person_id: 关联的人物 ID（v0.1 暂不使用）
        content: 清洗后的消息内容
        content_type: 内容类型标记
        status: 消息状态（NORMALIZED / CLEANED / FILTERED / UNCERTAIN）
        filter_tags: 过滤标签列表（如 ["system_message", "recall"]）
        metadata: 扩展元数据
    """

    id: str
    raw_message_id: str
    source_artifact_id: str
    timestamp: str | None
    timestamp_confidence: str = "CERTAIN"
    speaker_original: str = ""
    speaker_normalized: str = ""
    person_id: str | None = None
    content: str = ""
    content_type: str = "text"
    status: MessageStatus = MessageStatus.NORMALIZED
    filter_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，方便写入数据库。"""
        import json

        return {
            "id": self.id,
            "raw_message_id": self.raw_message_id,
            "source_artifact_id": self.source_artifact_id,
            "timestamp": self.timestamp,
            "timestamp_confidence": self.timestamp_confidence,
            "speaker_original": self.speaker_original,
            "speaker_normalized": self.speaker_normalized,
            "person_id": self.person_id,
            "content": self.content,
            "content_type": self.content_type,
            "status": self.status.value if isinstance(self.status, MessageStatus) else self.status,
            "filter_tags": json.dumps(self.filter_tags, ensure_ascii=False) if self.filter_tags else "[]",
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
        }


@dataclass
class FilterContext:
    """过滤上下文 — 在清洗管道中传递状态。

    Attributes:
        seen_hashes: 已见过的消息内容哈希（用于去重）
        speaker_aliases: 说话人别名映射 {原始名: 规范名}
        message_count: 已处理的消息数
        filter_stats: 各过滤器的统计信息
    """

    seen_hashes: set[str] = field(default_factory=set)
    speaker_aliases: dict[str, str] = field(default_factory=dict)
    message_count: int = 0
    filter_stats: dict[str, int] = field(default_factory=dict)


class BaseFilter(abc.ABC):
    """过滤器抽象基类。

    所有过滤器必须实现 should_filter 和 should_tag 方法。
    transform 方法可选，用于修改消息内容。
    """

    filter_tag: str = ""

    @abc.abstractmethod
    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        """判断消息是否应被标记为 FILTERED。

        Args:
            msg: 待检查的规范化消息
            ctx: 过滤上下文

        Returns:
            True 表示应标记为 FILTERED
        """
        ...

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        """判断消息是否应被打上过滤器标签（但不 FILTERED）。

        Args:
            msg: 待检查的规范化消息
            ctx: 过滤上下文

        Returns:
            True 表示应打上标签
        """
        return False

    def transform(
        self, msg: NormalizedMessage, ctx: FilterContext
    ) -> NormalizedMessage:
        """转换消息内容（可选）。

        Args:
            msg: 待转换的规范化消息
            ctx: 过滤上下文

        Returns:
            转换后的消息
        """
        return msg


class SystemMessageFilter(BaseFilter):
    """系统消息过滤器 — 标记系统消息为 FILTERED。

    系统消息包括: 入群通知、退群通知、添加好友等。
    说话人为 "__system__" 或消息类型为 "system" 的消息会被过滤。
    """

    filter_tag = "system_message"

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        return msg.speaker_original == "__system__" or msg.content_type == "system"

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        # 非系统消息不需要打标签
        return False


class RecallMessageFilter(BaseFilter):
    """撤回消息过滤器 — 标记撤回消息为 FILTERED。

    撤回消息没有实际内容价值，但需要保留用于完整性审计。
    """

    filter_tag = "recall_message"

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        return msg.content_type == "recall" or msg.content == "撤回了一条消息"

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        return True


class FinancialEventFilter(BaseFilter):
    """金融事件过滤器 — 标记包含金融信息的消息。

    检测红包、转账等金融事件，打标签但不 FILTERED（v0.1 策略），
    后续版本在 scope 级别决定是否隐藏。
    """

    filter_tag = "financial_event"

    _FINANCIAL_KEYWORDS = [
        "红包", "转账", "收款", "付款", "微信支付",
        "支付宝", "银行", "余额",
    ]

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        # v0.1: 金融事件不 FILTERED，只打标签
        return False

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        content = msg.content
        return any(kw in content for kw in self._FINANCIAL_KEYWORDS) or msg.content_type == "red_packet"


class EmojiPlaceholderFilter(BaseFilter):
    """表情占位符过滤器 — 标记纯表情/贴图消息。

    纯表情消息无文本内容，对语义检索无贡献，但保留用于完整性。
    """

    filter_tag = "emoji_placeholder"

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        # 纯表情/贴图消息标记为 FILTERED
        return msg.content_type in ("sticker",) and not msg.content.strip()

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        return msg.content_type in ("sticker",)


class DuplicateMessageFilter(BaseFilter):
    """重复消息过滤器 — 标记精确重复的消息。

    使用消息内容 + 说话人的哈希值检测重复。
    仅保留原始消息，重复的标记为 FILTERED。
    """

    filter_tag = "duplicate"

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        # 计算去重哈希: 说话人 + 内容
        content_hash = self._compute_hash(msg)
        if content_hash in ctx.seen_hashes:
            return True
        ctx.seen_hashes.add(content_hash)
        return False

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        return False

    @staticmethod
    def _compute_hash(msg: NormalizedMessage) -> str:
        """计算消息去重哈希。"""
        raw = f"{msg.speaker_normalized}:{msg.content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ShortFragmentFilter(BaseFilter):
    """极短片段过滤器 — 标记过短的消息。

    纯文本消息少于 min_length 个字符时打标签。
    包含有效内容类型（图片、语音等）的消息不受此限制。
    v0.1 策略: 只打标签，不 FILTERED。
    """

    filter_tag = "short_fragment"
    min_length: int = 2

    def __init__(self, min_length: int = 2) -> None:
        self.min_length = min_length

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        # v0.1: 极短片段不过滤，只打标签
        return False

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        if msg.content_type != "text":
            return False
        return len(msg.content.strip()) < self.min_length


class NoTimestampFilter(BaseFilter):
    """无时间戳消息过滤器 — 标记缺少时间戳的消息。

    无时间戳的消息时间置信度为 MISSING，打标签但不 FILTERED。
    这些消息的分块位置由 _infer_timestamps 推断。
    """

    filter_tag = "no_timestamp"

    def should_filter(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        # v0.1: 无时间戳消息不过滤，只打标签
        return False

    def should_tag(self, msg: NormalizedMessage, ctx: FilterContext) -> bool:
        return msg.timestamp is None or msg.timestamp_confidence == "MISSING"


class SpeakerAliasNormalizer:
    """说话人别名规范化器 — 统一同一说话人的不同称呼。

    例如: "妈" / "妈妈" / "老妈" → "妈妈"
    通过 alias_map 参数配置映射关系。
    用户可通过 pipeline 的 speaker_aliases 参数传入。

    Attributes:
        alias_map: 别名映射 {原始名: 规范名}
    """

    def __init__(self, alias_map: dict[str, str] | None = None) -> None:
        self.alias_map: dict[str, str] = alias_map or {}

    def normalize(self, speaker: str) -> str:
        """规范化说话人名称。

        Args:
            speaker: 原始说话人名称

        Returns:
            规范化后的名称（如果有映射则使用映射值，否则原样返回）
        """
        return self.alias_map.get(speaker, speaker)

    def apply(self, messages: list[NormalizedMessage]) -> list[NormalizedMessage]:
        """批量应用说话人规范化。

        Args:
            messages: 规范化消息列表

        Returns:
            更新了 speaker_normalized 的消息列表
        """
        for msg in messages:
            msg.speaker_normalized = self.normalize(msg.speaker_original)
        return messages


def filter_noise(
    messages: list[NormalizedMessage],
    filters: list[BaseFilter] | None = None,
    alias_map: dict[str, str] | None = None,
) -> list[NormalizedMessage]:
    """清洗管道入口 — 对消息列表执行全部过滤和规范化。

    处理顺序:
    1. 说话人别名规范化
    2. 依次执行所有过滤器
    3. 统计过滤结果

    核心原则: 不删除消息，只标记 FILTERED 或添加 filter_tags。

    Args:
        messages: 规范化消息列表
        filters: 自定义过滤器列表（None 则使用默认 7 个）
        alias_map: 说话人别名映射

    Returns:
        处理后的消息列表（数量不变，状态和标签可能变化）
    """
    if filters is None:
        filters = [
            SystemMessageFilter(),
            RecallMessageFilter(),
            FinancialEventFilter(),
            EmojiPlaceholderFilter(),
            DuplicateMessageFilter(),
            ShortFragmentFilter(),
            NoTimestampFilter(),
        ]

    # 1. 说话人别名规范化
    normalizer = SpeakerAliasNormalizer(alias_map)
    messages = normalizer.apply(messages)

    # 2. 初始化过滤上下文
    ctx = FilterContext()

    # 3. 依次执行过滤器
    for f in filters:
        tag_count = 0
        for i, msg in enumerate(messages):
            # 先检查是否需要标记
            if f.should_tag(msg, ctx):
                if f.filter_tag not in msg.filter_tags:
                    msg.filter_tags.append(f.filter_tag)
                tag_count += 1

            # 再检查是否需要 FILTERED
            if f.should_filter(msg, ctx):
                msg.status = MessageStatus.FILTERED
                if f.filter_tag not in msg.filter_tags:
                    msg.filter_tags.append(f.filter_tag)
                tag_count += 1

            # 执行转换
            messages[i] = f.transform(msg, ctx)

        ctx.filter_stats[f.filter_tag] = tag_count
        ctx.message_count = len(messages)

    return messages


__all__ = [
    "MessageStatus",
    "NormalizedMessage",
    "FilterContext",
    "BaseFilter",
    "SystemMessageFilter",
    "RecallMessageFilter",
    "FinancialEventFilter",
    "EmojiPlaceholderFilter",
    "DuplicateMessageFilter",
    "ShortFragmentFilter",
    "NoTimestampFilter",
    "SpeakerAliasNormalizer",
    "filter_noise",
]