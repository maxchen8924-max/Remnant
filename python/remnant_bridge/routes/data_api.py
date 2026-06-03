"""POST /api/v1/data/destroy — 数据销毁 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from remnant_bridge.config import DEFAULT_DB_PATH
from remnant_bridge.runtime import destroy_scope_data, open_bridge_connection

router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.post("/destroy")
async def destroy_data(request: dict[str, Any]) -> dict:
    """销毁指定数据。

    请求体应包含:
    - scope_id: 要销毁数据的作用域 ID
    - deletion_type: 销毁类型 (scope_soft_delete / scope_hard_delete / selective_delete)
    - confirm: 用户确认标志
    - target_chunk_ids: 选择性删除时的 chunk ID 列表
    """
    scope_id = request.get("scope_id")
    deletion_type = request.get("deletion_type", "scope_soft_delete")
    confirm = bool(request.get("confirm", False))

    if not scope_id:
        raise HTTPException(status_code=400, detail="scope_id is required")

    conn = open_bridge_connection(DEFAULT_DB_PATH)
    try:
        result = destroy_scope_data(
            conn=conn,
            scope_id=scope_id,
            deletion_type=deletion_type,
            confirm=confirm,
            actor=str(request.get("actor", "user")),
        )
    finally:
        conn.close()

    if result["status"] == "requires_confirmation":
        raise HTTPException(status_code=400, detail=result["message"])
    if result["status"] == "unsupported":
        raise HTTPException(status_code=400, detail=result["message"])
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Deletion failed"))

    return result
