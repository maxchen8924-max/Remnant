"""remnant query — 查询子命令。

调用 POST /api/v1/query 执行记忆查询，支持 SSE 流式输出。
"""

from __future__ import annotations

import json
import sys
from typing import Optional

import httpx
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from ..cli import get_base_url, get_token

console = Console()


def add_query_parser(subparsers) -> None:
    """注册 query 子命令到 argparse。"""
    parser = subparsers.add_parser(
        "query",
        help="执行记忆查询",
        description="向 Remnant 发起记忆查询，返回 Claim-level 响应（支持 SSE 流式）。",
    )
    parser.add_argument(
        "--scope", "-s",
        required=True,
        help="关系作用域 ID (scope_id)",
    )
    parser.add_argument(
        "--text", "-t",
        required=True,
        help="查询文本",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="逝者档案 ID (deceased_profile_id)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="会话 ID (session_id)，不指定则自动创建",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="检索 top-K 结果数 (默认: 10)",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        default=False,
        help="禁用 rerank",
    )
    parser.set_defaults(func=handle_query)


def handle_query(args) -> None:
    """处理 query 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/query"

    payload: dict = {
        "scope_id": args.scope,
        "query": args.text,
        "options": {
            "top_k": args.top_k,
            "rerank": not args.no_rerank,
        },
    }
    if args.profile:
        payload["deceased_profile_id"] = args.profile
    if args.session:
        payload["session_id"] = args.session

    headers = {
        "X-Remnant-Token": token,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    try:
        with httpx.Client(timeout=120.0) as client:
            if args.json:
                # 非 SSE 模式，获取完整 JSON 响应
                headers["Accept"] = "application/json"
                response = client.post(url, json=payload, headers=headers)
                data = response.json()
                console.print_json(json.dumps(data, ensure_ascii=False, indent=2))
                return

            # SSE 流式模式
            collected_text = ""
            claims = []
            with client.stream("POST", url, json=payload, headers=headers) as response:
                console.print("[dim]正在查询...[/dim]\n")
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        try:
                            event_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if event_type == "safety_check":
                            level = event_data.get("level", "")
                            action = event_data.get("action", "")
                            buf = event_data.get("buffer_text", "")
                            console.print(f"[yellow]安全检查: level={level}, action={action}[/yellow]")
                            if buf:
                                collected_text = buf

                        elif event_type == "retrieval_done":
                            chunk_count = event_data.get("chunk_count", 0)
                            evidence_count = event_data.get("evidence_count", 0)
                            console.print(f"[dim]检索完成: {chunk_count} 个 chunk, {evidence_count} 条证据[/dim]\n")

                        elif event_type == "token":
                            collected_text += event_data.get("text", "")

                        elif event_type == "claims":
                            claims = event_data.get("claims", [])

                        elif event_type == "unsupported":
                            unsupported = event_data.get("unsupported_claims", [])
                            if unsupported:
                                console.print("\n[yellow]以下内容因证据不足已被移除:[/yellow]")
                                for uc in unsupported:
                                    console.print(f"  [dim]- {uc.get('claim_text', '')}[/dim]")

                        elif event_type == "audit":
                            scope_id = event_data.get("scope_id", "")
                            dur = event_data.get("duration_ms", 0)
                            console.print(f"\n[dim]审计: scope={scope_id}, 耗时={dur}ms[/dim]")

                        elif event_type == "done":
                            break

            # 显示最终响应
            console.print()
            console.print(Panel(Markdown(collected_text), title="回答", border_style="green"))

            # 显示 claims 表格
            if claims:
                table = Table(title="Claims")
                table.add_column("ID", style="dim", width=10)
                table.add_column("类型", width=20)
                table.add_column("支撑状态", width=20)
                table.add_column("内容", width=50)
                table.add_column("置信度", width=10)

                for c in claims:
                    table.add_row(
                        c.get("claim_id", "")[:8],
                        c.get("claim_type", ""),
                        c.get("support_status", ""),
                        c.get("claim_text", "")[:50] + ("..." if len(c.get("claim_text", "")) > 50 else ""),
                        f"{c.get('confidence_score', 0):.2f}",
                    )
                console.print(table)

    except httpx.ConnectError:
        console.print("[red]错误: 无法连接到 Remnant 服务，请确认服务已启动[/red]")
        sys.exit(1)