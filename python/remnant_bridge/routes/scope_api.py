"""POST /api/v1/scope/create, delete, list, get — 关系作用域 API。

提供 Scope 的完整 CRUD 端点:
- POST /api/v1/scope/create — 创建作用域
- POST /api/v1/scope/delete — 删除作用域（软删除/硬删除）
- GET /api/v1/scope/{scope_id} — 查询作用域详情
- GET /api/v1/scope/list — 列出逝者下的所有作用域
- GET /api/v1/scope/{scope_id}/permissions — 查询权限配置
- GET /api/v1/scope/{scope_id}/safety-policy — 查询安全策略
- GET /api/v1/scope/{scope_id}/prompt-policies — 查询 Prompt 策略
- PUT /api/v1/scope/{scope_id}/permissions — 更新权限
- PUT /api/v1/scope/{scope_id}/prompt-policy — 更新 Prompt 策略
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from remnant_core.models import (
    ScopeCreateRequest,
    ScopeDeleteRequest,
)
from remnant_store.db import get_connection
from remnant_store.scope_dao import ScopeDAO
from remnant_store.scope_deletion import hard_delete_scope, soft_delete_scope

router = APIRouter(prefix="/api/v1/scope", tags=["scope"])


def _get_conn() -> Any:
    """获取数据库连接依赖。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@router.post("/create")
async def create_scope(request: ScopeCreateRequest) -> dict:
    """创建关系作用域。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        scope_id = dao.create_scope(request)
        scope = dao.get_scope(scope_id)
        return {
            "scope_id": scope_id,
            "status": "created",
            "scope": scope,
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/delete")
async def delete_scope(request: ScopeDeleteRequest) -> dict:
    """删除关系作用域（软删除/硬删除/选择性删除）。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        if request.deletion_type.value == "scope_soft_delete":
            result = soft_delete_scope(conn, request.scope_id)
        elif request.deletion_type.value == "scope_hard_delete":
            result = hard_delete_scope(conn, request.scope_id)
        else:
            result = {"success": False, "error": f"Unsupported deletion type: {request.deletion_type}"}

        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Deletion failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/{scope_id}")
async def get_scope(scope_id: str) -> dict:
    """查询作用域详情。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        scope = dao.get_scope(scope_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Scope {scope_id} not found")
        return {"scope": scope}
    finally:
        conn.close()


@router.get("/list/{deceased_profile_id}")
async def list_scopes(deceased_profile_id: str) -> dict:
    """列出逝者下所有活跃作用域。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        scopes = dao.list_scopes(deceased_profile_id)
        return {"scopes": scopes, "count": len(scopes)}
    finally:
        conn.close()


@router.get("/{scope_id}/permissions")
async def get_permissions(scope_id: str) -> dict:
    """查询作用域权限配置。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        permissions = dao.get_permissions(scope_id)
        return {"scope_id": scope_id, "permissions": permissions}
    finally:
        conn.close()


@router.get("/{scope_id}/safety-policy")
async def get_safety_policy(scope_id: str) -> dict:
    """查询作用域安全策略。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        policy = dao.get_safety_policy(scope_id)
        if policy is None:
            raise HTTPException(status_code=404, detail=f"Safety policy for scope {scope_id} not found")
        return {"scope_id": scope_id, "safety_policy": policy}
    finally:
        conn.close()


@router.get("/{scope_id}/prompt-policies")
async def get_prompt_policies(scope_id: str) -> dict:
    """查询作用域 Prompt 策略。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        policies = dao.get_prompt_policies(scope_id)
        return {"scope_id": scope_id, "prompt_policies": policies}
    finally:
        conn.close()


@router.put("/{scope_id}/permissions/{permission_key}")
async def set_permission(scope_id: str, permission_key: str, permission_value: str = "allow") -> dict:
    """更新作用域权限。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        perm_id = dao.set_permission(scope_id, permission_key, permission_value)
        return {"scope_id": scope_id, "permission_key": permission_key, "permission_value": permission_value, "id": perm_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.put("/{scope_id}/prompt-policy/{policy_key}")
async def set_prompt_policy(scope_id: str, policy_key: str, policy_value: str = "") -> dict:
    """更新作用域 Prompt 策略。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        dao = ScopeDAO(conn)
        policy_id = dao.set_prompt_policy(scope_id, policy_key, policy_value)
        return {"scope_id": scope_id, "policy_key": policy_key, "policy_value": policy_value, "id": policy_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()