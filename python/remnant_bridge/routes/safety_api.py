"""POST /api/v1/safety/evaluate — 安全评估 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from remnant_core.models import SafetyDirective

router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


@router.post("/evaluate")
async def evaluate_safety(request: dict[str, Any]) -> dict:
    """评估当前交互的安全性。

    请求体应包含:
    - query: 用户查询文本
    - response_text: AI 响应文本
    - scope_id: 关系作用域 ID
    - session_stats: 会话统计（可选）
    """
    # M1 阶段调用 SafetyMiddleware.evaluate
    return {"safe": True, "directive": None}