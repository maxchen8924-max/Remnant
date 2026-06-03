"""remnant audit — 审计日志子命令。

支持查看审计日志列表。
"""

from __future__ import annotations

import json
import sys
from typing import Optional

import httpx
from rich.console import Console
from rich.table import Table

from ..config import get_base_url, get_token

console = Console()


def add_audit_parser(subparsers) -> None:
    """注册 audit 子命令到 argparse。"""
    parser = subparsers.add_parser(
        "audit",
        help="查看审计日志",
        description="查看系统审计日志，记录所有数据操作和安全事件。",
    )
    audit_sub = parser.add_subparsers(dest="audit_action", help="audit 操作")

    # audit list
    list_parser = audit_sub.add_parser("list", help="列出审计日志")
    list_parser.add_argument(
        "--scope", "-s",
        required=True,
        help="作用域 ID",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="返回条数限制 (默认: 20)",
    )
    list_parser.set_defaults(func=handle_audit_list)


def handle_audit_list(args) -> None:
    """处理 audit list 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/safety/events/{args.scope}"
    params = {"limit": args.limit}
    headers = {"X-Remnant-Token": token}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params, headers=headers)
    except httpx.ConnectError:
        console.print("[red]错误: 无法连接到 Remnant 服务[/red]")
        sys.exit(1)

    data = response.json()

    if args.json:
        console.print_json(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if data.get("code") != 0:
        console.print(f"[red]查询失败: {data.get('message', '未知错误')}[/red]")
        sys.exit(1)

    events = data.get("data", {}).get("events", [])
    if not events:
        console.print("[yellow]未找到审计日志[/yellow]")
        return

    table = Table(title="审计日志")
    table.add_column("时间", width=20)
    table.add_column("动作", style="cyan", width=18)
    table.add_column("级别", width=10)
    table.add_column("详情", width=50)

    for e in events[: args.limit]:
        detail = e.get("detail", "")
        if len(detail) > 50:
            detail = detail[:47] + "..."
        table.add_row(
            e.get("created_at", "")[:19],
            e.get("action", ""),
            e.get("level", ""),
            detail,
        )

    console.print(table)