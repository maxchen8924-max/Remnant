"""向量搜索模块 — 实现白皮书 RAG Pipeline Step 5 的向量搜索分支。

功能:
- vector_search(): 向量相似度搜索 + scope 过滤
- _compute_cosine_similarity(): 余弦相似度辅助函数
- 回退方案: 当 sqlite-vec 不可用时，从 embedding_index_ref 表加载 embedding，
  在 Python 中计算余弦相似度
- 使用 get_visible_chunk_ids 做 scope 过滤
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any


def _compute_cosine_similarity(
    vec_a: list[float],
    vec_b: list[float],
) -> float:
    """计算两个向量的余弦相似度。

    余弦相似度 = (A · B) / (||A|| * ||B||)

    Args:
        vec_a: 向量 A
        vec_b: 向量 B

    Returns:
        余弦相似度值，范围 [-1, 1]。向量维度不一致时抛出 ValueError。
        零向量返回 0.0。

    Raises:
        ValueError: 向量维度不一致
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"向量维度不一致: len(vec_a)={len(vec_a)}, len(vec_b)={len(vec_b)}"
        )

    if len(vec_a) == 0:
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def _vector_search_fallback(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    visible_ids: set[str],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """向量搜索回退方案: Python 原生余弦相似度计算。

    从 embedding_index_ref 表加载已索引的 embedding（存储在 metadata JSON 中），
    在 Python 中计算余弦相似度，排序返回 top_k 结果。

    Args:
        conn: 数据库连接
        query_embedding: 查询向量
        visible_ids: 可见 chunk ID 集合
        top_k: 返回结果数量上限

    Returns:
        匹配的 chunk 字典列表，每项包含 vector_score 和 source='vector'
    """
    if not visible_ids:
        return []

    placeholders = ",".join("?" * len(visible_ids))
    params: list[Any] = list(visible_ids)

    # 查询已索引且属于可见 scope 的 embedding 记录
    sql = f"""SELECT eir.id AS embedding_id, eir.chunk_id, eir.model_name,
                     eir.model_version, eir.vector_dimension, eir.metadata,
                     mc.id, mc.source_artifact_id, mc.relationship_scope_id,
                     mc.chunk_hash, mc.chunk_type, mc.content, mc.token_count,
                     mc.time_range_start, mc.time_range_end, mc.message_count,
                     mc.speaker_count, mc.status, mc.metadata AS chunk_metadata,
                     mc.created_at, mc.updated_at
              FROM embedding_index_ref eir
              JOIN memory_chunk mc ON eir.chunk_id = mc.id
              WHERE eir.chunk_id IN ({placeholders})
                AND eir.index_status = 'INDEXED'
                AND mc.deleted_at IS NULL"""

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        row_dict = dict(row)

        # 从 metadata JSON 中提取 embedding 向量
        metadata_str = row_dict.get("metadata", "{}")
        try:
            metadata = json.loads(metadata_str) if metadata_str else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        embedding_vec = metadata.get("vector")
        if embedding_vec is None or not isinstance(embedding_vec, list):
            continue

        # 计算余弦相似度
        try:
            similarity = _compute_cosine_similarity(query_embedding, embedding_vec)
        except ValueError:
            continue

        item = {
            "id": row_dict["id"],
            "source_artifact_id": row_dict.get("source_artifact_id"),
            "relationship_scope_id": row_dict.get("relationship_scope_id"),
            "chunk_hash": row_dict.get("chunk_hash"),
            "chunk_type": row_dict.get("chunk_type"),
            "content": row_dict.get("content"),
            "token_count": row_dict.get("token_count", 0),
            "time_range_start": row_dict.get("time_range_start"),
            "time_range_end": row_dict.get("time_range_end"),
            "message_count": row_dict.get("message_count", 0),
            "speaker_count": row_dict.get("speaker_count", 0),
            "status": row_dict.get("status"),
            "metadata": row_dict.get("chunk_metadata", "{}"),
            "created_at": row_dict.get("created_at"),
            "updated_at": row_dict.get("updated_at"),
            "embedding_id": row_dict.get("embedding_id"),
            "model_name": row_dict.get("model_name"),
            "vector_dimension": row_dict.get("vector_dimension"),
            "vector_score": similarity,
            "source": "vector",
        }
        scored.append((similarity, item))

    # 按相似度降序排序
    scored.sort(key=lambda x: x[0], reverse=True)

    return [item for _, item in scored[:top_k]]


def _vector_search_sqlite_vec(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    visible_ids: set[str],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """使用 sqlite-vec 扩展进行向量搜索。

    Args:
        conn: 数据库连接
        query_embedding: 查询向量
        visible_ids: 可见 chunk ID 集合
        top_k: 返回结果数量上限

    Returns:
        匹配的 chunk 字典列表
    """
    # sqlite-vec 需要 embedding 以 BLOB 形式存储在单独的 vec0 虚拟表中
    # 当前 schema 使用 embedding_index_ref 存储元数据，实际向量存储在
    # 外部 sqlite-vec 虚拟表中。M2 阶段回退到 Python 余弦相似度。
    return _vector_search_fallback(conn, query_embedding, visible_ids, top_k)


def vector_search(
    conn: sqlite3.Connection,
    query_embedding: list[float] | None,
    scope_id: str,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """向量相似度搜索，带 scope 过滤。

    实现白皮书 RAG Pipeline Step 5 的向量搜索分支:
    1. 通过 get_visible_chunk_ids 获取当前 scope 可见的所有 chunk ID
    2. 尝试使用 sqlite-vec 扩展进行搜索
    3. 如果 sqlite-vec 不可用，回退到 Python 原生余弦相似度计算
    4. 返回 top_k 结果，按相似度降序排列

    Args:
        conn: 数据库连接
        query_embedding: 查询向量（None 时返回空列表）
        scope_id: 关系作用域 ID
        top_k: 返回结果数量上限

    Returns:
        匹配的 chunk 字典列表，每项包含 vector_score 和 source='vector'
    """
    if query_embedding is None:
        return []

    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return []

    # 尝试 sqlite-vec，失败则回退
    try:
        return _vector_search_sqlite_vec(
            conn, query_embedding, visible_ids, top_k
        )
    except Exception:
        return _vector_search_fallback(
            conn, query_embedding, visible_ids, top_k
        )


def vector_count(
    conn: sqlite3.Connection,
    scope_id: str,
) -> int:
    """向量搜索可用 embedding 计数。

    统计当前 scope 下有多少 chunk 已建立 embedding 索引。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID

    Returns:
        已索引的 chunk 数量
    """
    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return 0

    placeholders = ",".join("?" * len(visible_ids))
    params: list[Any] = list(visible_ids)

    sql = f"""SELECT COUNT(*)
              FROM embedding_index_ref eir
              JOIN memory_chunk mc ON eir.chunk_id = mc.id
              WHERE eir.chunk_id IN ({placeholders})
                AND eir.index_status = 'INDEXED'
                AND mc.deleted_at IS NULL"""

    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    return row[0] if row else 0


# 重新导出 get_visible_chunk_ids 方便使用
from remnant_store.chunk_visibility import get_visible_chunk_ids  # noqa: E402, F811
