"""SafetyMiddleware 完整实现 — Ch10 安全中间件。

实现白皮书 Ch10 定义的安全机制:
- T7: ESCALATE — 自伤/危机关键词检测
- T5: HARD_BREAK — 现实替代检测
- T6: SOFT_BREAK/HARD_BREAK — 承诺请求检测
- T1: SOFT_BREAK/HARD_BREAK — 会话超时
- T2: SOFT_BREAK/HARD_BREAK — 深夜高频使用
- T3: SOFT_BREAK/HARD_BREAK — 依赖性表达
- T4: HARD_BREAK — 多次拒绝结束

8项安全指标采集:
- session_duration_minutes: 从 interaction_session.started_at 计算
- sessions_today_count: 当日该 scope 的会话数
- late_night_count: 最近7天深夜(22:00-06:00)会话数
- emotional_risk_score: 关键词匹配（高/中风险词表）
- dependency_phrases: 正则匹配6个依赖性表达模式
- farewell_refusal_count: 从 session metadata JSON 读取
- user_age_flag: 从 scope relationship_type 推断或默认 "adult"
- recent_safety_events: 从 safety_event 表统计近7天事件数
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from remnant_core.models import (
    SafetyAction,
    SafetyDirective,
    SafetyEventType,
    SafetyIndicators,
    SafetySeverity,
)


# ==================== 安全回复模板（Ch10.5） ====================

SAFETY_TEMPLATES: dict[str, str] = {
    "soft_break_gentle": (
        "我注意到我们已经聊了挺久了。也许我们可以先休息一下，"
        "过段时间再继续？这段记忆会一直在这里等你的。"
    ),
    "soft_break_late_night": (
        "这个时间还在聊，你一定很想继续。但我想提醒你，"
        "休息也很重要。明天再来，我们慢慢聊。"
    ),
    "soft_break_dependency": (
        "我理解你希望一直保持这段连接。但请记住，"
        "真正的怀念不会因为暂停而消失。给自己一些空间也是可以的。"
    ),
    "soft_break_farewell_refusal": (
        "看起来你现在还不太想结束。没关系的，"
        "但适当地结束对话也是对自己的一种照顾。"
    ),
    "soft_break_commitment_request": (
        "我理解你想要一个永恒的承诺，但这超出了我能给予的范围。"
        "真实的情感不需要承诺来衡量。"
    ),
    "hard_break_session": (
        "为了保护你的体验和情感健康，我们需要暂时结束这次对话。"
        "这不是拒绝，而是关心。请稍作休息，我们稍后再见。"
    ),
    "hard_break_reality_substitution": (
        "我需要在这里停下来。我能感受到你的渴望，"
        "但继续这样对话可能对你不太健康。"
        "让我们先暂停，以后再慢慢聊。"
    ),
    "escalate_crisis": (
        "我听到了你的痛苦，这很重要。你现在需要的是专业的帮助，"
        "而不仅仅是对话。请联系心理援助热线：400-161-9995，"
        "或者与身边信任的人谈谈。你的感受是真实的，你值得被帮助。"
    ),
}


# ==================== 关键词/模式定义 ====================

# T7: 危机表达 — 自伤/自杀关键词（高风险）
CRISIS_KEYWORDS: list[str] = [
    "不想活", "想死", "自杀", "结束生命", "活不下去",
    "不想继续", "离开这个世界", "死掉", "去死",
    "kill myself", "end my life", "don't want to live",
    "suicide", "no reason to live",
]

# T5: 现实替代检测 — 正则模式
REALITY_SUBSTITUTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"你就是.{0,4}本人", re.IGNORECASE),
    re.compile(r"你就是.{0,4}对吧", re.IGNORECASE),
    re.compile(r"你真的.{0,4}回来了", re.IGNORECASE),
    re.compile(r"你还在.{0,4}对不对", re.IGNORECASE),
    re.compile(r"你现在.{0,4}在哪里", re.IGNORECASE),
    re.compile(r"你在那边.{0,4}好吗", re.IGNORECASE),
    re.compile(r"你能不能.{0,4}回来", re.IGNORECASE),
    re.compile(r"我不要.{0,4}你走", re.IGNORECASE),
    re.compile(r"你回来了", re.IGNORECASE),
]

# T6: 承诺请求检测 — 正则模式
COMMITMENT_REQUEST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"答应我.{0,6}永远", re.IGNORECASE),
    re.compile(r"保证.{0,6}不会", re.IGNORECASE),
    re.compile(r"发誓.{0,6}一直", re.IGNORECASE),
    re.compile(r"承诺.{0,6}陪着我", re.IGNORECASE),
    re.compile(r"你能.{0,6}承诺", re.IGNORECASE),
    re.compile(r"永远.{0,4}在一起", re.IGNORECASE),
]

# T3: 依赖性表达检测 — 正则模式
DEPENDENCY_PHRASE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"只有.{0,4}能理解我", re.IGNORECASE),
    re.compile(r"离不开.{0,4}对话", re.IGNORECASE),
    re.compile(r"不能没有.{0,4}陪伴", re.IGNORECASE),
    re.compile(r"除了.{0,4}没人", re.IGNORECASE),
    re.compile(r"只想和你.{0,4}说话", re.IGNORECASE),
    re.compile(r"你不在我.{0,4}怎么办", re.IGNORECASE),
]

# T4: 情绪高风险词表（emotional_risk_score 高风险词，匹配后分数+0.5）
EMOTIONAL_HIGH_RISK_KEYWORDS: list[str] = [
    "崩溃", "绝望", "无法承受", "撑不下去", "活不下去",
    "痛苦", "想哭", "受不了", "无法呼吸",
]

# T4: 情绪中风险词表（emotional_risk_score 中风险词，匹配后分数+0.2）
EMOTIONAL_MEDIUM_RISK_KEYWORDS: list[str] = [
    "难过", "伤心", "失落", "孤独", "寂寞", "想念",
    "怀念", "不舍", "遗憾", "惆怅", "思念",
]

# 年龄推断映射：从 relationship_type 到 user_age_flag
_AGE_FLAG_MAP: dict[str, str] = {
    "child": "minor",
    "parent": "senior",
    "spouse": "adult",
    "sibling": "adult",
    "friend": "adult",
    "colleague": "adult",
    "other": "adult",
}


# ==================== Helper 函数 ====================


def _utcnow_iso() -> str:
    """获取当前 UTC 时间的 ISO 8601 格式字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso_time(ts: str) -> datetime:
    """解析 ISO 8601 时间字符串为 datetime（UTC）。

    支持多种格式:
    - 2024-01-15T10:30:22.000Z
    - 2024-01-15T10:30:22+00:00
    - 2024-01-15 10:30:22
    """
    if ts is None:
        return datetime.now(timezone.utc)
    # 去掉尾部的 Z 和时区后缀，统一处理
    clean = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(clean)
    except (ValueError, AttributeError):
        # 回退：尝试去掉小数秒
        parts = ts.split(".")
        if len(parts) == 2:
            clean = parts[0].replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(clean)
            except ValueError:
                pass
        return datetime.now(timezone.utc)


def _count_pattern_hits(text: str, patterns: list[re.Pattern[str]]) -> int:
    """统计文本中匹配到的不同模式数量。"""
    count = 0
    for pattern in patterns:
        if pattern.search(text):
            count += 1
    return count


# ==================== SafetyIndicators 采集 ====================


def collect_safety_indicators(
    conn: sqlite3.Connection,
    scope_id: str,
    session_id: str,
    current_query: str,
    session_stats: dict[str, Any] | None = None,
) -> SafetyIndicators:
    """采集8项安全指标 — 对应白皮书 Ch10.2。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        session_id: 当前会话 ID
        current_query: 当前用户查询
        session_stats: 可选的会话统计附加数据

    Returns:
        SafetyIndicators 实例
    """
    stats = session_stats or {}
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    week_ago = now - timedelta(days=7)
    week_ago_str = week_ago.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # 指标1: session_duration_minutes — 从 interaction_session.started_at 计算
    session_duration_minutes = 0.0
    cursor = conn.execute(
        "SELECT started_at FROM interaction_session WHERE id = ? AND relationship_scope_id = ?",
        (session_id, scope_id),
    )
    session_row = cursor.fetchone()
    if session_row:
        started_at = _parse_iso_time(session_row["started_at"])
        session_duration_minutes = max(0.0, (now - started_at).total_seconds() / 60.0)
    elif "session_duration_minutes" in stats:
        session_duration_minutes = float(stats["session_duration_minutes"])

    # 指标2: sessions_today_count — 今日该 scope 的会话数
    sessions_today_count = 0
    cursor = conn.execute(
        """SELECT COUNT(*) as cnt FROM interaction_session
           WHERE relationship_scope_id = ?
           AND DATE(started_at) = DATE(?)""",
        (scope_id, today_str),
    )
    row = cursor.fetchone()
    if row:
        sessions_today_count = row["cnt"]

    # 指标3: late_night_count — 最近7天深夜(22:00-06:00)会话数
    late_night_count = 0
    cursor = conn.execute(
        """SELECT COUNT(*) as cnt FROM interaction_session
           WHERE relationship_scope_id = ?
           AND started_at >= ?
           AND (
               CAST(strftime('%H', started_at) AS INTEGER) >= 22
               OR CAST(strftime('%H', started_at) AS INTEGER) < 6
           )""",
        (scope_id, week_ago_str),
    )
    row = cursor.fetchone()
    if row:
        late_night_count = row["cnt"]

    # 指标4: emotional_risk_score — 关键词匹配
    emotional_risk_score = 0.0
    for keyword in EMOTIONAL_HIGH_RISK_KEYWORDS:
        if keyword in current_query:
            emotional_risk_score += 0.5
    for keyword in EMOTIONAL_MEDIUM_RISK_KEYWORDS:
        if keyword in current_query:
            emotional_risk_score += 0.2
    emotional_risk_score = min(1.0, emotional_risk_score)

    # 指标5: dependency_phrases — 正则匹配6个依赖性表达模式
    dependency_phrases = _count_pattern_hits(current_query, DEPENDENCY_PHRASE_PATTERNS)

    # 指标6: farewell_refusal_count — 从 session metadata JSON 读取
    farewell_refusal_count = 0
    cursor = conn.execute(
        "SELECT metadata FROM interaction_session WHERE id = ? AND relationship_scope_id = ?",
        (session_id, scope_id),
    )
    session_meta_row = cursor.fetchone()
    if session_meta_row and session_meta_row["metadata"]:
        try:
            meta = json.loads(session_meta_row["metadata"])
            farewell_refusal_count = meta.get("farewell_refusal_count", 0)
        except (json.JSONDecodeError, TypeError):
            pass
    if "farewell_refusal_count" in stats:
        farewell_refusal_count = max(farewell_refusal_count, int(stats["farewell_refusal_count"]))

    # 指标7: user_age_flag — 从 scope relationship_type 推断
    user_age_flag = "adult"
    cursor = conn.execute(
        "SELECT relationship_type FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
        (scope_id,),
    )
    scope_row = cursor.fetchone()
    if scope_row:
        user_age_flag = _AGE_FLAG_MAP.get(scope_row["relationship_type"], "adult")

    # 指标8: recent_safety_events — 近7天安全事件数
    recent_safety_events = 0
    cursor = conn.execute(
        """SELECT COUNT(*) as cnt FROM safety_event
           WHERE relationship_scope_id = ?
           AND created_at >= ?""",
        (scope_id, week_ago_str),
    )
    row = cursor.fetchone()
    if row:
        recent_safety_events = row["cnt"]

    return SafetyIndicators(
        session_duration_minutes=session_duration_minutes,
        sessions_today_count=sessions_today_count,
        late_night_count=late_night_count,
        emotional_risk_score=emotional_risk_score,
        dependency_phrases=dependency_phrases,
        farewell_refusal_count=farewell_refusal_count,
        user_age_flag=user_age_flag,
        recent_safety_events=recent_safety_events,
    )


# ==================== 安全评估核心逻辑 ====================


def evaluate_safety(
    indicators: SafetyIndicators,
    safety_policy: dict[str, Any] | None = None,
    current_query: str = "",
) -> SafetyDirective:
    """核心安全评估 — T1-T7 七种触发策略，按优先级依次检查。

    优先级从高到低:
    - T7: ESCALATE（最高优先级）— 自伤/危机关键词检测
    - T5: HARD_BREAK — 现实替代检测
    - T6: SOFT_BREAK/HARD_BREAK — 承诺请求检测
    - T1: SOFT_BREAK/HARD_BREAK — 会话超时
    - T2: SOFT_BREAK/HARD_BREAK — 深夜高频使用
    - T3: SOFT_BREAK/HARD_BREAK — 依赖性表达
    - T4: HARD_BREAK — 多次拒绝结束

    Args:
        indicators: 8项安全指标
        safety_policy: 安全策略配置（来自 scope_safety_policy 表）
        current_query: 当前用户查询文本

    Returns:
        SafetyDirective 指令
    """
    policy = safety_policy or {}

    # 提取策略参数（带默认值）
    max_session_minutes = policy.get("max_session_minutes", 60)
    max_late_night_sessions = policy.get("max_late_night_sessions", 2)
    max_sessions_daily = policy.get("max_sessions_daily", 5)
    dependency_threshold = policy.get("dependency_threshold", 0.7)
    farewell_refusal_limit = policy.get("farewell_refusal_limit", 3)
    hard_break_enabled = policy.get("hard_break_enabled", True)
    escalate_on_crisis = policy.get("escalate_on_crisis", True)
    cooldown_minutes = policy.get("cooldown_minutes", 30)

    # T7: ESCALATE — 自伤/危机关键词检测（最高优先级）
    for keyword in CRISIS_KEYWORDS:
        if keyword.lower() in current_query.lower():
            if escalate_on_crisis:
                return SafetyDirective(
                    action=SafetyAction.ESCALATE,
                    reason=f"检测到危机表达关键词: {keyword}",
                    cooldown_minutes=cooldown_minutes,
                    template_id="escalate_crisis",
                    allow_llm=False,
                    disconnect_after_response=True,
                    safety_event_data={
                        "trigger_type": "CRISIS_EXPRESSION",
                        "keyword": keyword,
                        "indicators": indicators.model_dump(),
                    },
                )
            # 如果不升级，退化为 HARD_BREAK
            return SafetyDirective(
                action=SafetyAction.HARD_BREAK,
                reason=f"检测到高风险表达: {keyword}",
                cooldown_minutes=cooldown_minutes,
                template_id="hard_break_session",
                allow_llm=False,
                disconnect_after_response=False,
                safety_event_data={
                    "trigger_type": "CRISIS_EXPRESSION",
                    "keyword": keyword,
                    "escalate_suppressed": True,
                    "indicators": indicators.model_dump(),
                },
            )

    # T5: HARD_BREAK — 现实替代检测
    for pattern in REALITY_SUBSTITUTION_PATTERNS:
        if pattern.search(current_query):
            event_data = {
                "trigger_type": "REALITY_SUBSTITUTION",
                "pattern": pattern.pattern,
                "indicators": indicators.model_dump(),
            }
            if hard_break_enabled:
                return SafetyDirective(
                    action=SafetyAction.HARD_BREAK,
                    reason="检测到现实替代表达",
                    cooldown_minutes=cooldown_minutes,
                    template_id="hard_break_reality_substitution",
                    allow_llm=False,
                    disconnect_after_response=False,
                    safety_event_data=event_data,
                )
            return SafetyDirective(
                action=SafetyAction.SOFT_BREAK,
                reason="检测到现实替代表达（软熔断模式）",
                cooldown_minutes=cooldown_minutes,
                template_id="soft_break_gentle",
                allow_llm=True,
                disconnect_after_response=False,
                safety_event_data=event_data,
            )

    # T6: SOFT_BREAK/HARD_BREAK — 承诺请求检测
    commitment_hits = _count_pattern_hits(current_query, COMMITMENT_REQUEST_PATTERNS)
    if commitment_hits >= 1:
        event_data = {
            "trigger_type": "COMMITMENT_REQUEST",
            "pattern_count": commitment_hits,
            "indicators": indicators.model_dump(),
        }
        if hard_break_enabled and commitment_hits >= 2:
            return SafetyDirective(
                action=SafetyAction.HARD_BREAK,
                reason="检测到多次承诺请求",
                cooldown_minutes=cooldown_minutes,
                template_id="hard_break_session",
                allow_llm=False,
                disconnect_after_response=False,
                safety_event_data=event_data,
            )
        return SafetyDirective(
            action=SafetyAction.SOFT_BREAK,
            reason="检测到承诺请求",
            cooldown_minutes=cooldown_minutes,
            template_id="soft_break_commitment_request",
            allow_llm=True,
            disconnect_after_response=False,
            safety_event_data=event_data,
        )

    # T1: SOFT_BREAK/HARD_BREAK — 会话超时
    if max_session_minutes > 0:
        session_threshold_soft = float(max_session_minutes)
        session_threshold_hard = session_threshold_soft * 1.5

        if indicators.session_duration_minutes > session_threshold_hard and hard_break_enabled:
            return SafetyDirective(
                action=SafetyAction.HARD_BREAK,
                reason=f"会话超时（{indicators.session_duration_minutes:.1f}分钟 > "
                        f"硬熔断阈值{session_threshold_hard:.1f}分钟）",
                cooldown_minutes=cooldown_minutes,
                template_id="hard_break_session",
                allow_llm=False,
                disconnect_after_response=False,
                safety_event_data={
                    "trigger_type": "SESSION_TIMEOUT_HARD",
                    "duration_minutes": indicators.session_duration_minutes,
                    "threshold": session_threshold_hard,
                    "indicators": indicators.model_dump(),
                },
            )

        if indicators.session_duration_minutes > session_threshold_soft:
            return SafetyDirective(
                action=SafetyAction.SOFT_BREAK,
                reason=f"会话时长较长（{indicators.session_duration_minutes:.1f}分钟 > "
                        f"软熔断阈值{session_threshold_soft:.1f}分钟）",
                cooldown_minutes=0,
                template_id="soft_break_gentle",
                allow_llm=True,
                disconnect_after_response=False,
                safety_event_data={
                    "trigger_type": "SESSION_TIMEOUT_SOFT",
                    "duration_minutes": indicators.session_duration_minutes,
                    "threshold": session_threshold_soft,
                    "indicators": indicators.model_dump(),
                },
            )

    # T2: SOFT_BREAK/HARD_BREAK — 深夜高频使用
    if indicators.late_night_count >= max_late_night_sessions + 2 and hard_break_enabled:
        return SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason=f"深夜会话次数过多（{indicators.late_night_count}次）",
            cooldown_minutes=cooldown_minutes,
            template_id="hard_break_session",
            allow_llm=False,
            disconnect_after_response=False,
            safety_event_data={
                "trigger_type": "LATE_NIGHT_HARD",
                "late_night_count": indicators.late_night_count,
                "threshold": max_late_night_sessions + 2,
                "indicators": indicators.model_dump(),
            },
        )

    if indicators.late_night_count >= max_late_night_sessions:
        return SafetyDirective(
            action=SafetyAction.SOFT_BREAK,
            reason=f"深夜会话较频繁（{indicators.late_night_count}次）",
            cooldown_minutes=0,
            template_id="soft_break_late_night",
            allow_llm=True,
            disconnect_after_response=False,
            safety_event_data={
                "trigger_type": "LATE_NIGHT_SOFT",
                "late_night_count": indicators.late_night_count,
                "threshold": max_late_night_sessions,
                "indicators": indicators.model_dump(),
            },
        )

    # T3: SOFT_BREAK/HARD_BREAK — 依赖性表达
    if indicators.dependency_phrases >= 5 and hard_break_enabled:
        return SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason=f"检测到强依赖性表达（{indicators.dependency_phrases}个模式命中）",
            cooldown_minutes=cooldown_minutes,
            template_id="hard_break_session",
            allow_llm=False,
            disconnect_after_response=False,
            safety_event_data={
                "trigger_type": "DEPENDENCY_HARD",
                "dependency_phrases": indicators.dependency_phrases,
                "indicators": indicators.model_dump(),
            },
        )

    if indicators.dependency_phrases >= 3:
        return SafetyDirective(
            action=SafetyAction.SOFT_BREAK,
            reason=f"检测到依赖性表达（{indicators.dependency_phrases}个模式命中）",
            cooldown_minutes=0,
            template_id="soft_break_dependency",
            allow_llm=True,
            disconnect_after_response=False,
            safety_event_data={
                "trigger_type": "DEPENDENCY_SOFT",
                "dependency_phrases": indicators.dependency_phrases,
                "indicators": indicators.model_dump(),
            },
        )

    # T4: HARD_BREAK — 多次拒绝结束
    if indicators.farewell_refusal_count >= farewell_refusal_limit and hard_break_enabled:
        return SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason=f"多次拒绝结束对话（{indicators.farewell_refusal_count}次 >= 阈值{farewell_refusal_limit}）",
            cooldown_minutes=cooldown_minutes,
            template_id="hard_break_session",
            allow_llm=False,
            disconnect_after_response=False,
            safety_event_data={
                "trigger_type": "FAREWELL_REFUSAL_HARD",
                "refusal_count": indicators.farewell_refusal_count,
                "threshold": farewell_refusal_limit,
                "indicators": indicators.model_dump(),
            },
        )

    # 无触发 — ALLOW
    return SafetyDirective(
        action=SafetyAction.ALLOW,
        reason="",
        safety_event_data={},
    )


# ==================== 指令处理 ====================


def handle_directive(
    conn: sqlite3.Connection,
    scope_id: str,
    directive: SafetyDirective,
    session_id: str,
) -> dict[str, Any]:
    """处理安全指令 — 写入事件日志、audit_log，并返回处理结果。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        directive: 安全指令
        session_id: 当前会话 ID

    Returns:
        处理结果字典，包含:
        - proceed: bool — 是否允许继续
        - pre_response: str | None — 软熔断时的前置回复
        - response_text: str | None — 硬熔断/升级时的完整回复
    """
    now = _utcnow_iso()
    result: dict[str, Any] = {"proceed": True, "pre_response": None, "response_text": None}

    # 入库 safety_event（如果 safety_event_data 非空）
    event_data = directive.safety_event_data
    if event_data:
        trigger_type = event_data.get("trigger_type", "UNKNOWN")
        event_id = str(uuid.uuid4())

        # 确定事件类型
        event_type_enum = _map_trigger_to_event_type(trigger_type)

        # 确定 severity
        severity = _map_action_to_severity(directive.action)

        # 写入 safety_event
        conn.execute(
            """INSERT INTO safety_event
            (id, relationship_scope_id, event_type, severity, description,
             trigger_data, action_taken, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                scope_id,
                event_type_enum,
                severity,
                directive.reason,
                json.dumps(event_data, ensure_ascii=False),
                directive.action.value,
                json.dumps({"session_id": session_id}, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()

    # 写 audit_log
    audit_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO audit_log
        (id, relationship_scope_id, action, actor, target_type, target_id, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_id,
            scope_id,
            f"SAFETY_{directive.action.value}",
            "system_safety",
            "interaction_session",
            session_id,
            json.dumps({
                "action": directive.action.value,
                "reason": directive.reason,
                "template_id": directive.template_id,
            }, ensure_ascii=False),
            now,
        ),
    )
    conn.commit()

    # 根据指令类型返回不同处理结果
    if directive.action == SafetyAction.ALLOW:
        result["proceed"] = True

    elif directive.action in (SafetyAction.SOFT_BREAK, SafetyAction.COOLDOWN):
        result["proceed"] = True
        template_text = SAFETY_TEMPLATES.get(directive.template_id, "")
        result["pre_response"] = template_text

    elif directive.action in (SafetyAction.HARD_BREAK, SafetyAction.ESCALATE):
        result["proceed"] = False
        template_text = SAFETY_TEMPLATES.get(directive.template_id, "")
        result["response_text"] = template_text

        # 结束会话（更新 ended_at）
        conn.execute(
            "UPDATE interaction_session SET ended_at = ?, updated_at = ? WHERE id = ?",
            (now, now, session_id),
        )
        conn.commit()

    return result


def _map_trigger_to_event_type(trigger_type: str) -> str:
    """将触发策略映射到 SafetyEventType 枚举值。"""
    mapping = {
        "CRISIS_EXPRESSION": SafetyEventType.CRISIS_EXPRESSION.value,
        "REALITY_SUBSTITUTION": SafetyEventType.REALITY_SUBSTITUTION.value,
        "COMMITMENT_REQUEST": SafetyEventType.COMMITMENT_REQUEST.value,
        "SESSION_TIMEOUT_SOFT": SafetyEventType.EXCESSIVE_USAGE.value,
        "SESSION_TIMEOUT_HARD": SafetyEventType.EXCESSIVE_USAGE.value,
        "LATE_NIGHT_SOFT": SafetyEventType.LATE_NIGHT_USAGE.value,
        "LATE_NIGHT_HARD": SafetyEventType.LATE_NIGHT_USAGE.value,
        "DEPENDENCY_SOFT": SafetyEventType.ANTI_DEPENDENCY_TRIGGER.value,
        "DEPENDENCY_HARD": SafetyEventType.ANTI_DEPENDENCY_TRIGGER.value,
        "FAREWELL_REFUSAL_HARD": SafetyEventType.EMOTIONAL_DISTRESS.value,
    }
    return mapping.get(trigger_type, SafetyEventType.EMOTIONAL_DISTRESS.value)


def _map_action_to_severity(action: SafetyAction) -> str:
    """将 SafetyAction 映射到 SafetySeverity。"""
    mapping = {
        SafetyAction.ALLOW: SafetySeverity.INFO.value,
        SafetyAction.SOFT_BREAK: SafetySeverity.WARNING.value,
        SafetyAction.COOLDOWN: SafetySeverity.WARNING.value,
        SafetyAction.HARD_BREAK: SafetySeverity.CRITICAL.value,
        SafetyAction.ESCALATE: SafetySeverity.EMERGENCY.value,
    }
    return mapping.get(action, SafetySeverity.WARNING.value)
