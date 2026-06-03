"""remnant import — 数据导入子命令。

调用 POST /api/v1/import 启动数据导入任务。
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


def add_import_parser(subparsers) -> None:
    """注册 import 子命令到 argparse。"""
    parser = subparsers.add_parser(
        "import",
        help="导入数据文件到 Remnant",
        description="启动数据导入任务，支持微信聊天记录、日记、邮件等格式。",
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="要导入的文件路径",
    )
    parser.add_argument(
        "--profile", "-p",
        required=True,
        help="逝者档案 ID (deceased_profile_id)",
    )
    parser.add_argument(
        "--scope", "-s",
        required=True,
        help="关系作用域 ID (scope_id)",
    )
    parser.add_argument(
        "--type", "-t",
        choices=["wechat_txt", "diary", "email"],
        default="wechat_txt",
        help="数据来源类型 (默认: wechat_txt)",
    )
    parser.add_argument(
        "--encoding",
        default="auto",
        help="文件编码 (默认: auto 自动检测)",
    )
    parser.add_argument(
        "--skip-system",
        action="store_true",
        default=True,
        help="跳过系统消息 (默认: True)",
    )
    parser.add_argument(
        "--skip-recall",
        action="store_true",
        default=True,
        help="跳过撤回消息 (默认: True)",
    )
    parser.add_argument(
        "--consent",
        default="用户手动授权",
        help="数据来源授权声明",
    )
    parser.set_defaults(func=handle_import)


def handle_import(args) -> None:
    """处理 import 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/import"

    payload: dict = {
        "deceased_profile_id": args.profile,
        "scope_id": args.scope,
        "source_type": args.type,
        "file_path": args.file,
        "encoding": args.encoding,
        "import_options": {
            "skip_system_message": args.skip_system,
            "skip_recall_message": args.skip_recall,
            "consent_categories": ["raw_text"],
            "consent_evidence": args.consent,
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
        console.print("[red]错误: 无法连接到 Remnant 服务，请确认服务已启动[/red]")
        sys.exit(1)

    data = response.json()

    if args.json:
        console.print_json(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if data.get("code") != 0:
        console.print(f"[red]导入失败: {data.get('message', '未知错误')}[/red]")
        sys.exit(1)

    result = data.get("data", {})
    table = Table(title="导入任务已创建")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")

    table.add_row("Job ID", result.get("job_id", "N/A"))
    table.add_row("状态", result.get("status", "N/A"))
    table.add_row("Source Artifact ID", result.get("source_artifact_id", "N/A"))
    table.add_row("文件哈希", result.get("file_hash", "N/A"))
    table.add_row("预估耗时", f"{result.get('estimated_duration_seconds', 'N/A')} 秒")

    console.print(table)