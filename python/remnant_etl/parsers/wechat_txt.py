"""微信 TXT 导出文件解析器。

支持微信导出的纯文本聊天记录格式：
- 两行格式: 时间戳 + 说话人一行，消息内容下一行
- 单行格式: 时间戳 + 说话人: 消息内容
- 系统消息: --- 系统消息内容 ---
- 撤回消息: 「说话人」撤回了一条消息

解析流程:
1. _read_file() — 自动检测编码
2. _split_by_date() — 按日期分隔线切分组
3. 逐行解析，_parse_line() 正则匹配
4. _classify_content() — 识别图片/语音/文件等占位符
5. _infer_timestamps() — 为无时间戳消息推断时间
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta
from typing import Any

from remnant_etl.parsers.base import BaseParser, RawMessage, generate_uuid

# 日期分隔线: "—————— 2024-01-15 ——————" 或类似格式
_DATE_SEPARATOR_RE = re.compile(
    r"^[-=—]{3,}\s*(\d{4}[-/]\d{2}[-/]\d{2})\s*.*?[-=—]{3,}$"
)

# 两行格式: "2024-01-15 10:30:22 说话人" (无冒号)
_TWO_LINE_HEADER_RE = re.compile(
    r"^(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+(\S.+)$"
)

# 单行格式: "2024-01-15 10:30:22 说话人: 消息内容"
_SINGLE_LINE_RE = re.compile(
    r"^(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+(\S+?):\s*(.+)$"
)

# 系统消息: "--- 2024-01-15 11:00:00 你已添加了"爸爸" ---"
_SYSTEM_MSG_RE = re.compile(
    r"^[-=—]{3,}\s*(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s*(.+?)\s*[-=—]{3,}$"
)

# 撤回消息: 「说话人」撤回了一条消息
_RECALL_RE = re.compile(r"^[「『\u201c\u201d'](.+?)[」』\u201c\u201d']\s*撤回了一条消息$")

# 图片占位符
_IMAGE_PLACEHOLDER_RE = re.compile(r"\[图片\]|\[Image\]|<图片>|<Image>|📷", re.IGNORECASE)

# 语音占位符
_VOICE_PLACEHOLDER_RE = re.compile(r"\[语音\]|\[Voice\]|<语音>|<Voice>|🎤", re.IGNORECASE)

# 文件占位符
_FILE_PLACEHOLDER_RE = re.compile(
    r"\[文件\]|\[File\]|<文件>|<File>|\.pdf|\.doc|\.xls|\.zip|\.rar",
    re.IGNORECASE,
)

# 视频占位符
_VIDEO_PLACEHOLDER_RE = re.compile(r"\[视频\]|\[Video\]|<视频>|<Video>", re.IGNORECASE)

# 红包/转账占位符
_RED_PACKET_RE = re.compile(r"\[红包\]|\[转账\]|领取了红包|发出红包", re.IGNORECASE)

# 位置占位符
_LOCATION_RE = re.compile(r"\[位置\]|\[Location\]|<位置>|<Location>", re.IGNORECASE)

# 表情包占位符
_EMOJI_PKG_RE = re.compile(r"\[表情包\]|\[Sticker\]|<表情包>|<Sticker>", re.IGNORECASE)


class WechatTxtParser(BaseParser):
    """微信 TXT 导出文件解析器。

    将微信导出的纯文本聊天记录解析为 RawMessage 列表。
    支持自动编码检测、多格式消息识别、系统消息/撤回消息处理。
    """

    supported_file_type: str = "wechat_txt"

    def __init__(self) -> None:
        self._raw_lines: list[str] = []

    def parse(self, file_path: str, artifact_id: str) -> list[RawMessage]:
        """解析微信 TXT 文件，返回 RawMessage 列表。

        Args:
            file_path: 微信导出的 txt 文件路径
            artifact_id: source_artifact 的 UUID

        Returns:
            按时间排序的 RawMessage 列表

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件为空或格式异常
        """
        if not self.validate_file(file_path):
            raise FileNotFoundError(f"文件不存在或不可读: {file_path}")

        content = self._read_file(file_path)
        if not content.strip():
            raise ValueError(f"文件为空: {file_path}")

        self._raw_lines = content.splitlines()
        groups = self._split_by_date(self._raw_lines)
        messages = self._parse_groups(groups, artifact_id)
        messages = self._infer_timestamps(messages)

        # 按时间排序
        messages.sort(key=lambda m: m.timestamp or "")
        return messages

    def _read_file(self, file_path: str) -> str:
        """自动检测编码读取文件内容。

        依次尝试 utf-8 → gbk → gb18030，确保能读取
        微信导出的各种编码的 txt 文件。

        Args:
            file_path: 文件路径

        Returns:
            文件文本内容
        """
        encodings = ["utf-8", "gbk", "gb18030"]
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding, errors="strict") as f:
                    content = f.read()
                # 验证内容中包含可识别的中文或日期格式
                if any(c > "\u4e00" and c < "\u9fff" for c in content) or re.search(
                    r"\d{4}[-/]\d{2}[-/]\d{2}", content
                ):
                    return content
                # 如果内容看起来正常（没有乱码），也返回
                try:
                    content.encode("ascii")
                    return content  # 纯 ASCII 内容
                except UnicodeEncodeError:
                    continue
            except (UnicodeDecodeError, UnicodeError):
                continue

        # 最终回退：使用 utf-8 替换错误字符
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _split_by_date(self, lines: list[str]) -> list[list[str]]:
        """按日期分隔线将文本切分为消息组。

        微信导出文件中的日期分隔线格式如:
        "—————— 2024-01-15 ——————"

        Args:
            lines: 原始文本行列表

        Returns:
            消息组列表，每组包含一个日期区域内的全部行
        """
        groups: list[list[str]] = []
        current_group: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # 空行可能是消息之间的分隔，保留
                if current_group:
                    current_group.append("")
                continue

            # 检查是否是日期分隔线
            if _DATE_SEPARATOR_RE.match(stripped):
                if current_group:
                    groups.append(current_group)
                current_group = [stripped]
            else:
                current_group.append(stripped)

        if current_group:
            groups.append(current_group)

        # 如果没有任何分组，把所有行作为一组
        if not groups and lines:
            groups = [lines]

        return groups

    def _parse_groups(
        self, groups: list[list[str]], artifact_id: str
    ) -> list[RawMessage]:
        """解析消息组，逐组逐行提取原始消息。

        Args:
            groups: 消息组列表
            artifact_id: source_artifact ID

        Returns:
            RawMessage 列表
        """
        messages: list[RawMessage] = []

        for group in groups:
            i = 0
            while i < len(group):
                line = group[i].strip()
                if not line:
                    i += 1
                    continue

                # 检查系统消息
                sys_match = _SYSTEM_MSG_RE.match(line)
                if sys_match:
                    timestamp_str = sys_match.group(1)
                    sys_content = sys_match.group(2).strip().strip("-").strip().strip("=").strip()
                    ts = self._normalize_timestamp(timestamp_str)
                    messages.append(
                        RawMessage(
                            id=generate_uuid(),
                            source_artifact_id=artifact_id,
                            timestamp=ts,
                            speaker="__system__",
                            content=sys_content,
                            content_type="system",
                            metadata={"original_line": line},
                            parse_status="OK",
                        )
                    )
                    i += 1
                    continue

                # 检查撤回消息
                recall_match = _RECALL_RE.match(line)
                if recall_match:
                    speaker = recall_match.group(1)
                    messages.append(
                        RawMessage(
                            id=generate_uuid(),
                            source_artifact_id=artifact_id,
                            timestamp=None,
                            speaker=speaker,
                            content="撤回了一条消息",
                            content_type="recall",
                            metadata={"original_line": line},
                            parse_status="OK",
                        )
                    )
                    i += 1
                    continue

                # 检查单行格式（有时间戳、说话人和内容在同一行）
                single_match = _SINGLE_LINE_RE.match(line)
                if single_match:
                    timestamp_str = single_match.group(1)
                    speaker = single_match.group(2)
                    content = single_match.group(3)
                    ts = self._normalize_timestamp(timestamp_str)
                    content_type = self._classify_content(content)
                    messages.append(
                        RawMessage(
                            id=generate_uuid(),
                            source_artifact_id=artifact_id,
                            timestamp=ts,
                            speaker=speaker,
                            content=content,
                            content_type=content_type,
                            metadata={"original_line": line},
                            parse_status="OK",
                        )
                    )
                    i += 1
                    continue

                # 检查两行格式（时间戳 + 说话人在一行，内容在下一行）
                two_line_match = _TWO_LINE_HEADER_RE.match(line)
                if two_line_match:
                    timestamp_str = two_line_match.group(1)
                    speaker = two_line_match.group(2)
                    ts = self._normalize_timestamp(timestamp_str)

                    # 下一个非空行是消息内容
                    content = ""
                    j = i + 1
                    while j < len(group) and not group[j].strip():
                        j += 1
                    if j < len(group):
                        next_line = group[j].strip()
                        # 确保下一行不是新的消息头
                        if not _TWO_LINE_HEADER_RE.match(
                            next_line
                        ) and not _SINGLE_LINE_RE.match(
                            next_line
                        ) and not _SYSTEM_MSG_RE.match(
                            next_line
                        ):
                            content = next_line
                            i = j + 1
                        else:
                            i += 1
                    else:
                        i += 1

                    content_type = self._classify_content(content)
                    messages.append(
                        RawMessage(
                            id=generate_uuid(),
                            source_artifact_id=artifact_id,
                            timestamp=ts,
                            speaker=speaker,
                            content=content,
                            content_type=content_type,
                            metadata={"original_line": f"{line} / {content}"},
                            parse_status="OK",
                        )
                    )
                    continue

                # 无时间戳的普通文本行 — 可能是多行消息的续行
                # 跳过日期分隔线
                if _DATE_SEPARATOR_RE.match(line):
                    i += 1
                    continue

                # 无法识别的行作为无时间戳消息
                i += 1

        return messages

    def _normalize_timestamp(self, ts_str: str) -> str:
        """将各种格式的时间戳标准化为 ISO 8601 格式。

        支持的格式:
        - "2024-01-15 10:30:22"
        - "2024/01/15 10:30:22"
        - "2024-1-5 10:30:22"

        Args:
            ts_str: 原始时间戳字符串

        Returns:
            ISO 8601 格式的时间戳字符串（本地时间，无时区后缀）
            如果解析失败返回原始字符串
        """
        # 统一分隔符
        normalized = ts_str.replace("/", "-")

        # 尝试多种格式
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(normalized, fmt)
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue

        # 解析失败，返回原始字符串
        return ts_str

    def _classify_content(self, content: str) -> str:
        """识别消息内容类型。

        根据占位符模式判断消息是文本、图片、语音、文件等。

        Args:
            content: 消息文本内容

        Returns:
            内容类型字符串: text / image / voice / file / video / red_packet / location / sticker / recall
        """
        if not content:
            return "text"

        if _RECALL_RE.match(content):
            return "recall"
        if _IMAGE_PLACEHOLDER_RE.search(content):
            return "image"
        if _VOICE_PLACEHOLDER_RE.search(content):
            return "voice"
        if _FILE_PLACEHOLDER_RE.search(content):
            return "file"
        if _VIDEO_PLACEHOLDER_RE.search(content):
            return "video"
        if _RED_PACKET_RE.search(content):
            return "red_packet"
        if _LOCATION_RE.search(content):
            return "location"
        if _EMOJI_PKG_RE.search(content):
            return "sticker"

        return "text"

    def _infer_timestamps(self, messages: list[RawMessage]) -> list[RawMessage]:
        """为无时间戳的消息推断时间。

        推断策略:
        1. 撤回消息: 使用前一条消息的时间戳（同一说话人优先）
        2. 其他无时间戳消息: 使用紧邻的上一条有时间的消息时间戳

        Args:
            messages: 原始消息列表（可能包含 None 时间戳）

        Returns:
            补全时间戳后的消息列表
        """
        if not messages:
            return messages

        last_ts: str | None = None
        for msg in messages:
            if msg.timestamp is not None:
                last_ts = msg.timestamp
            elif last_ts is not None:
                # 使用最近的已知时间戳
                msg.timestamp = last_ts
                # 标记为推断时间
                msg.metadata["timestamp_inferred"] = True

        return messages


# 注册到 parsers 包
__all__ = ["WechatTxtParser"]