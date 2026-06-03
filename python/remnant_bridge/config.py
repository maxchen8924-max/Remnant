"""配置常量 — 端口、重试等。"""

from __future__ import annotations

import os


def _get_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

# 服务绑定配置
HOST: str = os.environ.get("REMNANT_SIDECAR_HOST", "127.0.0.1")
PORT: int = _get_int_env("REMNANT_SIDECAR_PORT", 18731)

# Ephemeral Token 配置
TOKEN_LENGTH: int = 32
TOKEN_EXPIRY_SECONDS: int = 86400  # 24 小时

# 重试配置
MAX_RETRY_ATTEMPTS: int = 3
RETRY_DELAY_SECONDS: float = 1.0

# 数据库配置
DEFAULT_DB_PATH: str = os.environ.get("REMNANT_DB_PATH", ".remnant/data/remnant.db")
SQLCIPHER_KEY_ENV: str = "REMNANT_SQLCIPHER_KEY"

# 健康检查
HEALTH_CHECK_INTERVAL_SECONDS: int = 30

# 应用信息
APP_NAME: str = "Remnant"
APP_VERSION: str = "0.1.0"
APP_DESCRIPTION: str = "Local-First Digital Legacy Memory Runtime"
