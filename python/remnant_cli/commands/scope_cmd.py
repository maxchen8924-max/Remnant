"""remnant scope — 作用域管理子命令。

支持 scope 的创建、查看、列表、删除等操作。
"""

from __future__ import annotations

import json
import sys
from typing import Optional

import httpx
from rich.console import Console
from rich.table import Table

from ..cli import get_base_url, get_token

console = Console()


def add_scope_parser(subparsers) -> None:
    """注册 scope 子命令到 argparse。"""
    parser = subparsers.add_parser(
        "scope",
        help="管理关系作用域",
        description="创建、查看、列出、删除关系作用域（scope）。",
    )
    scope_sub = parser.add_subparsers(dest="scope_action", help="scope 操作")

    # scope list
    list_parser = scope_sub.add_parser("list", help="列出作用域")
    list_parser.add_argument(
        "--profile", "-p",
        required=True,
        help="逝者档案 ID (deceased_profile_id)",
    )
    list_parser.set_defaults(func=handle_scope_list)

    # scope create
    create_parser = scope_sub.add_parser("create", help="创建作用域")
    create_parser.add_argument(
        "--profile", "-p",
        required=True,
        help="逝者档案 ID (deceased_profile_id)",
    )
    create_parser.add_argument(
        "--name", "-n",
        required=True,
        help="作用域名称（如：作为儿子）",
    )
    create_parser.add_argument(
        "--type", "-t",
        required=True,
        choices=["spouse", "child", "parent", "sibling", "friend", "colleague", "other"],
        help="关系类型",
    )
    create_parser.add_argument(
        "--description", "-d",
        default="",
        help="作用域描述",
    )
    create_parser.set_defaults(func=handle_scope_create)

    # scope show
    show_parser = scope_sub.add_parser("show", help="查看作用域详情")
    show_parser.add_argument(
        "scope_id",
        help="作用域 ID",
    )
    show_parser.set_defaults(func=handle_scope_show)

    # scope delete
    delete_parser = scope_sub.add_parser("delete", help="删除作用域")
    delete_parser.add_argument(
        "scope_id",
        help="作用域 ID",
    )
    delete_parser.add_argument(
        "--hard",
        action="store_true",
        default=False,
        help="硬删除（不可逆）",
    )
    delete_parser.add_argument(
        "--reason",
        default="",
        help="删除原因",
    )
    delete_parser.set_defaults(func=handle_scope_delete)


def handle_scope_list(args) -> None:
    """处理 scope list 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/scope"
    params = {"deceased_profile_id": args.profile}
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

    scopes = data.get("data", {}).get("scopes", [])
    if not scopes:
        console.print("[yellow]未找到任何作用域[/yellow]")
        return

    table = Table(title="关系作用域列表")
    table.add_column("Scope ID", style="dim", width=38)
    table.add_column("名称", style="cyan")
    table.add_column("关系类型")
    table.add_column("活跃", width=6)
    table.add_column("创建时间")

    for s in scopes:
        table.add_row(
            s.get("scope_id", ""),
            s.get("scope_name", ""),
            s.get("relationship_type", ""),
            "✓" if s.get("is_active", False) else "✗",
            s.get("created_at", "")[:19],
        )

    console.print(table)


def handle_scope_create(args) -> None:
    """处理 scope create 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/scope/create"
    payload = {
        "deceased_profile_id": args.profile,
        "scope_name": args.name,
        "relationship_type": args.type,
        "scope_description": args.description,
        "initial_permissions": {
            "can_query_memory": "allow",
            "can_browse_original": "ask",
            "can_add_oral_history": "allow",
            "can_view_financial": "deny",
            "can_view_medical": "deny",
            "can_view_intimate": "deny",
        },
    }
    headers = {
        "X-Remnant-Token": token,
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.ConnectError:
        console.print("[red]错误: 无法连接到 Remnant 服务[/red]")
        sys.exit(1)

    data = response.json()

    if args.json:
        console.print_json(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if data.get("code") != 0:
        console.print(f"[red]创建失败: {data.get('message', '未知错误')}[/red]")
        sys.exit(1)

    result = data.get("data", {})
    console.print("[green]作用域创建成功！[/green]")
    table = Table(title="作用域详情")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")
    table.add_row("Scope ID", result.get("scope_id", ""))
    table.add_row("逝者档案 ID", result.get("deceased_profile_id", ""))
    table.add_row("名称", result.get("scope_name", ""))
    table.add_row("关系类型", result.get("relationship_type", ""))
    table.add_row("活跃", "✓" if result.get("is_active") else "✗")
    table.add_row("创建时间", result.get("created_at", "")[:19])
    console.print(table)


def handle_scope_show(args) -> None:
    """处理 scope show 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/scope/{args.scope_id}"
    headers = {"X-Remnant-Token": token}

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
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

    result = data.get("data", {})
    table = Table(title=f"作用域: {result.get('scope_name', '')}")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")

    table.add_row("Scope ID", result.get("scope_id", ""))
    table.add_row("逝者档案 ID", result.get("deceased_profile_id", ""))
    table.add_row("名称", result.get("scope_name", ""))
    table.add_row("关系类型", result.get("relationship_type", ""))
    table.add_row("描述", result.get("scope_description", ""))
    table.add_row("活跃", "✓" if result.get("is_active") else "✗")
    table.add_row("创建时间", result.get("created_at", "")[:19])

    # 权限信息
    permissions = result.get("permissions", {})
    if permissions:
        console.print()
        perm_table = Table(title="权限配置")
        perm_table.add_column("权限", style="cyan")
        perm_table.add_column("值")
        for key, value in permissions.items():
            perm_table.add_row(key, str(value))
        console.print(perm_table)

    console.print(table)


def handle_scope_delete(args) -> None:
    """处理 scope delete 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    deletion_type = "scope_hard_delete" if args.hard else "scope_soft_delete"

    # 先获取 confirmation token
    confirm_url = f"{base_url}/api/v1/scope/confirm_delete/{args.scope_id}"
    headers = {"X-Remnant-Token": token}

    try:
        with httpx.Client(timeout=30.0) as client:
            confirm_resp = client.get(confirm_url, headers=headers)
            confirm_data = confirm_resp.json()
            if confirm_data.get("code") != 0:
                console.print(f"[red]获取确认令牌失败: {confirm_data.get('message', '')}[/red]")
                sys.exit(1)
            confirmation_token = confirm_data.get("data", {}).get("confirmation_token", "")
    except httpx.ConnectError:
        console.print("[red]错误: 无法连接到 Remnant 服务[/red]")
        sys.exit(1)

    url = f"{base_url}/api/v1/scope/delete"
    payload = {
        "scope_id": args.scope_id,
        "deletion_type": deletion_type,
        "confirmation_token": confirmation_token,
    }
    if args.reason:
        payload["reason"] = args.reason

    headers["Content-Type"] = "application/json"

    console.print(f"[yellow]警告: 正在执行{'硬删除' if args.hard else '软删除'}...[/yellow]")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.ConnectError:
        console.print("[red]错误: 无法连接到 Remnant 服务[/red]")
        sys.exit(1)

    data = response.json()

    if args.json:
        console.print_json(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if data.get("code") != 0:
        console.print(f"[red]删除失败: {data.get('message', '未知错误')}[/red]")
        sys.exit(1)

    result = data.get("data", {})
    console.print(f"[green]作用域已{'硬删除' if args.hard else '软删除'}[/green]")
    table = Table(title="删除结果")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")
    table.add_row("Scope ID", result.get("scope_id", ""))
    table.add_row("删除类型", result.get("deletion_type", ""))
    table.add_row("影响行数", str(result.get("affected_rows", "")))
    table.add_row("完成时间", result.get("completed_at", "")[:19])
    console.print(table)