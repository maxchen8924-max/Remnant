"""pytest fixtures — 数据库连接 fixture、FastAPI client fixture。

注意: FastAPI/Pydantic 相关 fixture 在 macOS 沙盒环境下可能因
pydantic_core 二进制签名问题而不可用。schema 测试不需要这些 fixture。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Generator

import pytest

from remnant_store.schema import init_db


@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """内存数据库 fixture — 每个测试用例获得独立的内存数据库。"""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path: Any) -> str:
    """临时数据库文件路径 fixture。"""
    return str(tmp_path / "test_remnant.db")


@pytest.fixture
def file_db(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """文件数据库 fixture — 使用临时文件。"""
    conn = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def token_manager():
    """Token 管理器 fixture — 延迟导入以避免 pydantic_core 加载问题。"""
    from remnant_bridge.middleware.auth import EphemeralTokenManager

    return EphemeralTokenManager()


@pytest.fixture
def client(token_manager):
    """FastAPI 测试客户端 fixture — 延迟导入以避免签名问题。"""
    try:
        from fastapi.testclient import TestClient
        from remnant_bridge.main import app

        # 更新 main 中的 token_manager
        from remnant_bridge import main as main_module
        main_module.token_manager = token_manager

        # 更新中间件中的 token_manager
        for middleware in app.user_middleware:
            if hasattr(middleware, "cls") and middleware.cls.__name__ == "AuthMiddleware":
                middleware.kwargs["token_manager"] = token_manager

        test_client = TestClient(app)

        # 注入有效 token 到请求头
        valid_token = token_manager.get_current_token()
        test_client.headers.update({"Authorization": f"Bearer {valid_token}"})

        return test_client
    except ImportError:
        pytest.skip("pydantic_core binary not available in this environment")