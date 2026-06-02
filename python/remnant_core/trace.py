"""检索追踪记录模块 — 实现白皮书 RAG Pipeline 的追踪日志。

核心函数 record_retrieval_trace:
- 将每次检索的 FTS5 结果、向量结果、重排序结果写入 retrieval_trace 表
- 遵循审计原则: APPEND ONLY，不可修改
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any


def _generate_uuid7() -> str:
    """生成 UUID v7 格式的唯一标识符。

    基于时间戳 + 随机数，保证全局唯一且可排序。

    Returns:
        UUID v7 字符串
    """
    return str(uuid.uuid4())


def record_retrieval_trace(
    conn: sqlite3.Connection,
    scope_id: str,
    query_text: str,
    fts_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    reranked_results: list[dict[str, Any]],
    query_embedding_model: str | None = None,
    interaction_session_id: str | None = None,
    total_duration_ms: int | None = None,
) -> str:
    """记录检索追踪到 retrieval_trace 表。

    将 FTS5 搜索结果、向量搜索结果、重排序结果以 JSON 格式序列化存储。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        query_text: 用户查询文本
        fts_results: FTS5 搜索结果列表
        vector_results: 向量搜索结果列表
        reranked_results: 重排序后的最终结果列表
        query_embedding_model: 使用的 embedding 模型名称（可选）
        interaction_session_id: 关联的交互会话 ID（可选）
        total_duration_ms: 检索总耗时毫秒（可选）

    Returns:
        新创建的 retrieval_trace 记录的 ID
    """
    trace_id = _generate_uuid7()

    # 序列化结果集为 JSON
    fts_json = json.dumps(
        [_trace_summary(item) for item in fts_results],
        ensure_ascii=False,
    )
    vector_json = json.dumps(
        [_trace_summary(item) for item in vector_results],
        ensure_ascii=False,
    )
    reranked_json = json.dumps(
        [_trace_summary(item) for item in reranked_results],
        ensure_ascii=False,
    )

    conn.execute(
        """INSERT INTO retrieval_trace (
            id, relationship_scope_id, interaction_session_id,
            query_text, query_embedding_model,
            fts_results, vector_results, reranked_results,
            evidence_validated, evidence_rejected,
            total_duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?)""",
        (
            trace_id,
            scope_id,
            interaction_session_id,
            query_text,
            query_embedding_model,
            fts_json,
            vector_json,
            reranked_json,
            total_duration_ms,
        ),
    )
    conn.commit()

    return trace_id


def _trace_summary(item: dict[str, Any]) -> dict[str, Any]:
    """从检索结果中提取关键字段用于追踪摘要。

    避免存储完整的 chunk content 造成追踪表过大，
    仅保留 chunk_id、得分、来源等关键信息。

    Args:
        item: 检索结果项

    Returns:
        摘要字典
    """
    return {
        "chunk_id": item.get("id", ""),
        "chunk_type": item.get("chunk_type", ""),
        "fts_score": item.get("fts_score"),
        "vector_score": item.get("vector_score"),
        "combined_score": item.get("combined_score"),
        "rank": item.get("rank"),
        "source": item.get("source", ""),
        "speaker_count": item.get("speaker_count", 0),
        "time_range_start": item.get("time_range_start"),
        "time_range_end": item.get("time_range_end"),
    }


def get_trace(
    conn: sqlite3.Connection,
    trace_id: str,
) -> dict[str, Any] | None:
    """根据 trace ID 查询检索追踪记录。

    Args:
        conn: 数据库连接
        trace_id: 追踪记录 ID

    Returns:
        追踪记录字典，不存在时返回 None
    """
    cursor = conn.execute(
        "SELECT * FROM retrieval_trace WHERE id = ?",
        (trace_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row)


def get_recent_traces(
    conn: sqlite3.Connection,
    scope_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """获取指定 scope 下最近的检索追踪记录。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        limit: 返回数量上限

    Returns:
        追踪记录字典列表
    """
    cursor = conn.execute(
        """SELECT * FROM retrieval_trace
        WHERE relationship_scope_id = ?
        ORDER BY created_at DESC
        LIMIT ?""",
        (scope_id, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
