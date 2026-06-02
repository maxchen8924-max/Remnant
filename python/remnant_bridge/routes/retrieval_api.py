"""POST /api/v1/retrieve — 检索 API 端点。

实现白皮书 RAG Pipeline Step 5-8 的 HTTP 接口:
- 接收 {query, scope_id, top_k} 请求体
- 执行混合检索（FTS5 + Vector + Rerank）
- 记录检索追踪到 retrieval_trace 表
- 使用 ephemeral token 鉴权
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from remnant_bridge.config import DEFAULT_DB_PATH
from remnant_core.retrieval import hybrid_retrieve, get_hybrid_results_for_trace
from remnant_core.rerank import rerank_candidates
from remnant_core.trace import record_retrieval_trace
from remnant_store.db import get_connection

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


def _get_db_path() -> Path:
    """获取数据库文件路径。

    Returns:
        数据库文件的绝对路径
    """
    return Path(DEFAULT_DB_PATH).expanduser().resolve()


@router.post("/retrieve")
async def retrieve_chunks(request: Request) -> JSONResponse:
    """混合检索端点。

    请求体:
        {
            "query": "爸爸喜欢吃什么？",
            "scope_id": "uuid-v7-scope-id",
            "top_k": 10,
            "query_class": {
                "time_references": ["2023-06"],
                "target_speaker": "爸爸"
            }
        }

    响应:
        {
            "candidates": [...],
            "trace_id": "uuid-v7",
            "fts_count": 15,
            "vector_count": 12,
            "reranked_count": 10
        }
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid JSON body"},
        )

    query: str = body.get("query", "")
    scope_id: str = body.get("scope_id", "")
    top_k: int = body.get("top_k", 10)
    query_class: dict[str, Any] | None = body.get("query_class")

    # 参数校验
    if not query:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing required field: query"},
        )
    if not scope_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing required field: scope_id"},
        )
    if top_k < 1 or top_k > 50:
        return JSONResponse(
            status_code=400,
            content={"detail": "top_k must be between 1 and 50"},
        )

    # 获取数据库连接
    db_path = _get_db_path()
    if not db_path.exists():
        return JSONResponse(
            status_code=503,
            content={"detail": "Database not initialized"},
        )

    conn: sqlite3.Connection | None = None
    try:
        start_time = time.time()
        conn = get_connection(str(db_path))

        # 获取原始搜索结果（用于追踪）
        fts_raw, vec_raw = get_hybrid_results_for_trace(
            query=query,
            scope_id=scope_id,
            conn=conn,
            query_embedding=None,  # API 层暂不传 embedding
            top_k=top_k,
            query_class=query_class,
        )

        # 执行混合检索（不含向量搜索，因为 API 层不传 embedding）
        candidates = hybrid_retrieve(
            query=query,
            scope_id=scope_id,
            conn=conn,
            query_embedding=None,
            top_k=top_k,
            query_class=query_class,
        )

        # 重排序
        reranked = rerank_candidates(
            query=query,
            candidates=candidates,
            query_class=query_class,
            top_k=top_k,
            use_mmr=True,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        # 记录追踪
        trace_id = record_retrieval_trace(
            conn=conn,
            scope_id=scope_id,
            query_text=query,
            fts_results=fts_raw,
            vector_results=vec_raw,
            reranked_results=reranked,
            query_embedding_model=None,
            total_duration_ms=elapsed_ms,
        )

        return JSONResponse(
            content={
                "candidates": _serialize_candidates(reranked),
                "trace_id": trace_id,
                "fts_count": len(fts_raw),
                "vector_count": len(vec_raw),
                "reranked_count": len(reranked),
                "duration_ms": elapsed_ms,
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Retrieval failed: {str(e)}"},
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _serialize_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将候选 chunk 序列化为 API 响应格式。

    仅保留必要的字段，确保 JSON 可序列化。

    Args:
        candidates: 候选 chunk 列表

    Returns:
        序列化后的候选列表
    """
    result: list[dict[str, Any]] = []
    for item in candidates:
        serialized: dict[str, Any] = {
            "chunk_id": item.get("id", ""),
            "chunk_type": item.get("chunk_type", ""),
            "content": item.get("content", ""),
            "combined_score": item.get("combined_score", 0.0),
            "fts_score": item.get("fts_score"),
            "vector_score": item.get("vector_score"),
            "time_boost": item.get("time_boost"),
            "speaker_boost": item.get("speaker_boost"),
            "source": item.get("source", ""),
            "time_range_start": item.get("time_range_start"),
            "time_range_end": item.get("time_range_end"),
            "speaker_count": item.get("speaker_count", 0),
        }
        result.append(serialized)
    return result
