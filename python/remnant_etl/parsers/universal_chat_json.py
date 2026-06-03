"""Universal chat JSON parser.

This adapter accepts Remnant's canonical chat export shape and converts it into
RawMessage rows for the existing ETL pipeline.
"""

from __future__ import annotations

import json
from typing import Any

from remnant_etl.parsers.base import BaseParser, RawMessage, generate_uuid


class UniversalChatJsonParser(BaseParser):
    """Parse adapter-neutral chat JSON into RawMessage records."""

    supported_file_type: str = "universal_chat_json"

    def parse(self, file_path: str, artifact_id: str) -> list[RawMessage]:
        if not self.validate_file(file_path):
            raise FileNotFoundError(f"File does not exist or is not readable: {file_path}")

        with open(file_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, dict):
            raise ValueError("universal_chat_json root must be an object")

        version = payload.get("version")
        if version != 1:
            raise ValueError(f"Unsupported universal_chat_json schema version: {version}")

        source = _expect_object(payload, "source")
        conversation = _expect_object(payload, "conversation")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")

        parsed = [
            self._message_to_raw_message(
                message=message,
                index=index,
                artifact_id=artifact_id,
                source=source,
                conversation=conversation,
            )
            for index, message in enumerate(messages)
        ]
        parsed.sort(key=lambda message: message.timestamp or "")
        return parsed

    def _message_to_raw_message(
        self,
        message: Any,
        index: int,
        artifact_id: str,
        source: dict[str, Any],
        conversation: dict[str, Any],
    ) -> RawMessage:
        if not isinstance(message, dict):
            raise ValueError(f"messages[{index}] must be an object")

        message_id = _require_string(message, "id", index)
        sender_name = _require_string(message, "sender_name", index)
        content = _require_string(message, "content", index)
        content_type = _optional_string(message, "content_type") or "text"
        attachments = _optional_list(message, "attachments")
        metadata = _optional_object(message, "metadata")

        raw_metadata: dict[str, Any] = {
            "canonical_message_id": message_id,
            "sender_id": message.get("sender_id"),
            "source": source,
            "conversation": {
                "id": conversation.get("id"),
                "title": conversation.get("title"),
                "participants": conversation.get("participants", []),
            },
            "attachments": attachments,
            "platform_metadata": metadata,
        }

        if "reply_to" in message:
            raw_metadata["reply_to"] = message["reply_to"]
        if "reactions" in message:
            raw_metadata["reactions"] = _optional_list(message, "reactions")

        return RawMessage(
            id=generate_uuid(),
            source_artifact_id=artifact_id,
            timestamp=_optional_string(message, "timestamp"),
            speaker=sender_name,
            content=content,
            content_type=content_type,
            metadata=raw_metadata,
            parse_status="OK",
        )


def _expect_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _require_string(message: dict[str, Any], key: str, index: int) -> str:
    value = message.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"messages[{index}].{key} is required")
    return value


def _optional_string(message: dict[str, Any], key: str) -> str | None:
    value = message.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_object(message: dict[str, Any], key: str) -> dict[str, Any]:
    value = message.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _optional_list(message: dict[str, Any], key: str) -> list[Any]:
    value = message.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value
