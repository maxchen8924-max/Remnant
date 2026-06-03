"""ETL Pipeline 入口 — Remnant v0.1 完整管道实现。

串联解析 → 规范化 → 清洗 → 分块 → 溯源 → 哈希 → 写入数据库。

使用示例::

    pipeline = ETLPipeline(db_path="remnant.db")
    result = pipeline.run(
        file_path="/path/to/wechat.txt",
        file_type="wechat_txt",
        deceased_profile_id="profile-uuid",
        speaker_aliases={"妈": "妈妈", "老爸": "爸爸"},
    )

所有写入使用 SQLite 事务，错误时更新 source_artifact 状态为 FAILED。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remnant_store.db import get_connection
from remnant_store.schema import init_db

from remnant_etl.parsers.base import BaseParser, RawMessage, generate_uuid
from remnant_etl.parsers.registry import get_parser
from remnant_etl.cleaners.filters import (
    MessageStatus,
    NormalizedMessage,
    filter_noise,
)
from remnant_etl.cleaners.normalizer import normalize_messages
from remnant_etl.chunkers.conversation import (
    ChunkConfig,
    ConversationSegment,
    semantic_chunk,
    build_conversation_segments,
    _estimate_tokens,
)
from remnant_etl.chunkers.span import (
    ChunkSpan,
    attach_source_spans_v2,
    generate_chunk_hash,
)

logger = logging.getLogger(__name__)


class ETLPipeline:
    """ETL 管道 — 串联解析、规范化、清洗、分块、溯源、哈希、写入。

    Attributes:
        db_path: 数据库文件路径
        sqlcipher_key: SQLCipher 加密密钥（可选）
        conn: 数据库连接
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        sqlcipher_key: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """初始化 ETL 管道。

        Args:
            db_path: 数据库文件路径，默认内存数据库
            sqlcipher_key: SQLCipher 加密密钥
            conn: 外部传入的数据库连接（优先于 db_path）
        """
        self.db_path = str(db_path)
        self.sqlcipher_key = sqlcipher_key
        self._external_conn = conn

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接并确保表结构存在。

        如果初始化时传入了外部连接，直接返回。
        否则创建新连接。
        """
        if self._external_conn is not None:
            return self._external_conn
        conn = init_db(self.db_path, sqlcipher_key=self.sqlcipher_key)
        return conn

    def run(
        self,
        file_path: str,
        file_type: str,
        deceased_profile_id: str,
        scope_id: str | None = None,
        speaker_aliases: dict[str, str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行完整 ETL 管道。

        Args:
            file_path: 原始文件路径
            file_type: 文件类型（如 "wechat_txt"）
            deceased_profile_id: 逝者档案 ID
            scope_id: 关系作用域 ID（可选）
            speaker_aliases: 说话人别名映射
            config: 管道配置参数

        Returns:
            包含统计信息的字典:
            - artifact_id: source_artifact ID
            - raw_count: 原始消息数量
            - normalized_count: 规范化消息数量
            - filtered_count: 过滤消息数量
            - chunk_count: 分块数量
            - errors: 错误信息列表
        """
        errors: list[str] = []
        conn = self._get_conn()

        # 创建 source_artifact 记录
        artifact_id = generate_uuid()
        file_hash = _compute_file_hash(file_path)
        file_size = os.path.getsize(file_path)

        try:
            self._write_source_artifact(
                conn,
                artifact_id=artifact_id,
                deceased_profile_id=deceased_profile_id,
                file_path=file_path,
                file_hash=file_hash,
                file_size=file_size,
                file_type=file_type,
                parse_status="PARSING",
            )

            # 1. 解析
            parser = self._get_parser(file_type)
            raw_messages = parser.parse(file_path, artifact_id)

            # 2. 规范化
            normalized = normalize_messages(raw_messages, speaker_aliases=speaker_aliases)

            # 3. 清洗
            cleaned = filter_noise(normalized, alias_map=speaker_aliases)

            # 4. 分块
            chunk_config = ChunkConfig()
            if config:
                chunk_config = ChunkConfig(
                    max_tokens=config.get("max_tokens", 512),
                    min_tokens=config.get("min_tokens", 50),
                    time_gap_threshold=config.get("time_gap_threshold", 1800),
                    overlap_messages=config.get("overlap_messages", 2),
                    max_messages_per_chunk=config.get("max_messages_per_chunk", 100),
                )

            chunks = semantic_chunk(
                cleaned,
                config=chunk_config,
                source_artifact_id=artifact_id,
            )

            # 5. 溯源映射
            chunks = attach_source_spans_v2(chunks)

            # 6. 哈希
            for chunk in chunks:
                chunk["chunk_hash"] = generate_chunk_hash(chunk["content"])

            # 7. 写入数据库（事务）
            filtered_count = sum(
                1 for m in cleaned if m.status == MessageStatus.FILTERED
            )

            self._write_raw_messages(conn, raw_messages)
            self._write_normalized_messages(conn, cleaned)
            self._write_chunks(conn, chunks, scope_id=scope_id)

            # 更新 source_artifact 状态为 PARSED
            # 计算日期范围
            timestamps = [m.timestamp for m in cleaned if m.timestamp]
            date_start = min(timestamps) if timestamps else None
            date_end = max(timestamps) if timestamps else None

            self._update_artifact_status(
                conn,
                artifact_id=artifact_id,
                status="PARSED",
                message_count=len(raw_messages),
                date_range_start=date_start,
                date_range_end=date_end,
            )

            # 审计日志
            self._write_audit_log(
                conn,
                action="ETL_RUN",
                actor="system",
                target_type="source_artifact",
                target_id=artifact_id,
                detail={
                    "file_type": file_type,
                    "raw_count": len(raw_messages),
                    "normalized_count": len(cleaned) - filtered_count,
                    "filtered_count": filtered_count,
                    "chunk_count": len(chunks),
                },
                scope_id=scope_id,
            )

            conn.commit()

            return {
                "artifact_id": artifact_id,
                "raw_count": len(raw_messages),
                "normalized_count": len(cleaned) - filtered_count,
                "filtered_count": filtered_count,
                "chunk_count": len(chunks),
                "errors": errors,
            }

        except Exception as e:
            logger.exception(f"ETL pipeline failed for {file_path}")
            errors.append(str(e))

            # 回滚并更新状态为 FAILED
            try:
                conn.rollback()
            except Exception:
                pass

            try:
                self._update_artifact_status(
                    conn,
                    artifact_id=artifact_id,
                    status="FAILED",
                    parse_error=str(e),
                )
                conn.commit()
            except Exception:
                pass

            return {
                "artifact_id": artifact_id,
                "raw_count": 0,
                "normalized_count": 0,
                "filtered_count": 0,
                "chunk_count": 0,
                "errors": errors,
            }

    def _get_parser(self, file_type: str) -> BaseParser:
        """根据文件类型获取解析器。

        Args:
            file_type: 文件类型标识

        Returns:
            对应的解析器实例

        Raises:
            ValueError: 不支持的文件类型
        """
        return get_parser(file_type)

    def _write_source_artifact(
        self,
        conn: sqlite3.Connection,
        artifact_id: str,
        deceased_profile_id: str,
        file_path: str,
        file_hash: str,
        file_size: int,
        file_type: str,
        parse_status: str = "PENDING",
    ) -> None:
        """写入 source_artifact 记录。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT INTO source_artifact
            (id, deceased_profile_id, file_path, file_hash, file_size, file_type,
             parse_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                deceased_profile_id,
                file_path,
                file_hash,
                file_size,
                file_type,
                parse_status,
                now,
                now,
            ),
        )

    def _write_raw_messages(
        self,
        conn: sqlite3.Connection,
        messages: list[RawMessage],
    ) -> None:
        """批量写入 raw_message 记录。"""
        rows = []
        for msg in messages:
            d = msg.to_dict()
            rows.append((
                d["id"],
                d["source_artifact_id"],
                d["timestamp"],
                d["speaker"],
                d["content"],
                d["content_type"],
                d["parse_status"],
                d["metadata"],
            ))

        conn.executemany(
            """INSERT INTO raw_message
            (id, source_artifact_id, timestamp, speaker, content, content_type,
             parse_status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def _write_normalized_messages(
        self,
        conn: sqlite3.Connection,
        messages: list[NormalizedMessage],
    ) -> None:
        """批量写入 normalized_message 记录。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = []
        for msg in messages:
            d = msg.to_dict()
            rows.append((
                d["id"],
                d["raw_message_id"],
                d["source_artifact_id"],
                d["timestamp"],
                d["timestamp_confidence"],
                d["speaker_original"],
                d["speaker_normalized"],
                d.get("person_id"),
                d["content"],
                d["content_type"],
                d["status"],
                d["filter_tags"],
                d["metadata"],
                now,
                now,
            ))

        conn.executemany(
            """INSERT INTO normalized_message
            (id, raw_message_id, source_artifact_id, timestamp, timestamp_confidence,
             speaker_original, speaker_normalized, person_id, content, content_type,
             status, filter_tags, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def _write_chunks(
        self,
        conn: sqlite3.Connection,
        chunks: list[dict[str, Any]],
        scope_id: str | None = None,
    ) -> None:
        """批量写入 memory_chunk 和 memory_chunk_span 记录。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for chunk in chunks:
            # 写入 memory_chunk
            conn.execute(
                """INSERT INTO memory_chunk
                (id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type,
                 content, token_count, time_range_start, time_range_end,
                 message_count, speaker_count, overlap_previous, overlap_next,
                 status, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk["id"],
                    chunk["source_artifact_id"],
                    scope_id,
                    chunk["chunk_hash"],
                    chunk.get("chunk_type", "conversation_segment"),
                    chunk["content"],
                    chunk.get("token_count", 0),
                    chunk.get("time_range_start"),
                    chunk.get("time_range_end"),
                    chunk.get("message_count", 0),
                    chunk.get("speaker_count", 0),
                    chunk.get("overlap_previous", 0),
                    chunk.get("overlap_next", 0),
                    "ACTIVE",
                    json.dumps({}, ensure_ascii=False),
                    now,
                    now,
                ),
            )

            # 写入 memory_chunk_span
            spans: list[ChunkSpan] = chunk.get("spans", [])
            for span in spans:
                conn.execute(
                    """INSERT INTO memory_chunk_span
                    (id, chunk_id, normalized_message_id, char_start, char_end,
                     source_speaker, source_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        span.id,
                        chunk["id"],
                        span.normalized_message_id,
                        span.char_start,
                        span.char_end,
                        span.source_speaker,
                        span.source_timestamp,
                    ),
                )

    def _update_artifact_status(
        self,
        conn: sqlite3.Connection,
        artifact_id: str,
        status: str,
        message_count: int | None = None,
        date_range_start: str | None = None,
        date_range_end: str | None = None,
        parse_error: str | None = None,
    ) -> None:
        """更新 source_artifact 的解析状态。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        set_clauses = ["parse_status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]

        if message_count is not None:
            set_clauses.append("message_count = ?")
            params.append(message_count)

        if date_range_start is not None:
            set_clauses.append("date_range_start = ?")
            params.append(date_range_start)

        if date_range_end is not None:
            set_clauses.append("date_range_end = ?")
            params.append(date_range_end)

        if parse_error is not None:
            set_clauses.append("parse_error = ?")
            params.append(parse_error)

        params.append(artifact_id)

        conn.execute(
            f"UPDATE source_artifact SET {', '.join(set_clauses)} WHERE id = ?",
            params,
        )

    def _write_audit_log(
        self,
        conn: sqlite3.Connection,
        action: str,
        actor: str,
        target_type: str,
        target_id: str,
        detail: dict[str, Any] | None = None,
        scope_id: str | None = None,
    ) -> None:
        """写入审计日志。"""
        log_id = generate_uuid()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn.execute(
            """INSERT INTO audit_log
            (id, relationship_scope_id, action, actor, target_type, target_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_id,
                scope_id,
                action,
                actor,
                target_type,
                target_id,
                json.dumps(detail or {}, ensure_ascii=False),
                now,
            ),
        )


def _compute_file_hash(file_path: str) -> str:
    """计算文件的 SHA-256 哈希。

    Args:
        file_path: 文件路径

    Returns:
        十六进制哈希字符串
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            sha256.update(block)
    return sha256.hexdigest()


# 保持向后兼容 — 旧的 Protocol/ABC 定义保留为模块级接口
from remnant_etl.parsers.base import BaseParser as _BaseParser
from remnant_etl.parsers.wechat_txt import WechatTxtParser as _WechatTxtParser
from remnant_etl.cleaners.filters import BaseFilter as _BaseFilter


__all__ = ["ETLPipeline"]
