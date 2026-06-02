"""Chunk DAO 骨架 — 记忆分块数据访问层。

负责 memory_chunk 及关联表的 CRUD 操作:
- 创建/查询/软删除分块
- 分块溯源映射（chunk_span）
- 分块标注（annotation）
- 向量索引引用管理
- FTS5 全文搜索
- sqlite-vec 向量检索
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from remnant_core.models import MemoryAnnotationSchema, MemoryChunkSchema, MemoryChunkSpanSchema


def _generate_uuid_v7() -> str:
    """生成 UUID（简化实现）。"""
    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    """获取当前 UTC 时间的 ISO 8601 格式字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ChunkDAO:
    """记忆分块数据访问对象。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_chunk(self, chunk: MemoryChunkSchema) -> str:
        """创建记忆分块。

        Args:
            chunk: 分块模型

        Returns:
            分块 ID
        """
        now = _utcnow_iso()
        self.conn.execute(
            """INSERT INTO memory_chunk
            (id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type,
             content, token_count, time_range_start, time_range_end, message_count,
             speaker_count, overlap_previous, overlap_next, status, metadata,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk.id,
                chunk.source_artifact_id,
                chunk.relationship_scope_id,
                chunk.chunk_hash,
                chunk.chunk_type.value,
                chunk.content,
                chunk.token_count,
                chunk.time_range_start,
                chunk.time_range_end,
                chunk.message_count,
                chunk.speaker_count,
                chunk.overlap_previous,
                chunk.overlap_next,
                chunk.status,
                _dict_to_json(chunk.metadata),
                chunk.created_at or now,
                chunk.updated_at or now,
            ),
        )
        self.conn.commit()
        return chunk.id

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """查询分块详情。

        Args:
            chunk_id: 分块 ID

        Returns:
            分块字典，不存在返回 None
        """
        cursor = self.conn.execute(
            "SELECT * FROM memory_chunk WHERE id = ? AND deleted_at IS NULL",
            (chunk_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_chunks_by_scope(
        self, scope_id: str, status: str = "ACTIVE", limit: int = 100
    ) -> list[dict[str, Any]]:
        """列出身域下所有活跃分块。

        Args:
            scope_id: 关系作用域 ID
            status: 分块状态过滤
            limit: 返回数量上限

        Returns:
            分块字典列表
        """
        cursor = self.conn.execute(
            """SELECT * FROM memory_chunk
            WHERE relationship_scope_id = ? AND status = ? AND deleted_at IS NULL
            ORDER BY time_range_start LIMIT ?""",
            (scope_id, status, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_fts(self, query: str, scope_id: str, top_k: int = 10) -> list[dict[str, Any]]:
        """FTS5 全文搜索。

        Args:
            query: 搜索查询
            scope_id: 作用域 ID
            top_k: 返回数量

        Returns:
            匹配的分块字典列表
        """
        cursor = self.conn.execute(
            """SELECT mc.*, rank
            FROM memory_chunk_fts fts
            JOIN memory_chunk mc ON mc.rowid = fts.rowid
            WHERE fts.content MATCH ? AND mc.relationship_scope_id = ? AND mc.deleted_at IS NULL
            ORDER BY rank LIMIT ?""",
            (query, scope_id, top_k),
        )
        return [dict(row) for row in cursor.fetchall()]

    def create_span(self, span: MemoryChunkSpanSchema) -> str:
        """创建分块溯源映射。

        Args:
            span: 溯源映射模型

        Returns:
            映射 ID
        """
        self.conn.execute(
            """INSERT INTO memory_chunk_span
            (id, chunk_id, normalized_message_id, char_start, char_end, source_speaker, source_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                span.id,
                span.chunk_id,
                span.normalized_message_id,
                span.char_start,
                span.char_end,
                span.source_speaker,
                span.source_timestamp,
            ),
        )
        self.conn.commit()
        return span.id

    def create_annotation(self, annotation: MemoryAnnotationSchema) -> str:
        """创建记忆标注。

        Args:
            annotation: 标注模型

        Returns:
            标注 ID
        """
        now = _utcnow_iso()
        self.conn.execute(
            """INSERT INTO memory_annotation
            (id, chunk_id, annotation_type, annotation_value, confidence, source, is_valid, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                annotation.id,
                annotation.chunk_id,
                annotation.annotation_type,
                annotation.annotation_value,
                annotation.confidence,
                annotation.source,
                int(annotation.is_valid),
                _dict_to_json(annotation.metadata),
                annotation.created_at or now,
                annotation.updated_at or now,
            ),
        )
        self.conn.commit()
        return annotation.id

    def soft_delete_chunk(self, chunk_id: str) -> bool:
        """软删除分块。

        Args:
            chunk_id: 分块 ID

        Returns:
            True 如果成功
        """
        now = _utcnow_iso()
        cursor = self.conn.execute(
            "UPDATE memory_chunk SET deleted_at = ?, status = 'DEPRECATED', updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now, now, chunk_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0


def _dict_to_json(d: dict[str, Any]) -> str:
    """将字典转为 JSON 字符串。"""
    import json

    return json.dumps(d, ensure_ascii=False, default=str)