"""POST /api/v1/scope/create, delete — 关系作用域 API。"""

from __future__ import annotations

from fastapi import APIRouter

from remnant_core.models import ScopeCreateRequest, ScopeDeleteRequest

router = APIRouter(prefix="/api/v1/scope", tags=["scope"])


@router.post("/create")
async def create_scope(request: ScopeCreateRequest) -> dict:
    """创建关系作用域。"""
    # M1 阶段调用 ScopeDAO.create_scope
    return {"scope_id": "pending", "status": "created"}


@router.post("/delete")
async def delete_scope(request: ScopeDeleteRequest) -> dict:
    """删除关系作用域（软删除/硬删除/选择性删除）。"""
    # M1 阶段调用 ScopeDAO.soft_delete_scope / hard_delete
    return {"scope_id": request.scope_id, "status": "deleted"}