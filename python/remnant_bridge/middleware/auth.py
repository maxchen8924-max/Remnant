"""Ephemeral Token 鉴权中间件。

在 Local-First 架构下，使用一次性的 ephemeral token 进行鉴权:
1. 应用启动时生成 token
2. Tauri 前端通过 IPC 获取 token
3. 每次 HTTP 请求携带 token 在 Authorization header 中
4. 中间件验证 token 有效性
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Mapping
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response

from remnant_bridge.config import TOKEN_EXPIRY_SECONDS, TOKEN_LENGTH


def _hash_token(token: str) -> str:
    """Hash a token value for in-memory comparison."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def extract_auth_token(headers: Mapping[str, str]) -> str | None:
    """Extract the sidecar token from supported request headers.

    `Authorization: Bearer` is used by the Rust bridge today. `X-Remnant-Token`
    is kept for compatibility with the whitepaper and API docs.
    """
    auth_header = headers.get("Authorization") or headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token or None

    legacy_header = (
        headers.get("X-Remnant-Token")
        or headers.get("x-remnant-token")
        or ""
    )
    legacy_token = legacy_header.strip()
    return legacy_token or None


class EphemeralTokenManager:
    """Ephemeral Token 管理器 — 生成和验证一次性 token。"""

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}  # token_hash -> expiry_time
        self._current_token: str = ""
        self._current_token_hash: str = ""
        self._external_token = False

        env_token = os.environ.get("REMNANT_AUTH_TOKEN", "").strip()
        if env_token:
            self._external_token = True
            self._store_token(env_token, expiry=float("inf"))
        else:
            self._generate_new_token()

    def _store_token(self, token: str, expiry: float | None = None) -> str:
        """Store a token by hashing its string representation."""
        self._current_token = token
        self._current_token_hash = _hash_token(token)
        self._tokens[self._current_token_hash] = (
            expiry if expiry is not None else time.time() + TOKEN_EXPIRY_SECONDS
        )
        return self._current_token

    def _generate_new_token(self) -> str:
        """生成新的 ephemeral token。"""
        token = os.urandom(TOKEN_LENGTH).hex()
        self._store_token(token)

        # 清理过期 token
        now = time.time()
        expired = [k for k, v in self._tokens.items() if v < now]
        for k in expired:
            del self._tokens[k]

        return self._current_token

    def get_current_token(self) -> str:
        """获取当前有效 token（供 IPC 桥接调用）。"""
        if self._external_token:
            return self._current_token

        # 检查当前 token 是否即将过期，提前刷新
        if self._current_token_hash not in self._tokens:
            self._generate_new_token()
        remaining = self._tokens.get(self._current_token_hash, 0) - time.time()
        if remaining < 300:  # 5 分钟内过期则刷新
            self._generate_new_token()
        return self._current_token

    def validate_token(self, token: str) -> bool:
        """验证 token 是否有效。

        Args:
            token: 待验证的 token 值

        Returns:
            True 如果有效且未过期
        """
        if not token:
            return False

        token_hash = _hash_token(token)
        expiry = self._tokens.get(token_hash)
        if expiry is None:
            return False
        if time.time() > expiry:
            del self._tokens[token_hash]
            return False
        return any(hmac.compare_digest(token_hash, stored) for stored in self._tokens)


class AuthMiddleware(BaseHTTPMiddleware):
    """Ephemeral Token 鉴权中间件。

    验证请求的 Authorization header 是否携带有效 token。
    跳过 /health 和 OPTIONS 请求。
    """

    def __init__(self, app: Any, token_manager: EphemeralTokenManager) -> None:
        super().__init__(app)
        self.token_manager = token_manager

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 跳过健康检查和 CORS 预检
        if request.url.path == "/health" or request.method == "OPTIONS":
            return await call_next(request)

        token = extract_auth_token(request.headers)
        if token is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization Bearer or X-Remnant-Token header"},
            )

        if not self.token_manager.validate_token(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        return await call_next(request)
