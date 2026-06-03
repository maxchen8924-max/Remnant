"""POST /api/v1/scope/create, delete, list, get — 关系作用域 API。

提供 Scope 的完整 CRUD 端点:
- POST /api/v1/scope/create — 创建作用域
- POST /api/v1/scope/delete — 删除作用域（软删除/硬删除）
- POST /api/v1/scope/soft-delete — 软删除（便捷端点）
- POST /api/v1/scope/hard-delete — 硬删除（便捷端点，需二次确认）
- GET /api/v1/scope/{scope_id} — 查询作用域详情
- GET /api/v1/scope/list/{deceased_profile_id} — 列出逝者下的所有作用域
- GET /api/v1/scope/{scope_id}/permissions — 查询权限配置
- GET /api/v1/scope/{scope_id}/safety-policy — 查询安全策略
- GET /api/v1/scope/{scope_id}/prompt-policies — 查询 Prompt 策略
- GET /api/v1/scope/{scope_id}/visibility — 查询可见 chunk 列表
- POST /api/v1/scope/{scope_id}/visibility/upgrade — 提升 chunk 可见性
- PUT /api/v1/scope/{scope_id}/permissions/{permission_key} — 更新权限
- PUT /api/v1/scope/{scope_id}/prompt-policy/{policy_key} — 更新 Prompt 策略
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from remnant_core.models import (
    ScopeCreateRequest,
    ScopeDeleteRequest,
)
from remnant_store.chunk_visibility import get_visible_chunk_ids
from remnant_store.db import get_connection
from remnant_store.scope_dao import ScopeDAO
from remnant_store.scope_deletion import hard_delete_scope, soft_delete_scope

router = APIRouter(prefix="/api/v1/scope", tags=["scope"])


# ==================== 便捷请求模型 ====================


class ScopeIdRequest(BaseModel):
    """仅包含 scope_id 的请求模型，用于便捷删除端点。"""
    scope_id: str = Field(description="关系作用域 ID")


class VisibilityUpgradeRequest(BaseModel):
    """chunk 可见性升级请求模型。"""
    scope_id: str = Field(description="关系作用域 ID")
    chunk_id: str = Field(description="需要提升可见性的 chunk ID")


# ==================== Helper ====================


def _get_db_conn():
    """获取数据库连接（非生成器版本，用于手动管理生命周期）。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    return get_connection(DEFAULT_DB_PATH)


# ==================== CRUD 端点 ====================


@router.post("/create")
async def create_scope(request: ScopeCreateRequest) -> dict:
    """创建关系作用域。"""
    conn = _get_db_conn()
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
    conn = _get_db_conn()
    try:
        if request.deletion_type.value == "scope_soft_delete":
            result = soft_delete_scope(conn, request.scope_id)
        elif request.deletion_type.value == "scope_hard_delete":
            if not request.confirm:
                raise HTTPException(status_code=400, detail="Hard delete requires confirm=true")
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


@router.post("/soft-delete")
async def soft_delete_scope_endpoint(request: ScopeIdRequest) -> dict:
    """软删除关系作用域（便捷端点）。

    标记 deleted_at，触发器自动级联到关联 scoped 数据。
    软删除后数据可通过硬删除彻底移除。
    """
    conn = _get_db_conn()
    try:
        result = soft_delete_scope(conn, request.scope_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Soft delete failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/hard-delete")
async def hard_delete_scope_endpoint(request: ScopeIdRequest) -> dict:
    """硬删除关系作用域（便捷端点）。

    **此操作不可逆！** 物理删除作用域及所有关联数据，
    敏感内容被标记为 REDACTED。仅保留审计日志和删除日志。
    """
    conn = _get_db_conn()
    try:
        result = hard_delete_scope(conn, request.scope_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Hard delete failed"))
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
    conn = _get_db_conn()
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
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        scopes = dao.list_scopes(deceased_profile_id)
        return {"scopes": scopes, "count": len(scopes)}
    finally:
        conn.close()


# ==================== 权限端点 ====================


@router.get("/{scope_id}/permissions")
async def get_permissions(scope_id: str) -> dict:
    """查询作用域权限配置。"""
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        permissions = dao.get_permissions(scope_id)
        return {"scope_id": scope_id, "permissions": permissions}
    finally:
        conn.close()


@router.put("/{scope_id}/permissions/{permission_key}")
async def set_permission(scope_id: str, permission_key: str, permission_value: str = "allow") -> dict:
    """更新作用域权限。"""
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        perm_id = dao.set_permission(scope_id, permission_key, permission_value)
        return {"scope_id": scope_id, "permission_key": permission_key, "permission_value": permission_value, "id": perm_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 安全策略端点 ====================


@router.get("/{scope_id}/safety-policy")
async def get_safety_policy(scope_id: str) -> dict:
    """查询作用域安全策略。"""
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        policy = dao.get_safety_policy(scope_id)
        if policy is None:
            raise HTTPException(status_code=404, detail=f"Safety policy for scope {scope_id} not found")
        return {"scope_id": scope_id, "safety_policy": policy}
    finally:
        conn.close()


# ==================== Prompt 策略端点 ====================


@router.get("/{scope_id}/prompt-policies")
async def get_prompt_policies(scope_id: str) -> dict:
    """查询作用域 Prompt 策略。"""
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        policies = dao.get_prompt_policies(scope_id)
        return {"scope_id": scope_id, "prompt_policies": policies}
    finally:
        conn.close()


@router.put("/{scope_id}/prompt-policy/{policy_key}")
async def set_prompt_policy(scope_id: str, policy_key: str, policy_value: str = "") -> dict:
    """更新作用域 Prompt 策略。"""
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        policy_id = dao.set_prompt_policy(scope_id, policy_key, policy_value)
        return {"scope_id": scope_id, "policy_key": policy_key, "policy_value": policy_value, "id": policy_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== Chunk 可见性端点 ====================


@router.get("/{scope_id}/visibility")
async def get_scope_visibility(scope_id: str) -> dict:
    """查询作用域可见的 chunk 列表。

    返回该 scope 下所有可见的 chunk ID 及其基本信息。
    """
    conn = _get_db_conn()
    try:
        # 先验证 scope 存在
        dao = ScopeDAO(conn)
        scope = dao.get_scope(scope_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Scope {scope_id} not found")

        # 获取可见 chunk ID
        visible_ids = get_visible_chunk_ids(conn, scope_id)
        if not visible_ids:
            return {"scope_id": scope_id, "visible_chunks": [], "count": 0}

        # 获取 chunk 详情
        placeholders = ",".join("?" * len(visible_ids))
        cursor = conn.execute(
            f"""SELECT id, source_artifact_id, relationship_scope_id, chunk_type,
                       content, token_count, status, created_at, updated_at
                FROM memory_chunk
                WHERE id IN ({placeholders}) AND deleted_at IS NULL
                ORDER BY created_at DESC""",
            list(visible_ids),
        )
        chunks = [dict(row) for row in cursor.fetchall()]

        # 获取每个 chunk 的可见性记录
        chunk_visibilities = []
        for chunk_id in visible_ids:
            vis_cursor = conn.execute(
                """SELECT id, chunk_id, relationship_scope_id, visibility, elevated_at, elevated_by_scope
                   FROM chunk_scope_visibility
                   WHERE chunk_id = ? AND relationship_scope_id = ?""",
                (chunk_id, scope_id),
            )
            vis_row = vis_cursor.fetchone()
            if vis_row:
                chunk_visibilities.append(dict(vis_row))

        return {
            "scope_id": scope_id,
            "visible_chunks": chunks,
            "visibility_records": chunk_visibilities,
            "count": len(chunks),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/{scope_id}/visibility/upgrade")
async def upgrade_chunk_visibility(scope_id: str, request: VisibilityUpgradeRequest) -> dict:
    """提升 chunk 可见性（scope_private -> scope_shared）。

    将指定 chunk 在该 scope 下从 scope_private 提升为 scope_shared，
    使其他授权 scope 也能访问该 chunk。需要 can_elevate_shared 权限。
    """
    conn = _get_db_conn()
    try:
        from datetime import datetime, timezone

        # 验证 scope 存在
        dao = ScopeDAO(conn)
        scope = dao.get_scope(scope_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Scope {scope_id} not found")

        # 验证 chunk 存在
        cursor = conn.execute(
            "SELECT id, status FROM memory_chunk WHERE id = ? AND deleted_at IS NULL",
            (request.chunk_id,),
        )
        chunk = cursor.fetchone()
        if chunk is None:
            raise HTTPException(status_code=404, detail=f"Chunk {request.chunk_id} not found")

        # 检查 can_elevate_shared 权限
        perm_value = dao.check_permission(scope_id, "can_elevate_shared")
        if perm_value == "deny":
            raise HTTPException(status_code=403, detail="Permission denied: can_elevate_shared is deny")

        # 检查是否已有可见性记录
        vis_cursor = conn.execute(
            """SELECT id, visibility FROM chunk_scope_visibility
               WHERE chunk_id = ? AND relationship_scope_id = ?""",
            (request.chunk_id, scope_id),
        )
        existing = vis_cursor.fetchone()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        if existing:
            # 更新现有记录
            conn.execute(
                """UPDATE chunk_scope_visibility
                   SET visibility = 'scope_shared', elevated_at = ?, elevated_by_scope = ?
                   WHERE chunk_id = ? AND relationship_scope_id = ?""",
                (now, scope_id, request.chunk_id, scope_id),
            )
        else:
            # 创建新记录
            vis_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO chunk_scope_visibility
                   (id, chunk_id, relationship_scope_id, visibility, elevated_at, elevated_by_scope, created_at)
                   VALUES (?, ?, ?, 'scope_shared', ?, ?, ?)""",
                (vis_id, request.chunk_id, scope_id, now, scope_id, now),
            )

        conn.commit()

        return {
            "scope_id": scope_id,
            "chunk_id": request.chunk_id,
            "visibility": "scope_shared",
            "elevated_at": now,
            "elevated_by_scope": scope_id,
            "status": "upgraded",
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()