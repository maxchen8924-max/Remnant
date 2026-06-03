"""Remnant CLI — 共享配置和工具函数。

从 cli.py 提取，避免循环导入。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

__all__ = ["get_base_url", "get_token", "DEFAULT_BASE_URL", "DEFAULT_CONFIG_DIR", "DEFAULT_TOKEN_FILE"]

# 默认配置路径
DEFAULT_CONFIG_DIR = Path.home() / ".remnant"
DEFAULT_TOKEN_FILE = DEFAULT_CONFIG_DIR / "token"
DEFAULT_BASE_URL = "http://127.0.0.1:18731"


def get_base_url() -> str:
    """获取 Remnant API 基础 URL。

    优先级: 环境变量 > 默认值

    Returns:
        API 基础 URL
    """
    return os.environ.get("REMNANT_API_URL", DEFAULT_BASE_URL)


def get_token(args: argparse.Namespace) -> str:
    """获取认证 token。

    优先级: 命令行参数 > 环境变量 > ~/.remnant/token 文件

    Args:
        args: 命令行参数命名空间

    Returns:
        认证 token 字符串

    Raises:
        SystemExit: 如果找不到 token
    """
    # 1. 命令行参数
    if hasattr(args, "token") and args.token:
        return args.token

    # 2. 环境变量
    env_token = os.environ.get("REMNANT_TOKEN")
    if env_token:
        return env_token

    # 3. ~/.remnant/token 文件
    if DEFAULT_TOKEN_FILE.exists():
        return DEFAULT_TOKEN_FILE.read_text().strip()

    print(
        "错误: 未找到认证 token。请通过以下方式之一提供:\n"
        "  1. 命令行参数 --token\n"
        "  2. 环境变量 REMNANT_TOKEN\n"
        "  3. 文件 ~/.remnant/token",
        file=sys.stderr,
    )
    sys.exit(1)