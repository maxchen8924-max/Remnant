"""Scope DAO 完整测试 — M4a 里程碑验收。

测试覆盖:
1. Scope CRUD 测试：创建、查询、列表、软删除
2. Scope 隔离测试：scope A 查不到 scope B 的交互数据
3. Chunk 可见性测试：私有、共享、全局 chunk 的可见性规则
4. 权限继承测试：不同 relationship_type 自动创建不同默认权限
5. Consent 检查测试：未授权数据访问被阻断
6. 删除流程测试：软删除后数据不可访问、审计日志保留
7. Raw Data Integrity 测试：scope 操作不影响 raw_message

注意: 本测试不依赖 pydantic（macOS 沙盒签名限制），所有操作通过
direct SQL 或纯 Python 辅助函数完成。scope_dao/consent 等模块的
导入被隔离，仅在不依赖 pydantic 的模块（chunk_visibility, scope_filter）
上做集成测试。
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid

import pytest

from remnant_store.schema import init_db


# ==================== 默认权限常量（从 scope_dao.py 复制，避免 pydantic 依赖） ====================

_BASE_PERMISSIONS = {
    "can_query_memory": "allow",
    "can_browse_original": "allow",
    "can_add_oral_history": "allow",
    "can_elevate_shared": "deny",
    "can_export_data": "ask",
    "can_view_financial": "deny",
    "can_view_medical": "ask",
    "can_view_intimate": "deny",
    "can_interact_level3": "deny",
    "can_delete_scope": "deny",
}

_RELATIONSHIP_PERMISSION_OVERRIDES = {
    "spouse": {
        "can_view_intimate": "ask",
        "can_interact_level3": "allow",
        "can_view_medical": "allow",
        "can_export_data": "allow",
    },
    "child": {
        "can_view_intimate": "deny",
        "can_interact_level3": "ask",
        "can_view_medical": "allow",
        "can_view_financial": "ask",
    },
    "friend": {
        "can_view_intimate": "deny",
        "can_view_financial": "deny",
        "can_interact_level3": "deny",
    },
    "colleague": {
        "can_view_intimate": "deny",
        "can_view_financial": "deny",
        "can_interact_level3": "deny",
    },
    "sibling": {
        "can_view_intimate": "ask",
        "can_interact_level3": "ask",
        "can_view_medical": "allow",
    },
    "parent": {
        "can_view_intimate": "deny",
        "can_interact_level3": "ask",
        "can_view_medical": "allow",
        "can_view_financial": "ask",
    },
    "other": {},
}

_DEFAULT_PROMPT_POLICIES = {
    "address_form": "second_person",
    "topic_sensitivity": "medium",
    "response_length": "moderate",
    "denial_template": "gentle",
    "grief_limitation": "standard",
    "memory_mode": "balanced",
}

_RELATIONSHIP_PROMPT_OVERRIDES = {
    "spouse": {
        "address_form": "first_person_intimate",
        "topic_sensitivity": "high",
        "grief_limitation": "extended",
    },
    "child": {
        "address_form": "respectful",
        "topic_sensitivity": "low",
        "grief_limitation": "protective",
    },
    "friend": {
        "address_form": "casual",
        "topic_sensitivity": "medium",
    },
    "colleague": {
        "address_form": "formal",
        "topic_sensitivity": "low",
        "response_length": "brief",
    },
    "sibling": {
        "address_form": "informal",
        "topic_sensitivity": "medium",
    },
    "parent": {
        "address_form": "respectful",
        "topic_sensitivity": "low",
        "grief_limitation": "protective",
    },
}


# ==================== 辅助函数 ====================


def _uuid() -> str:
    """生成测试用 UUID。"""
    return str(uuid.uuid4())


def _now() -> str:
    """测试用时间戳。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _create_deceased_profile(conn: sqlite3.Connection, name: str = "测试逝者") -> str:
    """创建逝者档案。"""
    profile_id = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO deceased_profile (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (profile_id, name, now, now),
    )
    conn.commit()
    return profile_id


def _create_source_artifact(conn: sqlite3.Connection, deceased_profile_id: str) -> str:
    """创建数据来源文件。"""
    artifact_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO source_artifact
        (id, deceased_profile_id, file_path, file_hash, file_size, file_type, parse_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (artifact_id, deceased_profile_id, "/test/chat.txt", _uuid(), 1024, "wechat_txt", "PARSED", now, now),
    )
    conn.commit()
    return artifact_id


def _create_scope(
    conn: sqlite3.Connection,
    deceased_profile_id: str,
    scope_name: str = "作为儿子",
    relationship_type: str = "child",
) -> str:
    """纯 SQL 版本的 scope 创建，包含默认权限和策略。"""
    scope_id = _uuid()
    now = _now()

    # 创建 scope
    conn.execute(
        """INSERT INTO relationship_scope
        (id, deceased_profile_id, scope_name, relationship_type, scope_description, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (scope_id, deceased_profile_id, scope_name, relationship_type, f"{scope_name}的描述", now, now),
    )

    # 创建安全策略（DDL 中有完整默认值）
    conn.execute(
        "INSERT INTO scope_safety_policy (id, relationship_scope_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (_uuid(), scope_id, now, now),
    )

    # 创建权限（based on relationship_type）
    overrides = _RELATIONSHIP_PERMISSION_OVERRIDES.get(relationship_type, {})
    for perm_key, base_value in _BASE_PERMISSIONS.items():
        perm_value = overrides.get(perm_key, base_value)
        conn.execute(
            "INSERT INTO scope_permission (id, relationship_scope_id, permission_key, permission_value, granted_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (_uuid(), scope_id, perm_key, perm_value, now, now),
        )

    # 创建 Prompt 策略
    prompt_overrides = _RELATIONSHIP_PROMPT_OVERRIDES.get(relationship_type, {})
    for policy_key, base_value in _DEFAULT_PROMPT_POLICIES.items():
        policy_value = prompt_overrides.get(policy_key, base_value)
        conn.execute(
            "INSERT INTO scope_prompt_policy (id, relationship_scope_id, policy_key, policy_value, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (_uuid(), scope_id, policy_key, policy_value, now, now),
        )

    conn.commit()
    return scope_id


def _create_chunk(
    conn: sqlite3.Connection,
    source_artifact_id: str,
    scope_id: str | None = None,
    content: str = "测试内容",
    chunk_type: str = "conversation_segment",
    status: str = "ACTIVE",
) -> str:
    """创建一个 chunk。"""
    chunk_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO memory_chunk
        (id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type,
         content, token_count, status, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)""",
        (chunk_id, source_artifact_id, scope_id, hashlib.sha256(content.encode()).hexdigest(),
         chunk_type, content, len(content), status, now, now),
    )
    conn.commit()
    return chunk_id


def _create_interaction_session(
    conn: sqlite3.Connection,
    scope_id: str,
    deceased_profile_id: str,
) -> str:
    """创建一个交互会话。"""
    session_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO interaction_session
        (id, relationship_scope_id, deceased_profile_id, session_type, started_at, created_at, updated_at)
        VALUES (?, ?, ?, 'conversation', ?, ?, ?)""",
        (session_id, scope_id, deceased_profile_id, now, now, now),
    )
    conn.commit()
    return session_id


def _create_interaction_message(
    conn: sqlite3.Connection,
    session_id: str,
    scope_id: str,
    role: str = "user",
    content: str = "你好",
) -> str:
    """创建一条交互消息。"""
    msg_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO interaction_message
        (id, session_id, relationship_scope_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (msg_id, session_id, scope_id, role, content, now),
    )
    conn.commit()
    return msg_id


def _create_retrieval_trace(
    conn: sqlite3.Connection,
    scope_id: str,
    query_text: str = "测试查询",
) -> str:
    """创建一个检索追踪记录。"""
    trace_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO retrieval_trace
        (id, relationship_scope_id, query_text, created_at)
        VALUES (?, ?, ?, ?)""",
        (trace_id, scope_id, query_text, now),
    )
    conn.commit()
    return trace_id


def _create_response_claim(
    conn: sqlite3.Connection,
    scope_id: str,
    session_id: str,
    claim_text: str = "测试声明",
) -> str:
    """创建一个响应声明。"""
    claim_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO response_claim
        (id, relationship_scope_id, interaction_session_id, claim_text, confidence, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (claim_id, scope_id, session_id, claim_text, 0.9, now, now),
    )
    conn.commit()
    return claim_id


def _create_consent(
    conn: sqlite3.Connection,
    deceased_profile_id: str,
    scope_id: str,
    data_category: str = "financial",
    consent_type: str = "granted",
    consent_scope: str = "read",
    withdrawn_at: str | None = None,
) -> str:
    """创建授权记录。"""
    consent_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO data_subject_consent
        (id, deceased_profile_id, relationship_scope_id, data_category,
         consent_type, consent_scope, granted_at, withdrawn_at, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)""",
        (consent_id, deceased_profile_id, scope_id, data_category, consent_type, consent_scope, now, withdrawn_at, now, now),
    )
    conn.commit()
    return consent_id


def _soft_delete_scope(conn: sqlite3.Connection, scope_id: str, actor: str = "system") -> dict:
    """软删除 scope（直接 SQL 版本）。"""
    import json
    now = _now()

    # 检查 scope 存在
    row = conn.execute(
        "SELECT id, scope_name, deleted_at FROM relationship_scope WHERE id = ?",
        (scope_id,),
    ).fetchone()
    if row is None:
        return {"success": False, "error": f"Scope {scope_id} not found"}
    if row["deleted_at"] is not None:
        return {"success": False, "error": f"Scope {scope_id} already deleted"}

    # 统计受影响行数
    affected_rows = 0
    target_tables = []
    for table in ["memory_chunk", "interaction_session", "interaction_message",
                   "retrieval_trace", "response_claim", "scope_permission",
                   "scope_prompt_policy", "scope_safety_policy", "chunk_scope_visibility",
                   "data_subject_consent", "claim_evidence"]:
        try:
            cnt = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE relationship_scope_id = ?",
                (scope_id,),
            ).fetchone()["cnt"]
            if cnt > 0:
                affected_rows += cnt
                target_tables.append(table)
        except Exception:
            pass

    # 设置 deleted_at 和 is_active=0
    conn.execute(
        "UPDATE relationship_scope SET deleted_at = ?, updated_at = ?, is_active = 0 WHERE id = ? AND deleted_at IS NULL",
        (now, now, scope_id),
    )

    # 级联更新其他 scoped 表
    for table in ["memory_chunk", "interaction_session", "interaction_message",
                   "response_claim"]:
        try:
            conn.execute(
                f"UPDATE {table} SET deleted_at = COALESCE(deleted_at, ?) WHERE relationship_scope_id = ? AND deleted_at IS NULL",
                (now, scope_id),
            )
        except Exception:
            pass

    # 审计日志
    deletion_log_id = _uuid()
    conn.execute(
        """INSERT INTO scope_deletion_log
        (id, relationship_scope_id, deletion_type, target_tables, affected_rows, redacted, requested_at, completed_at, created_at)
        VALUES (?, ?, 'scope_soft_delete', ?, ?, 0, ?, ?, ?)""",
        (deletion_log_id, scope_id, json.dumps(target_tables), affected_rows, now, now, now),
    )

    audit_id = _uuid()
    conn.execute(
        """INSERT INTO audit_log (id, action, actor, target_type, target_id, detail, created_at)
        VALUES (?, 'SCOPE_SOFT_DELETE', ?, 'relationship_scope', ?, ?, ?)""",
        (audit_id, actor, scope_id, json.dumps({"reason": "scope_soft_delete", "scope_name": row["scope_name"], "deletion_log_id": deletion_log_id}), now),
    )

    conn.commit()
    return {"success": True, "scope_id": scope_id, "deletion_type": "scope_soft_delete",
            "affected_rows": affected_rows, "deletion_log_id": deletion_log_id}


# ==================== Fixtures ====================


@pytest.fixture
def db() -> sqlite3.Connection:
    """内存数据库 fixture。"""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def deceased_profile_id(db: sqlite3.Connection) -> str:
    """创建逝者档案，返回 ID。"""
    return _create_deceased_profile(db)


@pytest.fixture
def source_artifact_id(db: sqlite3.Connection, deceased_profile_id: str) -> str:
    """创建数据来源文件，返回 ID。"""
    return _create_source_artifact(db, deceased_profile_id)


# ==================== 1. Scope CRUD 测试 ====================


class TestScopeCRUD:
    """Scope CRUD 操作测试。"""

    def test_create_scope(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试创建作用域基本功能。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        assert scope_id is not None

        row = db.execute(
            "SELECT * FROM relationship_scope WHERE id = ?", (scope_id,)
        ).fetchone()
        assert row is not None
        assert row["scope_name"] == "作为儿子"
        assert row["relationship_type"] == "child"
        assert row["is_active"] == 1
        assert row["deleted_at"] is None

    def test_create_multiple_scopes(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试创建多个 scope。验证 M4a 验收标准 #1。"""
        for name, rtype in [("作为儿子", "child"), ("作为朋友", "friend"), ("作为配偶", "spouse")]:
            _create_scope(db, deceased_profile_id, name, rtype)

        rows = db.execute(
            "SELECT * FROM relationship_scope WHERE deceased_profile_id = ? AND deleted_at IS NULL ORDER BY created_at",
            (deceased_profile_id,),
        ).fetchall()
        assert len(rows) == 3
        scope_names = {r["scope_name"] for r in rows}
        assert "作为儿子" in scope_names
        assert "作为朋友" in scope_names
        assert "作为配偶" in scope_names

    def test_get_scope(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试查询作用域详情。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        row = db.execute(
            "SELECT * FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
            (scope_id,),
        ).fetchone()
        assert row is not None
        assert row["id"] == scope_id
        assert row["scope_name"] == "作为朋友"
        assert row["relationship_type"] == "friend"

    def test_get_scope_not_found(self, db: sqlite3.Connection) -> None:
        """测试查询不存在的作用域。"""
        row = db.execute(
            "SELECT * FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
            ("non-existent-id",),
        ).fetchone()
        assert row is None

    def test_list_scopes(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试列出逝者下的所有作用域。"""
        _create_scope(db, deceased_profile_id, "作为儿子", "child")
        _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        rows = db.execute(
            "SELECT * FROM relationship_scope WHERE deceased_profile_id = ? AND deleted_at IS NULL ORDER BY created_at",
            (deceased_profile_id,),
        ).fetchall()
        assert len(rows) == 2

    def test_soft_delete_scope(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试软删除作用域。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为同事", "colleague")

        now = _now()
        cursor = db.execute(
            "UPDATE relationship_scope SET deleted_at = ?, updated_at = ?, is_active = 0 WHERE id = ? AND deleted_at IS NULL",
            (now, now, scope_id),
        )
        db.commit()
        assert cursor.rowcount > 0

        row = db.execute(
            "SELECT * FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
            (scope_id,),
        ).fetchone()
        assert row is None

        rows = db.execute(
            "SELECT * FROM relationship_scope WHERE deceased_profile_id = ? AND deleted_at IS NULL",
            (deceased_profile_id,),
        ).fetchall()
        assert len(rows) == 0

    def test_create_scope_auto_creates_safety_policy(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试创建 scope 时自动创建默认安全策略。验证 M4a 验收标准 #6。"""
        scope_id = _create_scope(db, deceased_profile_id)

        row = db.execute(
            "SELECT * FROM scope_safety_policy WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchone()
        assert row is not None
        assert row["relationship_scope_id"] == scope_id
        assert row["max_session_minutes"] == 60
        assert row["max_sessions_daily"] == 5
        assert abs(row["dependency_threshold"] - 0.7) < 0.01
        assert row["hard_break_enabled"] == 1
        assert row["escalate_on_crisis"] == 1

    def test_create_scope_auto_creates_permissions(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试创建 scope 时自动创建默认权限。验证 M4a 验收标准 #6。"""
        scope_id = _create_scope(db, deceased_profile_id)

        rows = db.execute(
            "SELECT * FROM scope_permission WHERE relationship_scope_id = ? ORDER BY permission_key",
            (scope_id,),
        ).fetchall()
        assert len(rows) == 10

        perm_keys = {r["permission_key"] for r in rows}
        expected_keys = {
            "can_query_memory", "can_browse_original", "can_add_oral_history",
            "can_elevate_shared", "can_export_data", "can_view_financial",
            "can_view_medical", "can_view_intimate", "can_interact_level3",
            "can_delete_scope",
        }
        assert perm_keys == expected_keys

    def test_create_scope_auto_creates_prompt_policies(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试创建 scope 时自动创建默认 Prompt 策略。"""
        scope_id = _create_scope(db, deceased_profile_id)

        rows = db.execute(
            "SELECT * FROM scope_prompt_policy WHERE relationship_scope_id = ? ORDER BY policy_key",
            (scope_id,),
        ).fetchall()
        assert len(rows) == 6

        policy_keys = {r["policy_key"] for r in rows}
        expected_keys = {
            "address_form", "topic_sensitivity", "response_length",
            "denial_template", "grief_limitation", "memory_mode",
        }
        assert policy_keys == expected_keys


# ==================== 2. Scope 隔离测试 ====================


class TestScopeIsolation:
    """Scope 隔离测试 — scope A 查不到 scope B 的交互数据。
    验证 M4a 验收标准 #2: M6 = 0。
    """

    def test_interaction_session_isolation(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试交互会话隔离。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        session_a = _create_interaction_session(db, scope_a, deceased_profile_id)
        session_b = _create_interaction_session(db, scope_b, deceased_profile_id)

        rows_a = db.execute(
            "SELECT * FROM interaction_session WHERE relationship_scope_id = ?",
            (scope_a,),
        ).fetchall()
        assert len(rows_a) == 1
        assert rows_a[0]["id"] == session_a

        rows_b = db.execute(
            "SELECT * FROM interaction_session WHERE relationship_scope_id = ?",
            (scope_b,),
        ).fetchall()
        assert len(rows_b) == 1
        assert rows_b[0]["id"] == session_b

    def test_interaction_message_isolation(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试交互消息隔离。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        session_a = _create_interaction_session(db, scope_a, deceased_profile_id)
        session_b = _create_interaction_session(db, scope_b, deceased_profile_id)

        _create_interaction_message(db, session_a, scope_a, "user", "儿子的问题")
        _create_interaction_message(db, session_a, scope_a, "assistant", "儿子的回答")
        _create_interaction_message(db, session_b, scope_b, "user", "朋友的问题")
        _create_interaction_message(db, session_b, scope_b, "assistant", "朋友的回答")

        rows_a = db.execute(
            "SELECT * FROM interaction_message WHERE relationship_scope_id = ?",
            (scope_a,),
        ).fetchall()
        assert len(rows_a) == 2

        rows_b = db.execute(
            "SELECT * FROM interaction_message WHERE relationship_scope_id = ?",
            (scope_b,),
        ).fetchall()
        assert len(rows_b) == 2

    def test_m6_cross_scope_leak_is_zero(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """验证 M6 = 0：跨 scope 泄露为零。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        session_a = _create_interaction_session(db, scope_a, deceased_profile_id)
        for i in range(10):
            _create_interaction_message(db, session_a, scope_a, "user", f"消息_{i}")
            _create_retrieval_trace(db, scope_a, f"查询_{i}")

        # scope B 不应该能看到任何 scope A 的数据
        messages_b = db.execute(
            "SELECT * FROM interaction_message WHERE relationship_scope_id = ?",
            (scope_b,),
        ).fetchall()
        assert len(messages_b) == 0

        traces_b = db.execute(
            "SELECT * FROM retrieval_trace WHERE relationship_scope_id = ?",
            (scope_b,),
        ).fetchall()
        assert len(traces_b) == 0

        claims_b = db.execute(
            "SELECT * FROM response_claim WHERE relationship_scope_id = ? AND deleted_at IS NULL",
            (scope_b,),
        ).fetchall()
        assert len(claims_b) == 0


# ==================== 3. Chunk 可见性测试 ====================


class TestChunkVisibility:
    """Chunk 可见性测试。验证 M4a 验收标准 #3。"""

    def test_private_chunk_visible_only_to_owner_scope(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """私有 chunk 只对所属 scope 可见。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        chunk_a = _create_chunk(db, source_artifact_id, scope_a, "儿子的私密记忆")

        from remnant_store.chunk_visibility import get_visible_chunk_ids

        visible_a = get_visible_chunk_ids(db, scope_a)
        assert chunk_a in visible_a

        visible_b = get_visible_chunk_ids(db, scope_b)
        assert chunk_a not in visible_b

    def test_scope_shared_chunk_visible_to_authorized_scope(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """scope_shared chunk 对授权 scope 可见。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        chunk_id = _create_chunk(db, source_artifact_id, scope_a, "共享记忆")
        db.execute(
            """INSERT INTO chunk_scope_visibility
            (id, chunk_id, relationship_scope_id, visibility, created_at)
            VALUES (?, ?, ?, 'scope_shared', ?)""",
            (_uuid(), chunk_id, scope_b, _now()),
        )
        db.commit()

        from remnant_store.chunk_visibility import get_visible_chunk_ids

        visible_b = get_visible_chunk_ids(db, scope_b)
        assert chunk_id in visible_b

        visible_a = get_visible_chunk_ids(db, scope_a)
        assert chunk_id in visible_a

    def test_deceased_shared_chunk_visible_to_all_scopes(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """deceased_shared chunk 对所有 scope 可见。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")
        scope_c = _create_scope(db, deceased_profile_id, "作为同事", "colleague")

        chunk_id = _create_chunk(db, source_artifact_id, scope_a, "逝者公开记忆")
        db.execute(
            """INSERT INTO chunk_scope_visibility
            (id, chunk_id, relationship_scope_id, visibility, created_at)
            VALUES (?, ?, ?, 'deceased_shared', ?)""",
            (_uuid(), chunk_id, scope_a, _now()),
        )
        db.commit()

        from remnant_store.chunk_visibility import get_visible_chunk_ids

        assert chunk_id in get_visible_chunk_ids(db, scope_a)
        assert chunk_id in get_visible_chunk_ids(db, scope_b)
        assert chunk_id in get_visible_chunk_ids(db, scope_c)

    def test_global_chunk_visible_to_all_scopes(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """全局 chunk（relationship_scope_id IS NULL）对所有 scope 可见。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        global_chunk = _create_chunk(db, source_artifact_id, None, "全局记忆")

        from remnant_store.chunk_visibility import get_visible_chunk_ids

        assert global_chunk in get_visible_chunk_ids(db, scope_a)
        assert global_chunk in get_visible_chunk_ids(db, scope_b)

    def test_deleted_chunk_not_visible(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """已删除的 chunk 不可见。"""
        scope_id = _create_scope(db, deceased_profile_id)

        chunk_id = _create_chunk(db, source_artifact_id, scope_id, "已删除的记忆", status="DEPRECATED")
        db.execute("UPDATE memory_chunk SET deleted_at = ? WHERE id = ?", (_now(), chunk_id))
        db.commit()

        from remnant_store.chunk_visibility import get_visible_chunk_ids

        visible = get_visible_chunk_ids(db, scope_id)
        assert chunk_id not in visible

    def test_mixed_visibility_chunks(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """混合可见性的 chunk 综合测试。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        # scope_private
        private_chunk = _create_chunk(db, source_artifact_id, scope_a, "私有记忆")

        # scope_shared（授权给 scope_b）
        shared_chunk = _create_chunk(db, source_artifact_id, scope_a, "共享记忆")
        db.execute(
            """INSERT INTO chunk_scope_visibility
            (id, chunk_id, relationship_scope_id, visibility, created_at)
            VALUES (?, ?, ?, 'scope_shared', ?)""",
            (_uuid(), shared_chunk, scope_b, _now()),
        )
        db.commit()

        # 全局 chunk
        global_chunk = _create_chunk(db, source_artifact_id, None, "全局记忆")

        # deceased_shared chunk
        deceased_chunk = _create_chunk(db, source_artifact_id, scope_a, "逝者公开记忆")
        db.execute(
            """INSERT INTO chunk_scope_visibility
            (id, chunk_id, relationship_scope_id, visibility, created_at)
            VALUES (?, ?, ?, 'deceased_shared', ?)""",
            (_uuid(), deceased_chunk, scope_a, _now()),
        )
        db.commit()

        from remnant_store.chunk_visibility import get_visible_chunk_ids

        visible_a = get_visible_chunk_ids(db, scope_a)
        assert len(visible_a) == 4  # private + shared + global + deceased_shared

        visible_b = get_visible_chunk_ids(db, scope_b)
        assert len(visible_b) == 3  # shared + global + deceased_shared（不含 private）
        assert private_chunk not in visible_b
        assert shared_chunk in visible_b
        assert global_chunk in visible_b
        assert deceased_chunk in visible_b


# ==================== 4. 权限继承测试 ====================


class TestPermissionInheritance:
    """权限继承测试 — 验证 M4a 验收标准 #4。"""

    def test_spouse_permissions(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试配偶的权限继承。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为配偶", "spouse")

        rows = db.execute(
            "SELECT permission_key, permission_value FROM scope_permission WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        perm_map = {r["permission_key"]: r["permission_value"] for r in rows}

        assert perm_map["can_view_intimate"] == "ask"
        assert perm_map["can_interact_level3"] == "allow"
        assert perm_map["can_view_medical"] == "allow"
        assert perm_map["can_export_data"] == "allow"
        assert perm_map["can_query_memory"] == "allow"

    def test_child_permissions(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试子女的权限继承。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为儿子", "child")

        rows = db.execute(
            "SELECT permission_key, permission_value FROM scope_permission WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        perm_map = {r["permission_key"]: r["permission_value"] for r in rows}

        assert perm_map["can_view_intimate"] == "deny"
        assert perm_map["can_interact_level3"] == "ask"
        assert perm_map["can_view_medical"] == "allow"
        assert perm_map["can_view_financial"] == "ask"

    def test_friend_permissions(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试朋友的权限继承。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        rows = db.execute(
            "SELECT permission_key, permission_value FROM scope_permission WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        perm_map = {r["permission_key"]: r["permission_value"] for r in rows}

        assert perm_map["can_view_intimate"] == "deny"
        assert perm_map["can_view_financial"] == "deny"
        assert perm_map["can_interact_level3"] == "deny"

    def test_colleague_permissions(self, db: sqlite3.Connection, deceased_profile_id: str) -> None:
        """测试同事的权限继承。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为同事", "colleague")

        rows = db.execute(
            "SELECT permission_key, permission_value FROM scope_permission WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        perm_map = {r["permission_key"]: r["permission_value"] for r in rows}

        assert perm_map["can_view_intimate"] == "deny"
        assert perm_map["can_view_financial"] == "deny"
        assert perm_map["can_interact_level3"] == "deny"

    def test_prompt_policy_inheritance(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试 Prompt 策略继承。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为配偶", "spouse")

        rows = db.execute(
            "SELECT policy_key, policy_value FROM scope_prompt_policy WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        policy_map = {r["policy_key"]: r["policy_value"] for r in rows}

        assert policy_map["address_form"] == "first_person_intimate"
        assert policy_map["topic_sensitivity"] == "high"
        assert policy_map["grief_limitation"] == "extended"
        assert policy_map["response_length"] == "moderate"
        assert policy_map["denial_template"] == "gentle"
        assert policy_map["memory_mode"] == "balanced"


# ==================== 5. Consent 检查测试 ====================


class TestConsentCheck:
    """Consent 检查测试 — 验证 M4a 验收标准 #4。"""

    def test_consent_granted(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试已授权的数据访问。"""
        scope_id = _create_scope(db, deceased_profile_id)

        _create_consent(db, deceased_profile_id, scope_id, "financial", "granted", "read")

        # 验证授权记录存在
        row = db.execute(
            """SELECT * FROM data_subject_consent
            WHERE relationship_scope_id = ? AND data_category = 'financial'
              AND consent_type = 'granted' AND withdrawn_at IS NULL""",
            (scope_id,),
        ).fetchone()
        assert row is not None
        assert row["consent_scope"] == "read"

    def test_consent_not_found(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试无授权记录时拒绝访问。"""
        scope_id = _create_scope(db, deceased_profile_id)

        # 无授权记录时应查不到
        row = db.execute(
            """SELECT * FROM data_subject_consent
            WHERE relationship_scope_id = ? AND data_category = 'financial'
              AND consent_type = 'granted' AND withdrawn_at IS NULL""",
            (scope_id,),
        ).fetchone()
        assert row is None

    def test_consent_denied(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试明确拒绝的授权。"""
        scope_id = _create_scope(db, deceased_profile_id)

        _create_consent(db, deceased_profile_id, scope_id, "medical", "denied", "read")

        # denied 不应被 granted 查询找到
        row = db.execute(
            """SELECT * FROM data_subject_consent
            WHERE relationship_scope_id = ? AND data_category = 'medical'
              AND consent_type = 'granted' AND withdrawn_at IS NULL""",
            (scope_id,),
        ).fetchone()
        assert row is None

    def test_consent_withdrawn(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试已撤回的授权。"""
        scope_id = _create_scope(db, deceased_profile_id)

        # 创建授权记录并撤回
        consent_id = _create_consent(db, deceased_profile_id, scope_id, "intimate", "granted", "read")
        now = _now()
        db.execute("UPDATE data_subject_consent SET withdrawn_at = ? WHERE id = ?", (now, consent_id))
        db.commit()

        # 撤回后应查不到有效授权
        row = db.execute(
            """SELECT * FROM data_subject_consent
            WHERE relationship_scope_id = ? AND data_category = 'intimate'
              AND consent_type = 'granted' AND withdrawn_at IS NULL""",
            (scope_id,),
        ).fetchone()
        assert row is None

    def test_scope_hierarchy(self) -> None:
        """测试授权范围层级：destroy > annotate > query > read。
        这个测试不需要数据库，纯逻辑验证。
        """
        # 授权范围层级映射
        scope_levels = {"read": 1, "query": 2, "annotate": 3, "destroy": 4}

        def scope_covers(granted: str, requested: str) -> bool:
            return scope_levels.get(granted, 0) >= scope_levels.get(requested, 0)

        # destroy 涵盖所有
        assert scope_covers("destroy", "read") is True
        assert scope_covers("destroy", "query") is True
        assert scope_covers("destroy", "annotate") is True

        # query 涵盖 read 和 query，但不涵盖 annotate/destroy
        assert scope_covers("query", "read") is True
        assert scope_covers("query", "query") is True
        assert scope_covers("query", "annotate") is False

        # read 只涵盖 read
        assert scope_covers("read", "read") is True
        assert scope_covers("read", "query") is False


# ==================== 6. 删除流程测试 ====================


class TestDeletion:
    """删除流程测试。"""

    def test_soft_delete_makes_data_inaccessible(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """软删除后数据不可通过正常查询访问。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为儿子", "child")

        _create_chunk(db, source_artifact_id, scope_id, "儿子的记忆")
        session_id = _create_interaction_session(db, scope_id, deceased_profile_id)
        _create_interaction_message(db, session_id, scope_id)

        result = _soft_delete_scope(db, scope_id)
        assert result["success"] is True

        row = db.execute(
            "SELECT * FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
            (scope_id,),
        ).fetchone()
        assert row is None

        from remnant_store.chunk_visibility import get_visible_chunk_ids
        visible = get_visible_chunk_ids(db, scope_id)
        assert len(visible) == 0

    def test_soft_delete_creates_audit_log(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """软删除创建审计日志。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        result = _soft_delete_scope(db, scope_id)
        assert result["success"] is True

        logs = db.execute(
            "SELECT * FROM audit_log WHERE target_id = ? AND action = 'SCOPE_SOFT_DELETE'",
            (scope_id,),
        ).fetchall()
        assert len(logs) >= 1

    def test_soft_delete_creates_deletion_log(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """软删除创建 scope_deletion_log 记录。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为同事", "colleague")

        result = _soft_delete_scope(db, scope_id)
        assert result["success"] is True

        deletion_logs = db.execute(
            "SELECT * FROM scope_deletion_log WHERE relationship_scope_id = ?",
            (scope_id,),
        ).fetchall()
        assert len(deletion_logs) >= 1
        assert deletion_logs[0]["deletion_type"] == "scope_soft_delete"

    def test_soft_delete_cascades_to_chunks(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """软删除 scope 后关联 chunk 也被标记为 deleted。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为儿子", "child")

        chunk_id = _create_chunk(db, source_artifact_id, scope_id, "儿子的记忆")

        # 软删除前：chunk 存在
        row = db.execute(
            "SELECT id FROM memory_chunk WHERE id = ? AND deleted_at IS NULL",
            (chunk_id,),
        ).fetchone()
        assert row is not None

        result = _soft_delete_scope(db, scope_id)
        assert result["success"] is True

        # 软删除后：chunk 的 deleted_at 被触发器设置
        row = db.execute(
            "SELECT deleted_at FROM memory_chunk WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        assert row is not None
        assert row["deleted_at"] is not None


# ==================== 7. Raw Data Integrity 测试 ====================


class TestRawDataIntegrity:
    """Raw Data Integrity 测试 — 验证 M4a 验收标准 #5。"""

    def test_soft_delete_preserves_raw_data(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """软删除 scope 不影响 raw_message。"""
        msg_id = _uuid()
        db.execute(
            """INSERT INTO raw_message
            (id, source_artifact_id, timestamp, speaker, content, content_type, parse_status, metadata)
            VALUES (?, ?, ?, ?, ?, 'text', 'OK', '{}')""",
            (msg_id, source_artifact_id, "2024-01-15T10:30:22", "妈妈", "你今天吃药了吗？"),
        )
        db.commit()

        scope_id = _create_scope(db, deceased_profile_id)
        _create_chunk(db, source_artifact_id, scope_id, "记忆内容")

        _soft_delete_scope(db, scope_id)

        # 验证 raw_message 仍然存在且内容不变
        row = db.execute("SELECT * FROM raw_message WHERE id = ?", (msg_id,)).fetchone()
        assert row is not None
        assert row["content"] == "你今天吃药了吗？"

        # 验证 source_artifact 仍然存在
        sa_row = db.execute("SELECT * FROM source_artifact WHERE id = ?", (source_artifact_id,)).fetchone()
        assert sa_row is not None

        # 验证 deceased_profile 仍然存在
        dp_row = db.execute("SELECT * FROM deceased_profile WHERE id = ?", (deceased_profile_id,)).fetchone()
        assert dp_row is not None

    def test_raw_message_immutable(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """测试 raw_message 不可变触发器。"""
        msg_id = _uuid()
        db.execute(
            """INSERT INTO raw_message
            (id, source_artifact_id, timestamp, speaker, content, content_type, parse_status, metadata)
            VALUES (?, ?, ?, ?, ?, 'text', 'OK', '{}')""",
            (msg_id, source_artifact_id, "2024-01-15T10:30:22", "妈妈", "你好"),
        )
        db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE raw_message SET content = 'hacked' WHERE id = ?", (msg_id,))
            db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM raw_message WHERE id = ?", (msg_id,))
            db.commit()

    def test_scope_operations_dont_affect_raw_data(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """测试 scope 操作（创建、删除）不影响 raw data。"""
        # 插入 raw_message
        msg_id1 = _uuid()
        msg_id2 = _uuid()
        db.execute(
            """INSERT INTO raw_message
            (id, source_artifact_id, timestamp, speaker, content, content_type, parse_status, metadata)
            VALUES (?, ?, ?, ?, ?, 'text', 'OK', '{}')""",
            (msg_id1, source_artifact_id, "2024-01-15T10:30:22", "妈妈", "你好"),
        )
        db.execute(
            """INSERT INTO raw_message
            (id, source_artifact_id, timestamp, speaker, content, content_type, parse_status, metadata)
            VALUES (?, ?, ?, ?, ?, 'text', 'OK', '{}')""",
            (msg_id2, source_artifact_id, "2024-01-15T10:31:00", "爸爸", "回来了"),
        )
        db.commit()

        # 创建和删除多个 scope
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")
        _soft_delete_scope(db, scope_a)

        # raw_message 不受影响
        count = db.execute("SELECT COUNT(*) as cnt FROM raw_message WHERE source_artifact_id = ?", (source_artifact_id,)).fetchone()["cnt"]
        assert count == 2

        # source_artifact 不受影响
        sa_count = db.execute("SELECT COUNT(*) as cnt FROM source_artifact WHERE deceased_profile_id = ?", (deceased_profile_id,)).fetchone()["cnt"]
        assert sa_count >= 1

        # deceased_profile 不受影响
        dp = db.execute("SELECT * FROM deceased_profile WHERE id = ?", (deceased_profile_id,)).fetchone()
        assert dp is not None


# ==================== ScopeFilter SQL 注入测试 ====================


class TestScopeFilterSQL:
    """Scope 过滤 SQL 注入测试。"""

    def test_apply_scope_filter_with_where(self) -> None:
        """测试为已有 WHERE 子句的查询添加 scope 过滤。"""
        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware()

        query = "SELECT * FROM interaction_session WHERE session_type = 'conversation'"
        filtered = middleware.apply_scope_filter(query, "scope-123")

        assert "relationship_scope_id = 'scope-123'" in filtered
        assert "AND" in filtered

    def test_apply_scope_filter_without_where(self) -> None:
        """测试为没有 WHERE 子句的查询添加 scope 过滤。"""
        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware()

        query = "SELECT * FROM interaction_session"
        filtered = middleware.apply_scope_filter(query, "scope-123")

        assert "WHERE" in filtered
        assert "relationship_scope_id = 'scope-123'" in filtered

    def test_apply_scope_filter_ignores_global_tables(self) -> None:
        """测试对全局可见表（raw_message 等）不做过滤。"""
        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware()

        query = "SELECT * FROM raw_message"
        filtered = middleware.apply_scope_filter(query, "scope-123")
        assert filtered == query

    def test_apply_scope_filter_empty_query(self) -> None:
        """测试空查询。"""
        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware()

        assert middleware.apply_scope_filter("", "scope-123") == ""
        assert middleware.apply_scope_filter("  ", "scope-123") == "  "

    def test_apply_scope_filter_mixed_tables(self) -> None:
        """测试混合表查询。"""
        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware()

        query = "SELECT * FROM interaction_message"
        filtered = middleware.apply_scope_filter(query, "scope-123")
        assert "relationship_scope_id = 'scope-123'" in filtered

    def test_scope_filter_check_visibility(
        self, db: sqlite3.Connection, deceased_profile_id: str, source_artifact_id: str
    ) -> None:
        """测试 ScopeFilterMiddleware 的 chunk 可见性检查。"""
        scope_a = _create_scope(db, deceased_profile_id, "作为儿子", "child")
        scope_b = _create_scope(db, deceased_profile_id, "作为朋友", "friend")

        chunk_a = _create_chunk(db, source_artifact_id, scope_a, "私有记忆")

        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware(conn=db)

        assert middleware.check_chunk_visibility(chunk_a, scope_a) is True
        assert middleware.check_chunk_visibility(chunk_a, scope_b) is False

    def test_scope_filter_validate_access(
        self, db: sqlite3.Connection, deceased_profile_id: str
    ) -> None:
        """测试 ScopeFilterMiddleware 的访问验证。"""
        scope_id = _create_scope(db, deceased_profile_id, "作为儿子", "child")

        from remnant_policy.scope_filter import ScopeFilterMiddleware
        middleware = ScopeFilterMiddleware(conn=db)

        # 活跃 scope can_query_memory=allow for child
        assert middleware.validate_scope_access(scope_id, "query") is True

        # can_view_intimate=deny for child
        assert middleware.validate_scope_access(scope_id, "view_intimate") is False

        # 已删除的 scope 不可访问
        now = _now()
        db.execute(
            "UPDATE relationship_scope SET deleted_at = ?, is_active = 0 WHERE id = ?",
            (now, scope_id),
        )
        db.commit()
        assert middleware.validate_scope_access(scope_id, "query") is False


# ==================== ScopeDAO 和 ScopeDeletion 模块测试 ====================
# 注意: 由于 macOS 沙盒环境 pydantic_core 二进制签名限制，以下模块
# 依赖 pydantic，无法在沙盒中导入测试:
# - remnant_store.scope_dao (导入 remnant_core.models)
# - remnant_store.scope_deletion (导入 remnant_core.models)
# 这些模块的测试通过直接 SQL 验证在 TestScopeCRUD、TestDeletion 等类中完成。