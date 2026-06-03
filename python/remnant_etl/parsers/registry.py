"""Source adapter registry for Remnant imports."""

from __future__ import annotations

from dataclasses import dataclass

from remnant_etl.parsers.base import BaseParser
from remnant_etl.parsers.universal_chat_json import UniversalChatJsonParser
from remnant_etl.parsers.wechat_txt import WechatTxtParser


@dataclass(frozen=True)
class AdapterMetadata:
    """Reader-facing metadata for an import adapter."""

    file_type: str
    platform: str
    format: str
    capabilities: tuple[str, ...]


_ADAPTERS: dict[str, tuple[type[BaseParser], AdapterMetadata]] = {
    "universal_chat_json": (
        UniversalChatJsonParser,
        AdapterMetadata(
            file_type="universal_chat_json",
            platform="generic",
            format="json",
            capabilities=(
                "timestamps",
                "participants",
                "text_messages",
                "attachments",
                "replies",
                "reactions",
                "system_messages",
            ),
        ),
    ),
    "wechat_txt": (
        WechatTxtParser,
        AdapterMetadata(
            file_type="wechat_txt",
            platform="wechat",
            format="txt",
            capabilities=(
                "timestamps",
                "text_messages",
                "system_messages",
                "recalls",
                "media_placeholders",
            ),
        ),
    ),
}


def list_supported_file_types() -> list[str]:
    """Return stable import file types supported by the current build."""
    return sorted(_ADAPTERS)


def list_adapter_metadata() -> list[AdapterMetadata]:
    """Return metadata for every registered adapter."""
    return [metadata for _, metadata in sorted(_ADAPTERS.values(), key=lambda item: item[1].file_type)]


def get_parser(file_type: str) -> BaseParser:
    """Create a parser for a supported file type."""
    adapter = _ADAPTERS.get(file_type)
    if adapter is None:
        raise ValueError(
            f"不支持的文件类型: {file_type}。"
            f"支持的类型: {list_supported_file_types()}"
        )
    parser_cls, _metadata = adapter
    return parser_cls()
