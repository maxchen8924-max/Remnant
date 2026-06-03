"""审计日志中间件。

记录所有 API 请求到 audit_log 表:
- 请求方法、路径、状态码
- 请求和响应时间
- 关联的 relationship_scope_id（如果从请求中提取到）
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class AuditLogMiddleware(BaseHTTPMiddleware):
    """审计日志中间件 — 将所有 API 请求记录到 audit_log 表。"""

    def __init__(self, app: Any, db: Any = None) -> None:
        super().__init__(app)
        self.db = db

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # 尝试从请求中提取 scope_id
        scope_id = self._extract_scope_id(request)

        # 写入审计日志
        if self.db is not None:
            await self._write_audit_log(
                request=request,
                response=response,
                scope_id=scope_id,
                duration_ms=duration_ms,
            )

        # 添加处理时间 header
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        return response

    def _extract_scope_id(self, request: Request) -> str | None:
        """从请求中提取 relationship_scope_id。"""
        # 尝试从查询参数获取
        scope_id = request.query_params.get("scope_id")
        if scope_id:
            return scope_id

        # 尝试从路径参数获取
        path = request.url.path
        if "/scope/" in path:
            parts = path.split("/")
            for i, part in enumerate(parts):
                if part == "scope" and i + 1 < len(parts):
                    return parts[i + 1]

        return None

    async def _write_audit_log(
        self,
        request: Request,
        response: Response,
        scope_id: str | None,
        duration_ms: int,
    ) -> None:
        """写入审计日志记录。"""
        try:
            log_id = str(uuid.uuid4())
            action = f"{request.method}_{request.url.path}".upper()
            now = _utcnow_iso()

            self.db.execute(
                """INSERT INTO audit_log
                (id, relationship_scope_id, action, actor, target_type, target_id, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log_id,
                    scope_id,
                    action,
                    "user",
                    "api_request",
                    request.url.path,
                    f'{{"method": "{request.method}", "status": {response.status_code}, "duration_ms": {duration_ms}}}',
                    now,
                ),
            )
            self.db.commit()
        except Exception:
            # 审计日志写入失败不应阻塞请求
            pass


def _utcnow_iso() -> str:
    """获取当前 UTC 时间的 ISO 8601 格式字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
