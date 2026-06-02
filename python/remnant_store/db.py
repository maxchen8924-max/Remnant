"""数据库连接管理 — 支持 SQLite 和 SQLCipher。

提供统一的数据库连接获取接口:
- SQLite 普通模式（开发用）
- SQLCipher 加密模式（生产用）
- 连接池管理
- PRAGMA 配置
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def get_connection(
    db_path: str | Path,
    sqlcipher_key: str | None = None,
    pragmas: dict[str, Any] | None = None,
) -> sqlite3.Connection:
    """获取数据库连接。

    Args:
        db_path: 数据库文件路径
        sqlcipher_key: SQLCipher 加密密钥（None 则使用普通 SQLite）
        pragmas: 自定义 PRAGMA 配置

    Returns:
        配置好的 sqlite3.Connection
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if sqlcipher_key is not None:
        # 尝试使用 SQLCipher
        try:
            from sqlcipher3 import dbapi2 as sqlite_cipher  # type: ignore[import-untyped]

            conn = sqlite_cipher.connect(str(db_path))
            conn.execute(f"PRAGMA key = '{sqlcipher_key}'")
        except ImportError:
            import warnings

            warnings.warn(
                "sqlcipher3 未安装，回退到普通 SQLite。"
                "生产环境请安装 sqlcipher3 以启用加密。",
                stacklevel=2,
            )
            conn = sqlite3.connect(str(db_path))
    else:
        conn = sqlite3.connect(str(db_path))

    # 默认 PRAGMA 配置
    default_pragmas = {
        "journal_mode": "WAL",
        "foreign_keys": "ON",
        "recursive_triggers": "ON",
        "busy_timeout": 5000,
        "synchronous": "NORMAL",
    }

    # 合并自定义 PRAGMA
    final_pragmas = {**default_pragmas, **(pragmas or {})}

    for key, value in final_pragmas.items():
        conn.execute(f"PRAGMA {key} = {value}")

    # 启用 WAL 模式后需再次设置（WAL 需要特殊处理）
    conn.execute("PRAGMA journal_mode = WAL")

    conn.row_factory = sqlite3.Row
    return conn


def close_connection(conn: sqlite3.Connection) -> None:
    """安全关闭数据库连接。

    Args:
        conn: 要关闭的数据库连接
    """
    try:
        conn.close()
    except Exception:
        pass