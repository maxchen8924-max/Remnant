"""FastAPI 入口 — 绑定 127.0.0.1:18731。

配置:
- ephemeral token 鉴权中间件
- 审计日志中间件
- 所有 API 路由
- /health 健康检查端点
- CORS 禁止（localhost only）
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from remnant_bridge.config import APP_DESCRIPTION, APP_NAME, APP_VERSION, HOST, PORT
from remnant_bridge.middleware.audit import AuditLogMiddleware
from remnant_bridge.middleware.auth import AuthMiddleware, EphemeralTokenManager
from remnant_bridge.routes import data_api, evidence_api, import_api, query_api, safety_api, scope_api

# 全局 Token 管理器
token_manager = EphemeralTokenManager()

# FastAPI 应用实例
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
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