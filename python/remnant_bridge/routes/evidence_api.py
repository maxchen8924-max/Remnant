"""GET /api/v1/evidence/{claim_id} — 证据溯源 API。"""

from __future__ import annotations

from fastapi import APIRouter

from remnant_core.models import EvidenceSchema

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("/{claim_id}")
async def get_evidence(claim_id: str) -> dict:
    """获取指定 Claim 的证据链。

    返回 claim → chunk → chunk_span → normalized_message → source_artifact 完整溯源。
    """
    # M1 阶段实现数据库查询
    return {"claim_id": claim_id, "evidences": []}