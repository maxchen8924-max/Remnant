"""Framework-light runtime helpers for the local bridge.

The FastAPI routes stay thin and delegate here so the core sidecar behaviors
can be tested without importing Pydantic/FastAPI. This also makes the v0.1
preview clearer for contributors: API wiring is separate from storage/runtime
logic.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from remnant_bridge.config import DEFAULT_DB_PATH, SQLCIPHER_KEY_ENV
from remnant_etl.pipeline import ETLPipeline
from remnant_store.schema import init_db
from remnant_store.scope_deletion import hard_delete_scope, soft_delete_scope


def open_bridge_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the bridge database and ensure the schema exists."""
    sqlcipher_key = os.environ.get(SQLCIPHER_KEY_ENV)
    return init_db(db_path, sqlcipher_key=sqlcipher_key)


def compute_file_sha256(file_path: str | Path) -> str:
    """Compute a file's SHA-256 hash."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(8192), b""):
            sha256.update(block)
    return sha256.hexdigest()


def run_import_pipeline(db_path: str, request: Any) -> dict[str, Any]:
    """Run ETL for an import request and return API-ready fields."""
    file_path = getattr(request, "file_path")
    metadata = getattr(request, "metadata", {}) or {}
    speaker_aliases = metadata.get("speaker_aliases") if isinstance(metadata, dict) else None
    chunk_config = metadata.get("chunk_config") if isinstance(metadata, dict) else None

    file_hash = compute_file_sha256(file_path)
    pipeline = ETLPipeline(db_path=db_path)
    result = pipeline.run(
        file_path=file_path,
        file_type=getattr(request, "file_type"),
        deceased_profile_id=getattr(request, "deceased_profile_id"),
        scope_id=getattr(request, "scope_id", None),
        speaker_aliases=speaker_aliases,
        config=chunk_config,
    )

    errors = result.get("errors", [])
    return {
        "artifact_id": result.get("artifact_id", ""),
        "file_hash": file_hash,
        "message_count": result.get("raw_count", 0),
        "chunk_count": result.get("chunk_count", 0),
        "parse_status": "FAILED" if errors else "PARSED",
        "errors": errors,
    }


def build_query_response_content(
    query: str,
    candidates: list[dict[str, Any]],
) -> str:
    """Build an evidence summary without persona simulation or unsupported claims."""
    if not candidates:
        return (
            "No matching evidence was found in the selected relationship scope. "
            "I cannot answer this as a factual memory yet."
        )

    lines = ["Evidence-backed memory summary:"]
    for index, item in enumerate(candidates[:5], start=1):
        content = _clip_whitespace(str(item.get("content", "")), max_chars=320)
        score = item.get("combined_score")
        source = item.get("source", "retrieval")
        score_text = f", score={score:.2f}" if isinstance(score, (int, float)) else ""
        lines.append(f"{index}. {content} [{source}{score_text}]")

    lines.append("No persona generation was performed; this is a retrieval summary.")
    return "\n".join(lines)


def run_query_retrieval(
    conn: sqlite3.Connection,
    scope_id: str,
    query: str,
    top_k: int = 10,
) -> dict[str, Any]:
    """Run scoped retrieval and return a query response payload."""
    started = time.monotonic()
    session_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    if not _scope_exists(conn, scope_id):
        return {
            "session_id": session_id,
            "message_id": message_id,
            "content": build_query_response_content(query, []),
            "retrieval_trace_id": None,
            "duration_ms": _elapsed_ms(started),
            "safety_flags": ["scope_not_found"],
        }

    from remnant_core.rerank import rerank_candidates
    from remnant_core.retrieval import get_hybrid_results_for_trace, hybrid_retrieve
    from remnant_core.trace import record_retrieval_trace

    try:
        fts_raw, vector_raw = get_hybrid_results_for_trace(
            query=query,
            scope_id=scope_id,
            conn=conn,
            query_embedding=None,
            top_k=top_k,
        )
        candidates = hybrid_retrieve(
            query=query,
            scope_id=scope_id,
            conn=conn,
            query_embedding=None,
            top_k=top_k,
        )
        if not candidates:
            candidates = _keyword_fallback_retrieve(conn, scope_id, query, top_k)
        reranked = rerank_candidates(
            query=query,
            candidates=candidates or fts_raw,
            top_k=top_k,
            use_mmr=True,
        )
        duration_ms = _elapsed_ms(started)
        trace_id = record_retrieval_trace(
            conn=conn,
            scope_id=scope_id,
            query_text=query,
            fts_results=fts_raw,
            vector_results=vector_raw,
            reranked_results=reranked,
            total_duration_ms=duration_ms,
        )
    except Exception as exc:
        return {
            "session_id": session_id,
            "message_id": message_id,
            "content": f"Retrieval failed: {exc}",
            "retrieval_trace_id": None,
            "duration_ms": _elapsed_ms(started),
            "safety_flags": ["retrieval_error"],
        }

    return {
        "session_id": session_id,
        "message_id": message_id,
        "content": build_query_response_content(query, reranked),
        "retrieval_trace_id": trace_id,
        "duration_ms": _elapsed_ms(started),
        "safety_flags": [],
    }


def destroy_scope_data(
    conn: sqlite3.Connection,
    scope_id: str,
    deletion_type: str,
    confirm: bool,
    actor: str = "user",
) -> dict[str, Any]:
    """Dispatch data destruction to the scoped deletion implementation."""
    if not confirm:
        return {
            "success": False,
            "status": "requires_confirmation",
            "message": "Deletion requires confirm=true",
            "scope_id": scope_id,
            "deletion_type": deletion_type,
        }

    if deletion_type == "scope_soft_delete":
        result = soft_delete_scope(conn, scope_id, actor=actor)
    elif deletion_type == "scope_hard_delete":
        result = hard_delete_scope(conn, scope_id, actor=actor)
    else:
        return {
            "success": False,
            "status": "unsupported",
            "message": f"Unsupported deletion type: {deletion_type}",
            "scope_id": scope_id,
            "deletion_type": deletion_type,
        }

    return {
        **result,
        "status": "completed" if result.get("success") else "failed",
        "message": result.get("error", "Deletion completed"),
    }


def _scope_exists(conn: sqlite3.Connection, scope_id: str) -> bool:
    row = conn.execute(
        "SELECT id FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
        (scope_id,),
    ).fetchone()
    return row is not None


def _keyword_fallback_retrieve(
    conn: sqlite3.Connection,
    scope_id: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Plain LIKE fallback for preview data when FTS tokenization misses CJK."""
    from remnant_store.chunk_visibility import get_visible_chunk_ids

    visible_ids = get_visible_chunk_ids(conn, scope_id)
    if not visible_ids:
        return []

    placeholders = ",".join("?" * len(visible_ids))
    params: list[Any] = list(visible_ids)
    params.extend([f"%{query}%", top_k])
    cursor = conn.execute(
        f"""SELECT id, source_artifact_id, relationship_scope_id, chunk_hash,
                   chunk_type, content, token_count, time_range_start,
                   time_range_end, message_count, speaker_count, status,
                   metadata, created_at, updated_at
        FROM memory_chunk
        WHERE id IN ({placeholders})
          AND content LIKE ?
          AND status = 'ACTIVE'
          AND deleted_at IS NULL
        ORDER BY created_at
        LIMIT ?""",
        params,
    )
    rows = []
    for row in cursor.fetchall():
        item = dict(row)
        item["source"] = "keyword_fallback"
        item["combined_score"] = 0.35
        item["fts_score"] = 0.0
        item["vector_score"] = 0.0
        rows.append(item)
    return rows


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _clip_whitespace(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."
