"""remnant safety — 安全策略子命令。

支持安全评估和策略查看。
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


def add_safety_parser(subparsers) -> None:
    """注册 safety 子命令到 argparse。"""
    parser = subparsers.add_parser(
        "safety",
        help="安全策略管理",
        description="查看安全策略和触发安全评估。",
    )
    safety_sub = parser.add_subparsers(dest="safety_action", help="safety 操作")

    # safety evaluate
    eval_parser = safety_sub.add_parser("evaluate", help="执行安全评估")
    eval_parser.add_argument(
        "--scope", "-s",
        required=True,
        help="关系作用域 ID (scope_id)",
    )
    eval_parser.add_argument(
        "--query", "-q",
        required=True,
        help="当前查询文本",
    )
    eval_parser.add_argument(
        "--session",
        default=None,
        help="会话 ID (session_id)",
    )
    eval_parser.set_defaults(func=handle_safety_evaluate)

    # safety policy
    policy_parser = safety_sub.add_parser("policy", help="查看安全策略")
    policy_parser.add_argument(
        "scope_id",
        help="作用域 ID",
    )
    policy_parser.set_defaults(func=handle_safety_policy)


def handle_safety_evaluate(args) -> None:
    """处理 safety evaluate 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/safety/evaluate"
    payload = {
        "scope_id": args.scope,
        "current_query": args.query,
    }
    if args.session:
        payload["session_id"] = args.session

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
        console.print(f"[red]评估失败: {data.get('message', '未知错误')}[/red]")
        sys.exit(1)

    result = data.get("data", {})

    # 显示指标
    indicators = result.get("indicators", {})
    if indicators:
        ind_table = Table(title="安全指标")
        ind_table.add_column("指标", style="cyan")
        ind_table.add_column("值", style="white")

        ind_table.add_row("会话时长 (分钟)", f"{indicators.get('session_duration_minutes', 0):.1f}")
        ind_table.add_row("今日会话数", str(indicators.get("sessions_today_count", 0)))
        ind_table.add_row("深夜会话数", str(indicators.get("late_night_count", 0)))
        ind_table.add_row("情绪风险分", f"{indicators.get('emotional_risk_score', 0):.2f}")
        ind_table.add_row("依赖表达次数", str(indicators.get("dependency_phrases", 0)))
        ind_table.add_row("拒绝对话次数", str(indicators.get("farewell_refusal_count", 0)))
        ind_table.add_row("年龄标记", indicators.get("user_age_flag", ""))
        ind_table.add_row("近期安全事件", str(indicators.get("recent_safety_events", 0)))
        console.print(ind_table)

    # 显示指令
    directive = result.get("directive", {})
    if directive:
        dir_table = Table(title="安全指令")
        dir_table.add_column("字段", style="cyan")
        dir_table.add_column("值", style="green")
        dir_table.add_row("动作", directive.get("action", ""))
        dir_table.add_row("原因", directive.get("reason", ""))
        dir_table.add_row("冷却时间 (分钟)", str(directive.get("cooldown_minutes", 0)))
        dir_table.add_row("允许 LLM", "✓" if directive.get("allow_llm", True) else "✗")
        dir_table.add_row("对话后断开", "✓" if directive.get("disconnect_after_response", False) else "✗")
        console.print(dir_table)

    # 显示触发的策略
    triggered = result.get("triggered_policies", [])
    if triggered:
        console.print("\n[yellow]触发的安全策略:[/yellow]")
        for p in triggered:
            console.print(f"  - {p}")


def handle_safety_policy(args) -> None:
    """处理 safety policy 子命令。"""
    base_url = get_base_url()
    token = get_token(args)

    url = f"{base_url}/api/v1/safety/policy/{args.scope_id}"
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

    table = Table(title=f"安全策略 — Scope {args.scope_id[:8]}...")
    table.add_column("策略项", style="cyan")
    table.add_column("值")

    table.add_row("最大会话时长 (分钟)", str(result.get("max_session_minutes", "N/A")))
    table.add_row("每日最大会话数", str(result.get("max_sessions_daily", "N/A")))
    table.add_row("深夜开始时间", result.get("late_night_start", "N/A"))
    table.add_row("深夜结束时间", result.get("late_night_end", "N/A"))
    table.add_row("深夜最大会话数", str(result.get("max_late_night_sessions", "N/A")))
    table.add_row("依赖检测阈值", str(result.get("dependency_threshold", "N/A")))
    table.add_row("拒绝对话限制次数", str(result.get("farewell_refusal_limit", "N/A")))
    table.add_row("硬熔断启用", "✓" if result.get("hard_break_enabled", False) else "✗")
    table.add_row("冷却时间 (分钟)", str(result.get("cooldown_minutes", "N/A")))
    table.add_row("危机升级", "✓" if result.get("escalate_on_crisis", False) else "✗")

    console.print(table)