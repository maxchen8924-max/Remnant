"""FastAPI 入口 — 绑定 127.0.0.1:18731。

配置:
- ephemeral token 鉴权中间件
- 审计日志中间件
- 所有 API 路由
- /health 健康检查端点
- CORS 禁止（localhost only）
"""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from remnant_bridge.config import APP_DESCRIPTION, APP_NAME, APP_VERSION, HOST, PORT
from remnant_bridge.middleware.audit import AuditLogMiddleware
from remnant_bridge.middleware.auth import AuthMiddleware, EphemeralTokenManager
from remnant_bridge.routes import (
    data_api,
    evidence_api,
    import_api,
    profile_api,
    query_api,
    safety_api,
    scope_api,
)

# 全局 Token 管理器
token_manager = EphemeralTokenManager()

# FastAPI 应用实例
# 安全考虑：默认关闭 Swagger UI 和 ReDoc（白皮书 Ch11 要求 localhost 访问限制）
# 开发环境可通过 REMNANT_ENABLE_DOCS=1 环境变量开启
import os
_enable_docs = os.environ.get("REMNANT_ENABLE_DOCS", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
)

# CORS 禁止 — localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 鉴权中间件
app.add_middleware(AuthMiddleware, token_manager=token_manager)

# 审计日志中间件
app.add_middleware(AuditLogMiddleware)

# 注册路由
app.include_router(import_api.router)
app.include_router(query_api.router)
app.include_router(profile_api.router)
app.include_router(scope_api.router)
app.include_router(evidence_api.router)
app.include_router(safety_api.router)
app.include_router(data_api.router)


@app.get("/health")
async def health_check() -> dict:
    """健康检查端点。"""
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
    }


def run_server() -> None:
    """启动服务器入口。"""
    uvicorn.run(
        "remnant_bridge.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
