"""POST /api/v1/data/destroy — 数据销毁 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

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
    # M1 阶段实现数据销毁逻辑
    return {"status": "pending", "message": "M1 阶段实现"}