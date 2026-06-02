"""配置常量 — 端口、重试等。"""

# 服务绑定配置
HOST: str = "127.0.0.1"
PORT: int = 18731

# Ephemeral Token 配置
TOKEN_LENGTH: int = 32
TOKEN_EXPIRY_SECONDS: int = 86400  # 24 小时

# 重试配置
MAX_RETRY_ATTEMPTS: int = 3
RETRY_DELAY_SECONDS: float = 1.0

# 数据库配置
DEFAULT_DB_PATH: str = ".remnant/data/remnant.db"
SQLCIPHER_KEY_ENV: str = "REMNANT_SQLCIPHER_KEY"

# 健康检查
HEALTH_CHECK_INTERVAL_SECONDS: int = 30

# 应用信息
APP_NAME: str = "Remnant"
APP_VERSION: str = "0.1.0"
APP_DESCRIPTION: str = "Local-First Digital Legacy Memory Runtime"