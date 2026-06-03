"""Remnant CLI — 主入口。

命令行管理工具，支持完整流程：导入 → 索引 → 查询 → 查看 claim → 查看 evidence
→ scope 管理 → 安全策略查看 → 审计日志。

用法:
    remnant import --file <path> --profile <id> --scope <id> --type <wechat_txt|diary|email>
    remnant query --scope <id> --text <query>
    remnant scope list --profile <id>
    remnant scope create --profile <id> --name <name> --type <spouse|child|...>
    remnant scope show <scope_id>
    remnant scope delete <scope_id> [--hard]
    remnant safety evaluate --scope <id> --query <text>
    remnant safety policy <scope_id>
    remnant audit list --scope <id> [--limit 20]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .commands.import_cmd import add_import_parser
from .commands.query_cmd import add_query_parser
from .commands.scope_cmd import add_scope_parser
from .commands.safety_cmd import add_safety_parser
from .commands.audit_cmd import add_audit_parser
from .config import get_base_url, get_token  # noqa: F401 — re-export for backward compat

__all__ = ["main", "get_base_url", "get_token"]


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="remnant",
        description="Remnant — Local-First 数字遗产记忆运行时 CLI",
        epilog="使用 'remnant <command> --help' 查看子命令帮助",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    parser.add_argument(
        "--token",
        help="认证 token（也可通过环境变量 REMNANT_TOKEN 或 ~/.remnant/token 提供）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="以 JSON 格式输出",
    )

    # 注册子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    add_import_parser(subparsers)
    add_query_parser(subparsers)
    add_scope_parser(subparsers)
    add_safety_parser(subparsers)
    add_audit_parser(subparsers)

    return parser


def _get_version() -> str:
    """获取 CLI 版本号。"""
    try:
        from . import __version__
        return __version__
    except ImportError:
        return "0.1.0"


def main() -> None:
    """CLI 主入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if not hasattr(args, "func"):
        # 子命令没有进一步 action（如 scope, safety）
        parser.parse_args([args.command, "--help"])
        sys.exit(0)

    try:
        args.func(args)
    except KeyboardInterrupt:
        console_print("\n[yellow]操作已取消[/yellow]")
        sys.exit(130)
    except Exception as e:
        from rich.console import Console
        console = Console()
        console.print(f"[red]错误: {e}[/red]")
        sys.exit(1)


def console_print(msg: str) -> None:
    """简单控制台打印（main 中使用）。"""
    from rich.console import Console
    Console().print(msg)


if __name__ == "__main__":
    main()