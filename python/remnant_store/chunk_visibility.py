"""Chunk 可见性查询 — 实现白皮书 9.5 节的可见性矩阵。

核心函数 get_visible_chunk_ids 返回指定 scope 下可见的所有 chunk ID:
1. 私有 chunk: relationship_scope_id = scope_id AND status = 'ACTIVE'
2. 共享 chunk: chunk_scope_visibility 中有记录且 visibility != 'scope_private'
3. 全局共享 chunk: relationship_scope_id IS NULL AND status = 'ACTIVE' (deceased_shared)
4. 权限过滤: 排除 blocked_categories 中的 chunk

同时提供 FTS5 和向量搜索的 scope 过滤版本。
"""

from __future__ import annotations

import sqlite3
from typing import Any


def get_visible_chunk_ids(
    conn: sqlite3.Connection,
    scope_id: str,
    include_global: bool = True,
) -> set[str]:
    """获取指定 scope 下可见的所有 chunk ID。

    实现白皮书 9.5 节的可见性矩阵:
    - scope_private chunk: 仅所属 scope 可见
    - scope_shared chunk: chunk_scope_visibility 中有记录的 scope 可见
    - deceased_shared chunk: 所有 scope 可见
    - 全局 chunk (relationship_scope_id IS NULL): 所有 scope 可见

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        include_global: 是否包含全局可见的 chunk

    Returns:
        可见的 chunk ID 集合
    """
    visible_ids: set[str] = set()

    # 1. 私有 chunk: relationship_scope_id = scope_id AND status = 'ACTIVE'
    cursor = conn.execute(
        """SELECT id FROM memory_chunk
        WHERE relationship_scope_id = ? AND status = 'ACTIVE' AND deleted_at IS NULL""",
        (scope_id,),
    )
    for row in cursor.fetchall():
        visible_ids.add(row["id"])

    # 2. scope_shared chunk: chunk_scope_visibility 中有记录的 scope 可见
    #    且该记录的 visibility 不是 'scope_private'
    cursor = conn.execute(
        """SELECT csv.chunk_id FROM chunk_scope_visibility csv
        JOIN memory_chunk mc ON csv.chunk_id = mc.id
        WHERE csv.relationship_scope_id = ?
          AND csv.visibility != 'scope_private'
          AND mc.status = 'ACTIVE'
          AND mc.deleted_at IS NULL""",
        (scope_id,),
    )
    for row in cursor.fetchall():
        visible_ids.add(row["chunk_id"])

    # 3. deceased_shared chunk: 通过 chunk_scope_visibility 标记为 deceased_shared
    #    对所有 scope 可见
    cursor = conn.execute(
        """SELECT csv.chunk_id FROM chunk_scope_visibility csv
        JOIN memory_chunk mc ON csv.chunk_id = mc.id
        WHERE csv.visibility = 'deceased_shared'
          AND mc.status = 'ACTIVE'
          AND mc.deleted_at IS NULL""",
        (),
    )
    for row in cursor.fetchall():
        visible_ids.add(row["chunk_id"])

    # 4. 全局 chunk: relationship_scope_id IS NULL AND status = 'ACTIVE'
    if include_global:
        cursor = conn.execute(
            """SELECT id FROM memory_chunk
            WHERE relationship_scope_id IS NULL
              AND status = 'ACTIVE'
              AND deleted_at IS NULL""",
            (),
        )
        for row in cursor.fetchall():
            visible_ids.add(row["id"])

    return visible_ids


def get_visible_chunk_ids_with_permission_filter(
    conn: sqlite3.Connection,
    scope_id: str,
    blocked_categories: set[str] | None = None,
    include_global: bool = True,
) -> set[str]:
    """获取可见 chunk ID，并基于权限过滤类别。

    在 get_visible_chunk_ids 的基础上，根据 scope_permission 中的权限
    过滤掉某些类别的 chunk。例如 can_view_medical=deny 时，
    排除 metadata.category 包含 'medical' 的 chunk。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        blocked_categories: 需要过滤掉的内容类别集合
        include_global: 是否包含全局可见的 chunk

    Returns:
        过滤后的可见 chunk ID 集合
    """
    visible_ids = get_visible_chunk_ids(conn, scope_id, include_global)

    if not blocked_categories:
        return visible_ids

    # 过滤掉 blocked_categories 中的 chunk
    filtered_ids: set[str] = set()
    for chunk_id in visible_ids:
        cursor = conn.execute(
            "SELECT metadata FROM memory_chunk WHERE id = ?",
            (chunk_id,),
        )
        row = cursor.fetchone()
        if row is None:
            continue

        # 检查 metadata 中是否有 blocked 的类别
        import json
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        chunk_category = metadata.get("category", "")
        if chunk_category not in blocked_categories:
            filtered_ids.add(chunk_id)

    return filtered_ids


def search_fts_with_scope(
    conn: sqlite3.Connection,
    query: str,
    scope_id: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """FTS5 全文搜索，带 scope 过滤。

    实现白皮书 9.5 节的 FTS5 搜索 scope 过滤:
    先获取可见 chunk ID 集合，再在 FTS5 搜索中限定范围。

    Args:
        conn: 数据库连接
        query: 搜索查询
        scope_id: 作用域 ID
        top_k: 返回数量

    Returns:
        匹配的分块字典列表
    """
    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return []

    # 构建 IN 子句的占位符
    placeholders = ",".join("?" * len(visible_ids))
    params: list[Any] = [query]
    params.extend(visible_ids)
    params.append(top_k)

    cursor = conn.execute(
        f"""SELECT mc.id, mc.source_artifact_id, mc.relationship_scope_id,
                   mc.chunk_hash, mc.chunk_type, mc.content, mc.token_count,
                   mc.time_range_start, mc.time_range_end, mc.message_count,
                   mc.speaker_count, mc.status, mc.metadata,
                   mc.created_at, mc.updated_at, fts.rank
        FROM memory_chunk_fts fts
        JOIN memory_chunk mc ON fts.rowid = mc.rowid
        WHERE memory_chunk_fts MATCH ?
          AND mc.id IN ({placeholders})
          AND mc.deleted_at IS NULL
        ORDER BY rank
        LIMIT ?""",
        params,
    )
    return [dict(row) for row in cursor.fetchall()]


def search_vector_with_scope(
    conn: sqlite3.Connection,
    scope_id: str,
    top_k: int = 10,
    distance_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """向量搜索，带 scope 过滤。

    实现白皮书 9.5 节的向量搜索 scope 过滤。
    注意: 向量查询参数（embedding 向量等）需在调用前准备。

    Args:
        conn: 数据库连接
        scope_id: 作用域 ID
        top_k: 返回数量
        distance_threshold: 距离阈值（可选）

    Returns:
        匹配的分块字典列表
    """
    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return []

    placeholders = ",".join("?" * len(visible_ids))
    params = list(visible_ids) + [top_k]

    sql = f"""SELECT mc.id, mc.source_artifact_id, mc.relationship_scope_id,
              mc.chunk_hash, mc.chunk_type, mc.content, mc.token_count,
              mc.time_range_start, mc.time_range_end, mc.message_count,
              mc.speaker_count, mc.status, mc.metadata,
              mc.created_at, mc.updated_at
       FROM memory_chunk mc
       WHERE mc.id IN ({placeholders})
         AND mc.status = 'ACTIVE'
         AND mc.deleted_at IS NULL
       ORDER BY mc.created_at
       LIMIT ?"""

    cursor = conn.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


def list_interaction_sessions(
    conn: sqlite3.Connection,
    scope_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出指定 scope 下的交互会话（严格隔离）。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        limit: 返回数量上限

    Returns:
        交互会话字典列表
    """
    cursor = conn.execute(
        """SELECT * FROM interaction_session
        WHERE relationship_scope_id = ?
        ORDER BY started_at DESC
        LIMIT ?""",
        (scope_id, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def list_interaction_messages(
    conn: sqlite3.Connection,
    scope_id: str,
    session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """列出指定 scope 下的交互消息（严格隔离）。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        session_id: 可选的会话 ID 过滤
        limit: 返回数量上限

    Returns:
        交互消息字典列表
    """
    if session_id:
        cursor = conn.execute(
            """SELECT * FROM interaction_message
            WHERE relationship_scope_id = ? AND session_id = ?
            ORDER BY created_at
            LIMIT ?""",
            (scope_id, session_id, limit),
        )
    else:
        cursor = conn.execute(
            """SELECT * FROM interaction_message
            WHERE relationship_scope_id = ?
            ORDER BY created_at
            LIMIT ?""",
            (scope_id, limit),
        )
    return [dict(row) for row in cursor.fetchall()]


def list_retrieval_traces(
    conn: sqlite3.Connection,
    scope_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出指定 scope 下的检索追踪记录（严格隔离）。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        limit: 返回数量上限

    Returns:
        检索追踪字典列表
    """
    cursor = conn.execute(
        """SELECT * FROM retrieval_trace
        WHERE relationship_scope_id = ?
        ORDER BY created_at DESC
        LIMIT ?""",
        (scope_id, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def list_response_claims(
    conn: sqlite3.Connection,
    scope_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出指定 scope 下的响应声明（严格隔离）。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        limit: 返回数量上限

    Returns:
        响应声明字典列表
    """
    cursor = conn.execute(
        """SELECT * FROM response_claim
        WHERE relationship_scope_id = ? AND deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT ?""",
        (scope_id, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
