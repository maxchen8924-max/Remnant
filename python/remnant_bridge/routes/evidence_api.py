"""Evidence provenance API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from remnant_bridge.config import DEFAULT_DB_PATH
from remnant_bridge.runtime import get_evidence_trace, open_bridge_connection

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("/trace/{trace_id}")
async def inspect_trace_evidence(trace_id: str) -> dict:
    """Inspect the evidence behind a retrieval trace."""
    conn = open_bridge_connection(DEFAULT_DB_PATH)
    try:
        payload = get_evidence_trace(conn, trace_id)
    finally:
        conn.close()

    if payload is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
    return payload


@router.get("/{claim_id}")
async def get_evidence(claim_id: str) -> dict:
    """获取指定 Claim 的证据链。

    返回 claim → chunk → chunk_span → normalized_message → source_artifact 完整溯源。
    """
    # M1 阶段实现数据库查询
    return {"claim_id": claim_id, "evidences": []}
