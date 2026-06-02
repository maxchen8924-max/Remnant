"""FTS5 全文搜索模块 — 实现白皮书 RAG Pipeline Step 5 的 FTS5 分支。

功能:
- fts5_search(): FTS5 BM25 全文搜索 + scope 过滤
- 使用 chunk_visibility.get_visible_chunk_ids 获取可见 ID 集合
- 查询 memory_chunk_fts 虚拟表，JOIN memory_chunk 获取完整信息
- 返回 list[dict]，每项含 id, content, chunk_type, time_range_start,
  time_range_end, speaker_count, rank 等
"""

from __future__ import annotations

import sqlite3
from typing import Any

from remnant_store.chunk_visibility import get_visible_chunk_ids


def fts5_search(
    conn: sqlite3.Connection,
    query: str,
    scope_id: str,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """FTS5 BM25 全文搜索，带 scope 过滤。

    实现白皮书 RAG Pipeline Step 5 的 FTS5 分支:
    1. 通过 get_visible_chunk_ids 获取当前 scope 可见的所有 chunk ID
    2. 在 memory_chunk_fts 虚拟表中执行 FTS5 MATCH 查询
    3. JOIN memory_chunk 获取完整 chunk 信息
    4. 按 BM25 rank 升序返回 top_k 结果

    Args:
        conn: 数据库连接
        query: FTS5 搜索查询字符串
        scope_id: 关系作用域 ID
        top_k: 返回结果数量上限

    Returns:
        匹配的 chunk 字典列表，每项包含:
        - id, content, chunk_type, chunk_hash
        - time_range_start, time_range_end
        - speaker_count, message_count, token_count
        - source_artifact_id, relationship_scope_id
        - rank: FTS5 BM25 排名分数（越低越相关）
        - source: 'fts'
    """
    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return []

    # 构建 IN 子句的占位符
    # 参数顺序: MATCH query 在前，IN 子句在后，LIMIT 最后
    placeholders = ",".join("?" * len(visible_ids))
    params: list[Any] = [query]
    params.extend(visible_ids)
    params.append(top_k)

    sql = f"""SELECT mc.id, mc.source_artifact_id, mc.relationship_scope_id,
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
              LIMIT ?"""

    cursor = conn.execute(sql, params)
    results: list[dict[str, Any]] = []
    for row in cursor.fetchall():
        item = dict(row)
        item["source"] = "fts"
        results.append(item)

    return results


def fts5_count(
    conn: sqlite3.Connection,
    query: str,
    scope_id: str,
) -> int:
    """FTS5 搜索命中计数（不返回具体数据）。

    用于检索追踪记录中统计 FTS5 命中数量。

    Args:
        conn: 数据库连接
        query: FTS5 搜索查询字符串
        scope_id: 关系作用域 ID

    Returns:
        匹配的 chunk 数量
    """
    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return 0

    placeholders = ",".join("?" * len(visible_ids))
    params: list[Any] = [query]
    params.extend(visible_ids)

    sql = f"""SELECT COUNT(*)
              FROM memory_chunk_fts fts
              JOIN memory_chunk mc ON fts.rowid = mc.rowid
              WHERE memory_chunk_fts MATCH ?
                AND mc.id IN ({placeholders})
                AND mc.deleted_at IS NULL"""

    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    return row[0] if row else 0
