"""安全评估 API — Ch10 完整端点。

提供:
- POST /api/v1/safety/evaluate — 完整8指标采集 + 评估
- GET /api/v1/safety/policy/{scope_id} — 获取安全策略
- PUT /api/v1/safety/policy/{scope_id} — 更新安全策略
- GET /api/v1/safety/events/{scope_id} — 获取安全事件历史
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from remnant_core.models import SafetyAction, SafetyDirective, SafetyIndicators
from remnant_policy.safety import collect_safety_indicators, evaluate_safety, handle_directive
from remnant_store.scope_dao import ScopeDAO
from remnant_store.schema import init_db

router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


# ==================== 请求/响应模型 ====================


class SafetyEvaluateRequest(BaseModel):
    """安全评估请求模型。"""
    scope_id: str = Field(description="关系作用域 ID")
    session_id: str = Field(description="当前会话 ID")
    current_query: str = Field(default="", description="当前用户查询文本")
    session_stats: dict[str, Any] | None = Field(default=None, description="可选的会话统计附加数据")


class SafetyEvaluateResponse(BaseModel):
    """安全评估响应模型。"""
    directive: SafetyDirective = Field(description="安全指令")
    indicators: SafetyIndicators = Field(description="8项安全指标")
    proceed: bool = Field(description="是否允许继续")
    pre_response: str | None = Field(default=None, description="软熔断时的前置回复")
    response_text: str | None = Field(default=None, description="硬熔断/升级时的完整回复")


class SafetyPolicyUpdateRequest(BaseModel):
    """安全策略更新请求模型。"""
    max_session_minutes: int | None = Field(default=None, description="单次会话最大时长（分钟）")
    max_sessions_daily: int | None = Field(default=None, description="每日最大会话数")
    late_night_start: str | None = Field(default=None, description="深夜时段开始")
    late_night_end: str | None = Field(default=None, description="深夜时段结束")
    max_late_night_sessions: int | None = Field(default=None, description="深夜最大会话数")
    dependency_threshold: float | None = Field(default=None, description="情绪依赖阈值")
    farewell_refusal_limit: int | None = Field(default=None, description="拒绝结束次数上限")
    hard_break_enabled: bool | None = Field(default=None, description="是否允许硬熔断")
    cooldown_minutes: int | None = Field(default=None, description="冷却期分钟数")
    escalate_on_crisis: bool | None = Field(default=None, description="危机表达是否触发升级")


# ==================== Helper ====================


def _get_db_conn() -> sqlite3.Connection:
    """获取数据库连接（非生成器版本，用于手动管理生命周期）。"""
    from remnant_bridge.config import DEFAULT_DB_PATH
    return init_db(DEFAULT_DB_PATH)


# ==================== 端点 ====================


@router.post("/evaluate")
async def evaluate_safety_endpoint(request: SafetyEvaluateRequest) -> dict:
    """完整8指标采集 + 评估 — 对应白皮书 Ch10 核心流程。

    请求体:
    - scope_id: 关系作用域 ID
    - session_id: 当前会话 ID
    - current_query: 当前用户查询文本
    - session_stats: 可选的会话统计附加数据
    """
    conn = _get_db_conn()
    try:
        # 验证 scope 存在
        dao = ScopeDAO(conn)
        scope = dao.get_scope(request.scope_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Scope {request.scope_id} not found")

        # 采集安全指标
        indicators = collect_safety_indicators(
            conn=conn,
            scope_id=request.scope_id,
            session_id=request.session_id,
            current_query=request.current_query,
            session_stats=request.session_stats,
        )

        # 获取安全策略
        policy = dao.get_safety_policy(request.scope_id)
        policy_dict = dict(policy) if policy else {}

        # 评估安全
        directive = evaluate_safety(
            indicators=indicators,
            safety_policy=policy_dict,
            current_query=request.current_query,
        )

        # 处理指令（入库 + 会话管理）
        result = handle_directive(
            conn=conn,
            scope_id=request.scope_id,
            directive=directive,
            session_id=request.session_id,
        )

        return {
            "directive": directive.model_dump(),
            "indicators": indicators.model_dump(),
            "proceed": result["proceed"],
            "pre_response": result.get("pre_response"),
            "response_text": result.get("response_text"),
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/policy/{scope_id}")
async def get_safety_policy(scope_id: str) -> dict:
    """获取安全策略 — 从 scope_safety_policy 表读取。"""
    conn = _get_db_conn()
    try:
        dao = ScopeDAO(conn)
        policy = dao.get_safety_policy(scope_id)
        if policy is None:
            raise HTTPException(
                status_code=404,
                detail=f"Safety policy for scope {scope_id} not found",
            )
        return {"scope_id": scope_id, "safety_policy": dict(policy)}
    finally:
        conn.close()


@router.put("/policy/{scope_id}")
async def update_safety_policy(scope_id: str, request: SafetyPolicyUpdateRequest) -> dict:
    """更新安全策略 — 更新 scope_safety_policy 表中指定字段。"""
    conn = _get_db_conn()
    try:
        # 验证 scope 存在
        dao = ScopeDAO(conn)
        scope = dao.get_scope(scope_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Scope {scope_id} not found")

        # 验证安全策略存在
        policy = dao.get_safety_policy(scope_id)
        if policy is None:
            raise HTTPException(
                status_code=404,
                detail=f"Safety policy for scope {scope_id} not found",
            )

        # 构建更新字段
        updates: dict[str, Any] = {}
        field_map = {
            "max_session_minutes": request.max_session_minutes,
            "max_sessions_daily": request.max_sessions_daily,
            "late_night_start": request.late_night_start,
            "late_night_end": request.late_night_end,
            "max_late_night_sessions": request.max_late_night_sessions,
            "dependency_threshold": request.dependency_threshold,
            "farewell_refusal_limit": request.farewell_refusal_limit,
            "hard_break_enabled": request.hard_break_enabled,
            "cooldown_minutes": request.cooldown_minutes,
            "escalate_on_crisis": request.escalate_on_crisis,
        }

        for col, val in field_map.items():
            if val is not None:
                updates[col] = val

        if updates:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            updates["updated_at"] = now

            set_clauses = ", ".join(f"{col} = ?" for col in updates.keys())
            values = list(updates.values()) + [scope_id]

            conn.execute(
                f"UPDATE scope_safety_policy SET {set_clauses} WHERE relationship_scope_id = ?",
                values,
            )
            conn.commit()

        # 返回更新后的策略
        updated_policy = dao.get_safety_policy(scope_id)
        return {"scope_id": scope_id, "safety_policy": dict(updated_policy)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/events/{scope_id}")
async def get_safety_events(scope_id: str, days: int = 7) -> dict:
    """获取安全事件历史 — 从 safety_event 表查询最近 N 天事件。

    Args:
        scope_id: 关系作用域 ID
        days: 查询最近多少天的事件，默认7天
    """
    conn = _get_db_conn()
    try:
        # 验证 scope 存在
        dao = ScopeDAO(conn)
        scope = dao.get_scope(scope_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Scope {scope_id} not found")

        from datetime import datetime, timezone, timedelta

        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

        cursor = conn.execute(
            """SELECT id, relationship_scope_id, event_type, severity,
                      description, trigger_data, action_taken, resolved_at, metadata, created_at
               FROM safety_event
               WHERE relationship_scope_id = ? AND created_at >= ?
               ORDER BY created_at DESC""",
            (scope_id, since),
        )
        events = [dict(row) for row in cursor.fetchall()]

        return {
            "scope_id": scope_id,
            "events": events,
            "count": len(events),
            "days": days,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
