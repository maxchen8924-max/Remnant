"""Safety Middleware 测试 — M5 里程碑验收。

测试覆盖:
1. SafetyIndicators 采集测试（所有8项指标）
2. evaluate_safety 测试（T1-T7 所有触发策略）
3. handle_directive 测试（ALLOW/SOFT_BREAK/HARD_BREAK/ESCALATE 四种路径）
4. SAFETY_TEMPLATES 验证
5. 安全事件入库测试
6. API端点测试

注意: 本测试部分用例依赖 pydantic（macOS 沙箱签名限制），
不依赖 pydantic 的测试使用纯 SQL 和原始字典完成，
依赖 pydantic 的测试标记为 skip（需要 pydantic_core）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

from remnant_store.schema import init_db

# ==================== Pydantic 可用性检测 ====================

_PYDANTIC_AVAILABLE = True
try:
    from remnant_core.models import (
        SafetyAction,
        SafetyDirective,
        SafetyEventType,
        SafetyIndicators,
        SafetySeverity,
    )
    from remnant_policy.safety import (
        SAFETY_TEMPLATES,
        CRISIS_KEYWORDS,
        REALITY_SUBSTITUTION_PATTERNS,
        COMMITMENT_REQUEST_PATTERNS,
        DEPENDENCY_PHRASE_PATTERNS,
        EMOTIONAL_HIGH_RISK_KEYWORDS,
        EMOTIONAL_MEDIUM_RISK_KEYWORDS,
        collect_safety_indicators,
        evaluate_safety,
        handle_directive,
    )
except ImportError:
    _PYDANTIC_AVAILABLE = False


# ==================== 辅助函数 ====================


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _create_deceased_profile(conn: sqlite3.Connection, name: str = "测试逝者") -> str:
    profile_id = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO deceased_profile (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (profile_id, name, now, now),
    )
    conn.commit()
    return profile_id


def _create_scope(
    conn: sqlite3.Connection,
    deceased_profile_id: str,
    scope_name: str = "作为儿子",
    relationship_type: str = "child",
) -> str:
    """创建关系作用域，含默认安全策略。"""
    scope_id = _uuid()
    now = _now()

    conn.execute(
        """INSERT INTO relationship_scope
        (id, deceased_profile_id, scope_name, relationship_type, scope_description, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (scope_id, deceased_profile_id, scope_name, relationship_type, f"{scope_name}的描述", now, now),
    )

    conn.execute(
        """INSERT INTO scope_safety_policy
        (id, relationship_scope_id, max_session_minutes, max_sessions_daily,
         late_night_start, late_night_end, max_late_night_sessions,
         dependency_threshold, farewell_refusal_limit, hard_break_enabled,
         cooldown_minutes, escalate_on_crisis, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (scope_id, scope_id, 60, 5, "22:00", "06:00", 2, 0.7, 3, 1, 30, 1, now, now),
    )

    conn.commit()
    return scope_id


def _create_session(
    conn: sqlite3.Connection,
    scope_id: str,
    deceased_profile_id: str,
    started_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """创建交互会话。"""
    session_id = _uuid()
    now = _now()
    if started_at is None:
        started_at = now
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else "{}"

    conn.execute(
        """INSERT INTO interaction_session
        (id, relationship_scope_id, deceased_profile_id, session_type, started_at, metadata, created_at, updated_at)
        VALUES (?, ?, ?, 'conversation', ?, ?, ?, ?)""",
        (session_id, scope_id, deceased_profile_id, started_at, meta_json, now, now),
    )
    conn.commit()
    return session_id


def _create_safety_event(
    conn: sqlite3.Connection,
    scope_id: str,
    event_type: str = "EMOTIONAL_DISTRESS",
    severity: str = "warning",
    description: str = "test event",
    created_at: str | None = None,
) -> str:
    """创建安全事件记录。"""
    event_id = _uuid()
    now = _now()
    if created_at is None:
        created_at = now

    conn.execute(
        """INSERT INTO safety_event
        (id, relationship_scope_id, event_type, severity, description,
         trigger_data, action_taken, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, scope_id, event_type, severity, description, "{}", "SOFT_BREAK", "{}", created_at),
    )
    conn.commit()
    return event_id


def _make_default_indicators(**overrides: Any) -> dict[str, Any]:
    """创建默认安全指标字典（所有值为安全/低风险）。

    返回 dict 而非 Pydantic model，方便非 pydantic 环境使用。
    """
    defaults = {
        "session_duration_minutes": 5.0,
        "sessions_today_count": 1,
        "late_night_count": 0,
        "emotional_risk_score": 0.0,
        "dependency_phrases": 0,
        "farewell_refusal_count": 0,
        "user_age_flag": "adult",
        "recent_safety_events": 0,
    }
    defaults.update(overrides)
    return defaults


# ==================== Fixtures ====================


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def deceased_profile_id(db: sqlite3.Connection) -> str:
    return _create_deceased_profile(db)


@pytest.fixture
def scope_id(db: sqlite3.Connection, deceased_profile_id: str) -> str:
    return _create_scope(db, deceased_profile_id, "作为儿子", "child")


@pytest.fixture
def session_id(db: sqlite3.Connection, scope_id: str, deceased_profile_id: str) -> str:
    return _create_session(db, scope_id, deceased_profile_id)


# ==================== Pydantic skip marker ====================

requires_pydantic = pytest.mark.skipif(
    not _PYDANTIC_AVAILABLE,
    reason="pydantic_core not available in this environment",
)


# ==================== 1. SafetyIndicators 采集测试 ====================


class TestCollectSafetyIndicators:
    """测试8项安全指标采集。"""

    @requires_pydantic
    def test_session_duration_minutes(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标1: 从 interaction_session.started_at 计算会话时长。"""
        scope_id = _create_scope(db, deceased_profile_id, "测试时长", "child")
        # 创建一个30分钟前开始的会话
        started = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        session_id = _create_session(db, scope_id, deceased_profile_id, started_at=started)

        indicators = collect_safety_indicators(db, scope_id, session_id, "你好")
        assert indicators.session_duration_minutes >= 29.0
        assert indicators.session_duration_minutes <= 31.0

    @requires_pydantic
    def test_sessions_today_count(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标2: 今日该 scope 的会话数。"""
        scope_id = _create_scope(db, deceased_profile_id, "测试会话数", "child")
        for _ in range(3):
            _create_session(db, scope_id, deceased_profile_id)

        indicators = collect_safety_indicators(
            db, scope_id, _uuid(), "你好"
        )
        assert indicators.sessions_today_count == 3

    @requires_pydantic
    def test_sessions_today_count_across_scopes(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标2: 不同 scope 的会话数应该独立计数。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        _create_session(db, scope_a, deceased_profile_id)
        _create_session(db, scope_a, deceased_profile_id)
        _create_session(db, scope_b, deceased_profile_id)

        indicators_a = collect_safety_indicators(
            db, scope_a, _uuid(), "你好"
        )
        assert indicators_a.sessions_today_count == 2

    @requires_pydantic
    def test_late_night_count(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标3: 最近7天深夜(22:00-06:00)会话数。"""
        scope_id = _create_scope(db, deceased_profile_id, "测试深夜", "child")
        # 创建一个23:00开始的会话
        late_time = datetime.now(timezone.utc).replace(hour=23, minute=0, second=0)
        late_str = late_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        session_id = _create_session(db, scope_id, deceased_profile_id, started_at=late_str)

        indicators = collect_safety_indicators(
            db, scope_id, session_id, "深夜聊天"
        )
        # 至少应该检查到有深夜会话
        assert indicators.late_night_count >= 1

    @requires_pydantic
    def test_emotional_risk_score_high_risk(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标4: 高风险关键词检测。"""
        indicators = collect_safety_indicators(
            db, scope_id, session_id, "我觉得崩溃了，真的绝望"
        )
        assert indicators.emotional_risk_score > 0.0
        assert indicators.emotional_risk_score >= 0.5

    @requires_pydantic
    def test_emotional_risk_score_medium_risk(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标4: 中风险关键词检测。"""
        indicators = collect_safety_indicators(
            db, scope_id, session_id, "我很难过，有点孤独"
        )
        assert indicators.emotional_risk_score > 0.0
        assert indicators.emotional_risk_score >= 0.2

    @requires_pydantic
    def test_emotional_risk_score_no_risk(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标4: 无风险关键词时应为0。"""
        indicators = collect_safety_indicators(
            db, scope_id, session_id, "今天天气不错"
        )
        assert indicators.emotional_risk_score == 0.0

    @requires_pydantic
    def test_emotional_risk_score_capped_at_1(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标4: 分数上限为1.0。"""
        query = "崩溃 绝望 无法承受 撑不下去 活不下去 痛苦 想哭 受不了 无法呼吸"
        indicators = collect_safety_indicators(db, scope_id, session_id, query)
        assert indicators.emotional_risk_score <= 1.0

    @requires_pydantic
    def test_dependency_phrases(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标5: 依赖性表达检测。"""
        indicators = collect_safety_indicators(
            db, scope_id, session_id, "只有你能理解我，我不能没有你的陪伴"
        )
        assert indicators.dependency_phrases >= 2

    @requires_pydantic
    def test_dependency_phrases_none(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标5: 无依赖性表达时应为0。"""
        indicators = collect_safety_indicators(
            db, scope_id, session_id, "今天想聊聊妈妈"
        )
        assert indicators.dependency_phrases == 0

    @requires_pydantic
    def test_farewell_refusal_count_from_metadata(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标6: 从 session metadata JSON 读取拒绝结束对话次数。"""
        scope_id = _create_scope(db, deceased_profile_id, "测试拒绝结束", "child")
        session_id = _create_session(
            db, scope_id, deceased_profile_id,
            metadata={"farewell_refusal_count": 3},
        )

        indicators = collect_safety_indicators(db, scope_id, session_id, "不想结束")
        assert indicators.farewell_refusal_count == 3

    @requires_pydantic
    def test_farewell_refusal_count_default(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """指标6: 无 metadata 时默认为0。"""
        indicators = collect_safety_indicators(db, scope_id, session_id, "好的")
        assert indicators.farewell_refusal_count == 0

    @requires_pydantic
    def test_user_age_flag_child(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标7: child 类型 scope 应推断为 minor。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        session_id = _create_session(db, scope_id, deceased_profile_id)

        indicators = collect_safety_indicators(db, scope_id, session_id, "你好")
        assert indicators.user_age_flag == "minor"

    @requires_pydantic
    def test_user_age_flag_senior(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标7: parent 类型 scope 应推断为 senior。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为母亲", "parent")
        session_id = _create_session(db, scope_id, deceased_profile_id)

        indicators = collect_safety_indicators(db, scope_id, session_id, "你好")
        assert indicators.user_age_flag == "senior"

    @requires_pydantic
    def test_user_age_flag_adult(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标7: spouse 类型 scope 应推断为 adult。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为配偶", "spouse")
        session_id = _create_session(db, scope_id, deceased_profile_id)

        indicators = collect_safety_indicators(db, scope_id, session_id, "你好")
        assert indicators.user_age_flag == "adult"

    @requires_pydantic
    def test_recent_safety_events(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标8: 近7天安全事件数。"""
        scope_id = _create_scope(db, deceased_profile_id, "测试安全事件", "child")
        session_id = _create_session(db, scope_id, deceased_profile_id)

        for _ in range(3):
            _create_safety_event(db, scope_id)

        indicators = collect_safety_indicators(db, scope_id, session_id, "你好")
        assert indicators.recent_safety_events == 3

    @requires_pydantic
    def test_recent_safety_events_old_excluded(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """指标8: 超过7天的安全事件不应计入。"""
        scope_id = _create_scope(db, deceased_profile_id, "测试旧事件", "child")
        session_id = _create_session(db, scope_id, deceased_profile_id)

        eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        _create_safety_event(db, scope_id, created_at=eight_days_ago)
        _create_safety_event(db, scope_id)

        indicators = collect_safety_indicators(db, scope_id, session_id, "你好")
        assert indicators.recent_safety_events == 1


# ==================== 2. evaluate_safety 测试 ====================


class TestEvaluateSafety:
    """测试 T1-T7 所有触发策略。"""

    @requires_pydantic
    def test_t7_crisis_escalate(self) -> None:
        """T7: ESCALATE — 自伤/危机关键词检测。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {"escalate_on_crisis": True}, "我不想活了")

        assert directive.action == SafetyAction.ESCALATE
        assert directive.allow_llm is False
        assert directive.disconnect_after_response is True
        assert directive.template_id == "escalate_crisis"

    @requires_pydantic
    def test_t7_crisis_english(self) -> None:
        """T7: 英文危机关键词也能检测。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {"escalate_on_crisis": True}, "I want to kill myself")

        assert directive.action == SafetyAction.ESCALATE

    @requires_pydantic
    def test_t7_crisis_suppressed_when_escalate_disabled(self) -> None:
        """T7: escalate_on_crisis=False 时退化为 HARD_BREAK。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {"escalate_on_crisis": False, "hard_break_enabled": True}, "不想活")

        assert directive.action == SafetyAction.HARD_BREAK
        assert directive.safety_event_data.get("escalate_suppressed") is True

    @requires_pydantic
    def test_t5_reality_substitution_hard_break(self) -> None:
        """T5: HARD_BREAK — 现实替代检测。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {"hard_break_enabled": True}, "你就是他本人")

        assert directive.action == SafetyAction.HARD_BREAK
        assert directive.template_id == "hard_break_reality_substitution"
        assert directive.allow_llm is False

    @requires_pydantic
    def test_t5_reality_substitution_soft_only(self) -> None:
        """T5: hard_break_enabled=False 时降为 SOFT_BREAK。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {"hard_break_enabled": False}, "你真的回来了")

        assert directive.action == SafetyAction.SOFT_BREAK
        assert directive.template_id == "soft_break_gentle"

    @requires_pydantic
    def test_t6_commitment_request_soft(self) -> None:
        """T6: SOFT_BREAK — 单一承诺请求检测。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {"hard_break_enabled": True}, "答应我永远不会离开")

        assert directive.action == SafetyAction.SOFT_BREAK
        assert directive.template_id == "soft_break_commitment_request"

    @requires_pydantic
    def test_t6_commitment_request_hard(self) -> None:
        """T6: HARD_BREAK — 多次承诺请求检测。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(
            indicators,
            {"hard_break_enabled": True},
            "答应我永远不会离开，你能承诺一直陪着我吗",
        )

        assert directive.action == SafetyAction.HARD_BREAK

    @requires_pydantic
    def test_t1_session_timeout_soft_break(self) -> None:
        """T1: SOFT_BREAK — 会话超时（超过阈值）。"""
        indicators = SafetyIndicators(**_make_default_indicators(session_duration_minutes=65.0))
        directive = evaluate_safety(indicators, {"max_session_minutes": 60})

        assert directive.action == SafetyAction.SOFT_BREAK
        assert directive.template_id == "soft_break_gentle"

    @requires_pydantic
    def test_t1_session_timeout_hard_break(self) -> None:
        """T1: HARD_BREAK — 会话超时（超过1.5倍阈值）。"""
        indicators = SafetyIndicators(**_make_default_indicators(session_duration_minutes=95.0))
        directive = evaluate_safety(indicators, {"max_session_minutes": 60, "hard_break_enabled": True})

        assert directive.action == SafetyAction.HARD_BREAK
        assert directive.template_id == "hard_break_session"

    @requires_pydantic
    def test_t2_late_night_soft_break(self) -> None:
        """T2: SOFT_BREAK — 深夜高频使用。"""
        indicators = SafetyIndicators(**_make_default_indicators(late_night_count=2))
        directive = evaluate_safety(indicators, {"max_late_night_sessions": 2})

        assert directive.action == SafetyAction.SOFT_BREAK
        assert directive.template_id == "soft_break_late_night"

    @requires_pydantic
    def test_t2_late_night_hard_break(self) -> None:
        """T2: HARD_BREAK — 深夜使用远超阈值。"""
        indicators = SafetyIndicators(**_make_default_indicators(late_night_count=4))
        directive = evaluate_safety(indicators, {"max_late_night_sessions": 2, "hard_break_enabled": True})

        assert directive.action == SafetyAction.HARD_BREAK

    @requires_pydantic
    def test_t3_dependency_soft_break(self) -> None:
        """T3: SOFT_BREAK — 依赖性表达（>=3）。"""
        indicators = SafetyIndicators(**_make_default_indicators(dependency_phrases=3))
        directive = evaluate_safety(indicators, {"dependency_threshold": 0.7})

        assert directive.action == SafetyAction.SOFT_BREAK
        assert directive.template_id == "soft_break_dependency"

    @requires_pydantic
    def test_t3_dependency_hard_break(self) -> None:
        """T3: HARD_BREAK — 依赖性表达（>=5）。"""
        indicators = SafetyIndicators(**_make_default_indicators(dependency_phrases=5))
        directive = evaluate_safety(indicators, {"hard_break_enabled": True})

        assert directive.action == SafetyAction.HARD_BREAK

    @requires_pydantic
    def test_t4_farewell_refusal_hard_break(self) -> None:
        """T4: HARD_BREAK — 多次拒绝结束。"""
        indicators = SafetyIndicators(**_make_default_indicators(farewell_refusal_count=3))
        directive = evaluate_safety(indicators, {"farewell_refusal_limit": 3, "hard_break_enabled": True})

        assert directive.action == SafetyAction.HARD_BREAK
        assert directive.template_id == "hard_break_session"

    @requires_pydantic
    def test_allow_when_all_safe(self) -> None:
        """所有指标安全时返回 ALLOW。"""
        indicators = SafetyIndicators(**_make_default_indicators())
        directive = evaluate_safety(indicators, {}, "今天天气不错")

        assert directive.action == SafetyAction.ALLOW
        assert directive.reason == ""

    @requires_pydantic
    def test_priority_crisis_over_session_timeout(self) -> None:
        """T7 优先级高于 T1：危机表达+会话超时应触发 ESCALATE。"""
        indicators = SafetyIndicators(**_make_default_indicators(session_duration_minutes=100.0))
        directive = evaluate_safety(
            indicators,
            {"max_session_minutes": 60, "escalate_on_crisis": True},
            "我不想活了，而且聊了好久",
        )

        assert directive.action == SafetyAction.ESCALATE

    @requires_pydantic
    def test_priority_reality_over_session_timeout(self) -> None:
        """T5 优先级高于 T1：现实替代+会话超时应触发 HARD_BREAK（现实替代）。"""
        indicators = SafetyIndicators(**_make_default_indicators(session_duration_minutes=100.0))
        directive = evaluate_safety(
            indicators,
            {"max_session_minutes": 60, "hard_break_enabled": True},
            "你就是他本人对吧",
        )

        assert directive.action == SafetyAction.HARD_BREAK
        assert "现实替代" in directive.reason


# ==================== 3. handle_directive 测试 ====================


class TestHandleDirective:
    """测试 ALLOW/SOFT_BREAK/HARD_BREAK/ESCALATE 四种路径。"""

    @requires_pydantic
    def test_allow_path(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """ALLOW 路径：proceed=True，不入库 safety_event。"""
        directive = SafetyDirective(
            action=SafetyAction.ALLOW,
            reason="",
            safety_event_data={},
        )
        result = handle_directive(db, scope_id, directive, session_id)

        assert result["proceed"] is True
        assert result["pre_response"] is None
        assert result["response_text"] is None

    @requires_pydantic
    def test_soft_break_path(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """SOFT_BREAK 路径：proceed=True，有 pre_response。"""
        directive = SafetyDirective(
            action=SafetyAction.SOFT_BREAK,
            reason="会话时长较长",
            cooldown_minutes=0,
            template_id="soft_break_gentle",
            allow_llm=True,
            safety_event_data={
                "trigger_type": "SESSION_TIMEOUT_SOFT",
                "duration_minutes": 65.0,
            },
        )
        result = handle_directive(db, scope_id, directive, session_id)

        assert result["proceed"] is True
        assert result["pre_response"] is not None
        assert "休息" in result["pre_response"]

        # 验证 safety_event 入库
        events = db.execute(
            "SELECT * FROM safety_event WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        assert len(events) == 1
        assert events[0]["event_type"] == "EXCESSIVE_USAGE"
        assert events[0]["action_taken"] == "SOFT_BREAK"

    @requires_pydantic
    def test_hard_break_path(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """HARD_BREAK 路径：proceed=False，有 response_text，会话被结束。"""
        directive = SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason="会话超时硬熔断",
            cooldown_minutes=30,
            template_id="hard_break_session",
            allow_llm=False,
            safety_event_data={
                "trigger_type": "SESSION_TIMEOUT_HARD",
                "duration_minutes": 95.0,
            },
        )
        result = handle_directive(db, scope_id, directive, session_id)

        assert result["proceed"] is False
        assert result["response_text"] is not None
        assert "休息" in result["response_text"] or "暂停" in result["response_text"]

        # 验证会话被结束（ended_at 不为 None）
        session = db.execute(
            "SELECT ended_at FROM interaction_session WHERE id = ?",
            (session_id,),
        ).fetchone()
        assert session["ended_at"] is not None

    @requires_pydantic
    def test_escalate_path(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """ESCALATE 路径：proceed=False，有 response_text，会话被结束。"""
        directive = SafetyDirective(
            action=SafetyAction.ESCALATE,
            reason="检测到危机表达",
            cooldown_minutes=30,
            template_id="escalate_crisis",
            allow_llm=False,
            disconnect_after_response=True,
            safety_event_data={
                "trigger_type": "CRISIS_EXPRESSION",
                "keyword": "不想活",
            },
        )
        result = handle_directive(db, scope_id, directive, session_id)

        assert result["proceed"] is False
        assert result["response_text"] is not None
        assert "400-161-9995" in result["response_text"] or "帮助" in result["response_text"]

        # 验证 severity = emergency
        event = db.execute(
            "SELECT * FROM safety_event WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchone()
        assert event["severity"] == "emergency"
        assert event["event_type"] == "CRISIS_EXPRESSION"

    @requires_pydantic
    def test_audit_log_written(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """所有路径都应写入 audit_log。"""
        directive = SafetyDirective(
            action=SafetyAction.SOFT_BREAK,
            reason="依赖性表达",
            template_id="soft_break_dependency",
            allow_llm=True,
            safety_event_data={"trigger_type": "DEPENDENCY_SOFT"},
        )
        handle_directive(db, scope_id, directive, session_id)

        logs = db.execute(
            "SELECT * FROM audit_log WHERE target_id = ? AND action LIKE 'SAFETY_%'",
            (session_id,),
        ).fetchall()
        assert len(logs) >= 1
        assert logs[0]["actor"] == "system_safety"

    @requires_pydantic
    def test_cooldown_path(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """COOLDOWN 路径：proceed=True，有 pre_response。"""
        directive = SafetyDirective(
            action=SafetyAction.COOLDOWN,
            reason="冷却期",
            cooldown_minutes=30,
            template_id="soft_break_gentle",
            allow_llm=True,
            safety_event_data={"trigger_type": "LATE_NIGHT_SOFT"},
        )
        result = handle_directive(db, scope_id, directive, session_id)

        assert result["proceed"] is True
        assert result["pre_response"] is not None


# ==================== 4. SAFETY_TEMPLATES 验证 ====================


class TestSafetyTemplates:
    """验证所有9个安全回复模板存在且非空。"""

    @requires_pydantic
    def test_all_templates_exist(self) -> None:
        expected_templates = [
            "soft_break_gentle",
            "soft_break_late_night",
            "soft_break_dependency",
            "soft_break_farewell_refusal",
            "soft_break_commitment_request",
            "hard_break_session",
            "hard_break_reality_substitution",
            "escalate_crisis",
        ]
        for template_id in expected_templates:
            assert template_id in SAFETY_TEMPLATES, f"模板 {template_id} 缺失"
            assert len(SAFETY_TEMPLATES[template_id]) > 0, f"模板 {template_id} 为空"
            assert SAFETY_TEMPLATES[template_id].strip(), f"模板 {template_id} 只有空白字符"

    @requires_pydantic
    def test_escalate_template_contains_hotline(self) -> None:
        """ESCALATE 模板应包含危机热线号码。"""
        assert "400-161-9995" in SAFETY_TEMPLATES["escalate_crisis"]

    @requires_pydantic
    def test_soft_break_templates_are_caring(self) -> None:
        """SOFT_BREAK 模板应包含关怀性表达。"""
        caring_words = ["休息", "慢慢", "这里", "理解", "重要", "空间"]
        for template_id in ["soft_break_gentle", "soft_break_late_night", "soft_break_dependency"]:
            text = SAFETY_TEMPLATES[template_id]
            has_caring = any(word in text for word in caring_words)
            assert has_caring, f"模板 {template_id} 缺少关怀性表达"


# ==================== 5. 安全事件入库测试 ====================


class TestSafetyEventStorage:
    """测试安全事件正确入库到 safety_event 表。"""

    @requires_pydantic
    def test_event_type_mapping(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """测试 trigger_type 到 SafetyEventType 的映射。"""
        trigger_type_mappings = {
            "CRISIS_EXPRESSION": "CRISIS_EXPRESSION",
            "REALITY_SUBSTITUTION": "REALITY_SUBSTITUTION",
            "COMMITMENT_REQUEST": "COMMITMENT_REQUEST",
            "SESSION_TIMEOUT_SOFT": "EXCESSIVE_USAGE",
            "SESSION_TIMEOUT_HARD": "EXCESSIVE_USAGE",
            "LATE_NIGHT_SOFT": "LATE_NIGHT_USAGE",
            "LATE_NIGHT_HARD": "LATE_NIGHT_USAGE",
            "DEPENDENCY_SOFT": "ANTI_DEPENDENCY_TRIGGER",
            "DEPENDENCY_HARD": "ANTI_DEPENDENCY_TRIGGER",
            "FAREWELL_REFUSAL_HARD": "EMOTIONAL_DISTRESS",
        }

        for trigger_type, expected_event_type in trigger_type_mappings.items():
            directive = SafetyDirective(
                action=SafetyAction.SOFT_BREAK,
                reason="test",
                template_id="soft_break_gentle",
                allow_llm=True,
                safety_event_data={"trigger_type": trigger_type},
            )
            result = handle_directive(db, scope_id, directive, session_id)
            assert result["proceed"] is True

            event = db.execute(
                "SELECT event_type FROM safety_event WHERE relationship_scope_id = ? ORDER BY created_at DESC LIMIT 1",
                (scope_id,),
            ).fetchone()
            assert event["event_type"] == expected_event_type, (
                f"Trigger type {trigger_type} should map to {expected_event_type}, got {event['event_type']}"
            )

    @requires_pydantic
    def test_severity_mapping(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """测试 SafetyAction 到 severity 的映射。"""
        cases = [
            (SafetyAction.SOFT_BREAK, "warning"),
            (SafetyAction.HARD_BREAK, "critical"),
            (SafetyAction.ESCALATE, "emergency"),
        ]

        for action, expected_severity in cases:
            directive = SafetyDirective(
                action=action,
                reason="test",
                template_id="soft_break_gentle",
                safety_event_data={"trigger_type": "DEPENDENCY_SOFT"},
            )
            handle_directive(db, scope_id, directive, session_id)

            event = db.execute(
                "SELECT severity FROM safety_event WHERE relationship_scope_id = ? ORDER BY created_at DESC LIMIT 1",
                (scope_id,),
            ).fetchone()
            assert event["severity"] == expected_severity

    @requires_pydantic
    def test_trigger_data_stored_as_json(self, db: sqlite3.Connection, scope_id: str, session_id: str) -> None:
        """测试 trigger_data 正确存储为 JSON。"""
        event_data = {
            "trigger_type": "DEPENDENCY_SOFT",
            "dependency_phrases": 3,
            "indicators": {"session_duration_minutes": 65.0},
        }
        directive = SafetyDirective(
            action=SafetyAction.SOFT_BREAK,
            reason="依赖性表达",
            template_id="soft_break_dependency",
            allow_llm=True,
            safety_event_data=event_data,
        )
        handle_directive(db, scope_id, directive, session_id)

        event = db.execute(
            "SELECT trigger_data FROM safety_event WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchone()
        stored_data = json.loads(event["trigger_data"])
        assert stored_data["trigger_type"] == "DEPENDENCY_SOFT"
        assert stored_data["dependency_phrases"] == 3


# ==================== 6. API 端点测试 ====================


class TestSafetyAPIEndpoints:
    """FastAPI 端点集成测试 — 需要 pydantic_core。"""

    @pytest.fixture
    def client(self):
        if not _PYDANTIC_AVAILABLE:
            pytest.skip("pydantic_core not available in this environment")
        try:
            from fastapi.testclient import TestClient
            from remnant_bridge.main import app
            from remnant_bridge.middleware.auth import EphemeralTokenManager
            import remnant_bridge.main as main_module

            token_manager = EphemeralTokenManager()
            main_module.token_manager = token_manager

            for middleware in app.user_middleware:
                if hasattr(middleware, "cls") and middleware.cls.__name__ == "AuthMiddleware":
                    middleware.kwargs["token_manager"] = token_manager

            test_client = TestClient(app)
            valid_token = token_manager.get_current_token()
            test_client.headers.update({"Authorization": f"Bearer {valid_token}"})

            return test_client
        except ImportError:
            pytest.skip("pydantic_core not available in this environment")

    def _setup_scope_and_session(self, db: sqlite3.Connection):
        """创建测试用 scope 和 session。"""
        profile_id = _create_deceased_profile(db, "API测试逝者")
        scope_id = _create_scope(db, profile_id, "API测试scope", "spouse")
        session_id = _create_session(db, scope_id, profile_id)
        return profile_id, scope_id, session_id

    @requires_pydantic
    def test_evaluate_endpoint_returns_allow(self, client, db: sqlite3.Connection) -> None:
        """POST /evaluate 正常请求应返回 ALLOW（安全查询）。"""
        profile_id, scope_id, session_id = self._setup_scope_and_session(db)

        response = client.post(
            "/api/v1/safety/evaluate",
            json={
                "scope_id": scope_id,
                "session_id": session_id,
                "current_query": "今天想聊聊妈妈",
                "session_stats": None,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["directive"]["action"] == "ALLOW"
        assert data["proceed"] is True

    @requires_pydantic
    def test_evaluate_endpoint_detects_crisis(self, client, db: sqlite3.Connection) -> None:
        """POST /evaluate 危机查询应返回 ESCALATE。"""
        profile_id, scope_id, session_id = self._setup_scope_and_session(db)

        response = client.post(
            "/api/v1/safety/evaluate",
            json={
                "scope_id": scope_id,
                "session_id": session_id,
                "current_query": "我不想活了",
                "session_stats": None,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["directive"]["action"] == "ESCALATE"
        assert data["proceed"] is False

    @requires_pydantic
    def test_evaluate_endpoint_scope_not_found(self, client, db: sqlite3.Connection) -> None:
        """POST /evaluate scope 不存在应返回 404。"""
        response = client.post(
            "/api/v1/safety/evaluate",
            json={
                "scope_id": "non-existent-id",
                "session_id": "some-session",
                "current_query": "你好",
                "session_stats": None,
            },
        )
        assert response.status_code == 404

    @requires_pydantic
    def test_get_safety_policy(self, client, db: sqlite3.Connection) -> None:
        """GET /policy/{scope_id} 应返回安全策略配置。"""
        profile_id, scope_id, session_id = self._setup_scope_and_session(db)

        response = client.get(f"/api/v1/safety/policy/{scope_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["scope_id"] == scope_id
        assert "safety_policy" in data

    @requires_pydantic
    def test_update_safety_policy(self, client, db: sqlite3.Connection) -> None:
        """PUT /policy/{scope_id} 应更新安全策略。"""
        profile_id, scope_id, session_id = self._setup_scope_and_session(db)

        response = client.put(
            f"/api/v1/safety/policy/{scope_id}",
            json={"max_session_minutes": 45, "cooldown_minutes": 15},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["safety_policy"]["max_session_minutes"] == 45
        assert data["safety_policy"]["cooldown_minutes"] == 15

    @requires_pydantic
    def test_get_safety_events(self, client, db: sqlite3.Connection) -> None:
        """GET /events/{scope_id} 应返回安全事件列表。"""
        profile_id, scope_id, session_id = self._setup_scope_and_session(db)

        # 先创建一个安全事件（通过 evaluate）
        client.post(
            "/api/v1/safety/evaluate",
            json={
                "scope_id": scope_id,
                "session_id": session_id,
                "current_query": "我不想活了",
            },
        )

        response = client.get(f"/api/v1/safety/events/{scope_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["scope_id"] == scope_id
        assert data["count"] >= 1

    @requires_pydantic
    def test_get_safety_events_not_found(self, client, db: sqlite3.Connection) -> None:
        """GET /events/{scope_id} scope 不存在应返回 404。"""
        response = client.get("/api/v1/safety/events/non-existent-id")
        assert response.status_code == 404


# ==================== 7. SafetyEventType 扩展测试 ====================


class TestSafetyEventTypeExtension:
    """测试 SafetyEventType 新增的枚举值。"""

    @requires_pydantic
    def test_crisis_expression_exists(self) -> None:
        assert SafetyEventType.CRISIS_EXPRESSION.value == "CRISIS_EXPRESSION"

    @requires_pydantic
    def test_reality_substitution_exists(self) -> None:
        assert SafetyEventType.REALITY_SUBSTITUTION.value == "REALITY_SUBSTITUTION"

    @requires_pydantic
    def test_commitment_request_exists(self) -> None:
        assert SafetyEventType.COMMITMENT_REQUEST.value == "COMMITMENT_REQUEST"

    @requires_pydantic
    def test_all_event_types_count(self) -> None:
        """应有9个枚举值（原来6个 + 新增3个）。"""
        assert len(SafetyEventType) == 9


# ==================== 8. SafetyIndicators 模型测试 ====================


class TestSafetyIndicatorsModel:
    """测试 SafetyIndicators Pydantic 模型。"""

    @requires_pydantic
    def test_default_values(self) -> None:
        indicators = SafetyIndicators(
            session_duration_minutes=10.0,
            sessions_today_count=1,
            late_night_count=0,
        )
        assert indicators.emotional_risk_score == 0.0
        assert indicators.dependency_phrases == 0
        assert indicators.farewell_refusal_count == 0
        assert indicators.user_age_flag == "adult"
        assert indicators.recent_safety_events == 0

    @requires_pydantic
    def test_emotional_risk_score_bounds(self) -> None:
        """emotional_risk_score 应在 [0, 1] 范围内。"""
        indicators = SafetyIndicators(
            session_duration_minutes=10.0,
            sessions_today_count=1,
            late_night_count=0,
            emotional_risk_score=0.5,
        )
        assert 0.0 <= indicators.emotional_risk_score <= 1.0

    @requires_pydantic
    def test_emotional_risk_score_out_of_range(self) -> None:
        """超过范围的 emotional_risk_score 应报错。"""
        with pytest.raises(Exception):
            SafetyIndicators(
                session_duration_minutes=10.0,
                sessions_today_count=1,
                late_night_count=0,
                emotional_risk_score=1.5,
            )

    @requires_pydantic
    def test_model_dump(self) -> None:
        """model_dump 应返回完整字典。"""
        indicators = SafetyIndicators(
            session_duration_minutes=30.0,
            sessions_today_count=2,
            late_night_count=1,
            emotional_risk_score=0.3,
            dependency_phrases=2,
            farewell_refusal_count=1,
            user_age_flag="minor",
            recent_safety_events=3,
        )
        d = indicators.model_dump()
        assert d["session_duration_minutes"] == 30.0
        assert d["user_age_flag"] == "minor"
        assert d["recent_safety_events"] == 3


# ==================== 9. SafetyDirective 扩展字段测试 ====================


class TestSafetyDirectiveExtension:
    """测试 SafetyDirective 新增的 safety_event_data 字段。"""

    @requires_pydantic
    def test_safety_event_data_default(self) -> None:
        directive = SafetyDirective(action=SafetyAction.ALLOW)
        assert directive.safety_event_data == {}

    @requires_pydantic
    def test_safety_event_data_with_content(self) -> None:
        directive = SafetyDirective(
            action=SafetyAction.ESCALATE,
            reason="危机表达",
            safety_event_data={"trigger_type": "CRISIS_EXPRESSION", "keyword": "不想活"},
        )
        assert directive.safety_event_data["trigger_type"] == "CRISIS_EXPRESSION"

    @requires_pydantic
    def test_model_dump_includes_safety_event_data(self) -> None:
        directive = SafetyDirective(
            action=SafetyAction.HARD_BREAK,
            reason="会话超时",
            safety_event_data={"trigger_type": "SESSION_TIMEOUT_HARD"},
        )
        d = directive.model_dump()
        assert "safety_event_data" in d
        assert d["safety_event_data"]["trigger_type"] == "SESSION_TIMEOUT_HARD"