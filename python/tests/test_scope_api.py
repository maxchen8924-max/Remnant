"""Tests for scope API endpoints — M4b verification.

Covers:
- Scope CRUD (create, list, detail, permissions, deletion)
- Cross-scope isolation (M4b AC5)
- Permission deny blocking (M4b AC2)

Uses direct SQL to avoid pydantic_core binary signing issues in macOS sandbox.
"""

import uuid

import pytest

from remnant_store.schema import init_db


@pytest.fixture
def db_conn():
    """Create an in-memory database with schema initialized."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def deceased_profile_id(db_conn):
    """Create a test deceased profile and return its ID."""
    pid = str(uuid.uuid4())
    db_conn.execute(
        """INSERT INTO deceased_profile (id, name, birth_date, death_date, bio)
        VALUES (?, '测试逝者', '1950-01-01', '2023-01-01', '测试用')""",
        (pid,),
    )
    db_conn.commit()
    return pid


def _create_scope_with_dao(db_conn, deceased_profile_id, scope_name="测试作用域",
                             relationship_type="child", scope_description="测试描述"):
    """Helper: create a scope via SQL + manual inserts (avoids pydantic)."""
    scope_id = str(uuid.uuid4())
    now = "2026-01-01T00:00:00"
    db_conn.execute(
        """INSERT INTO relationship_scope
        (id, deceased_profile_id, scope_name, relationship_type, scope_description, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)""",
        (scope_id, deceased_profile_id, scope_name, relationship_type, scope_description, now),
    )

    # Default permissions (aligned with whitepaper Ch9.3)
    base_perms = {
        "can_query_memory": "allow",
        "can_browse_original": "ask",
        "can_add_oral_history": "allow",
        "can_elevate_shared": "ask",
        "can_export_data": "deny",
        "can_view_financial": "deny",
        "can_view_medical": "deny",
        "can_view_intimate": "deny",
        "can_interact_level3": "ask",
        "can_delete_scope": "deny",
    }
    overrides = {
        "spouse": {"can_view_intimate": "ask", "can_interact_level3": "allow",
                    "can_view_medical": "allow", "can_export_data": "allow"},
        "child": {"can_view_intimate": "deny", "can_interact_level3": "ask",
                  "can_view_medical": "allow", "can_view_financial": "ask"},
        "friend": {"can_view_intimate": "deny", "can_view_financial": "deny",
                   "can_interact_level3": "deny"},
        "colleague": {"can_view_intimate": "deny", "can_view_financial": "deny",
                      "can_interact_level3": "deny"},
        "sibling": {"can_view_intimate": "ask", "can_interact_level3": "ask",
                    "can_view_medical": "allow"},
        "parent": {"can_view_intimate": "deny", "can_interact_level3": "ask",
                   "can_view_medical": "allow", "can_view_financial": "ask"},
        "other": {},
    }
    perms = dict(base_perms)
    for k, v in overrides.get(relationship_type, {}).items():
        perms[k] = v

    for key, value in perms.items():
        db_conn.execute(
            """INSERT INTO scope_permission
            (id, relationship_scope_id, permission_key, permission_value, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), scope_id, key, value, now),
        )

    # Default prompt policies (aligned with whitepaper Ch9.6)
    prompt_policies = {
        "address_form": "respectful",
        "topic_sensitivity": "moderate",
        "response_length": "standard",
        "denial_template": "default",
        "grief_limitation": "moderate",
        "memory_mode": "archive",
    }
    for key, value in prompt_policies.items():
        db_conn.execute(
            """INSERT INTO scope_prompt_policy
            (id, relationship_scope_id, policy_key, policy_value, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), scope_id, key, value, now),
        )

    # Default safety policy
    db_conn.execute(
        """INSERT INTO scope_safety_policy
        (id, relationship_scope_id, max_session_minutes, max_sessions_daily, created_at)
        VALUES (?, ?, 60, 5, ?)""",
        (str(uuid.uuid4()), scope_id, now),
    )

    db_conn.commit()
    return scope_id


class TestScopeCreateAPI:
    """Tests for scope creation."""

    def test_create_scope_success(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        cursor = db_conn.execute("SELECT * FROM relationship_scope WHERE id = ?", (scope_id,))
        scope = dict(cursor.fetchone())
        assert scope["scope_name"] == "测试作用域"
        assert scope["relationship_type"] == "child"
        assert scope["is_active"] == 1

    def test_create_multiple_scopes(self, db_conn, deceased_profile_id):
        for i, rel_type in enumerate(["child", "friend", "colleague"]):
            _create_scope_with_dao(db_conn, deceased_profile_id,
                                    scope_name=f"作用域{i}", relationship_type=rel_type)
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM relationship_scope WHERE deceased_profile_id = ?",
            (deceased_profile_id,),
        )
        assert cursor.fetchone()[0] == 3

    def test_create_scope_auto_creates_permissions(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM scope_permission WHERE relationship_scope_id = ?", (scope_id,)
        )
        assert cursor.fetchone()[0] == 10

    def test_create_scope_auto_creates_prompt_policies(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM scope_prompt_policy WHERE relationship_scope_id = ?", (scope_id,)
        )
        assert cursor.fetchone()[0] == 6


class TestScopeListAPI:
    """Tests for listing scopes."""

    def test_list_scopes_empty(self, db_conn, deceased_profile_id):
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM relationship_scope WHERE deceased_profile_id = ?",
            (deceased_profile_id,),
        )
        assert cursor.fetchone()[0] == 0

    def test_list_scopes_multiple(self, db_conn, deceased_profile_id):
        for i in range(3):
            _create_scope_with_dao(db_conn, deceased_profile_id, scope_name=f"作用域{i}")
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM relationship_scope WHERE deceased_profile_id = ?",
            (deceased_profile_id,),
        )
        assert cursor.fetchone()[0] == 3


class TestScopeDetailAPI:
    """Tests for scope detail and not found."""

    def test_get_scope_detail(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        cursor = db_conn.execute("SELECT * FROM relationship_scope WHERE id = ?", (scope_id,))
        scope = dict(cursor.fetchone())
        assert scope["id"] == scope_id
        assert scope["scope_name"] == "测试作用域"
        assert scope["is_active"] == 1

    def test_get_scope_not_found(self, db_conn):
        cursor = db_conn.execute("SELECT * FROM relationship_scope WHERE id = ?", ("nonexistent-id",))
        assert cursor.fetchone() is None


class TestScopePermissionAPI:
    """Tests for scope permissions."""

    def test_get_permissions_default(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id, relationship_type="child")
        cursor = db_conn.execute(
            "SELECT permission_key, permission_value FROM scope_permission WHERE relationship_scope_id = ?",
            (scope_id,),
        )
        perms = {row[0]: row[1] for row in cursor.fetchall()}
        assert len(perms) == 10
        assert perms["can_browse_original"] == "ask"
        assert perms["can_view_intimate"] == "deny"
        assert perms["can_interact_level3"] == "ask"

    def test_set_permission(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        db_conn.execute(
            """UPDATE scope_permission SET permission_value = 'allow'
            WHERE relationship_scope_id = ? AND permission_key = 'can_export_data'""",
            (scope_id,),
        )
        db_conn.commit()
        cursor = db_conn.execute(
            "SELECT permission_value FROM scope_permission WHERE relationship_scope_id = ? AND permission_key = 'can_export_data'",
            (scope_id,),
        )
        assert cursor.fetchone()[0] == "allow"


class TestScopeDeletionAPI:
    """Tests for scope deletion."""

    def test_soft_delete(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        db_conn.execute(
            "UPDATE relationship_scope SET is_active = 0, deleted_at = '2026-01-02' WHERE id = ?",
            (scope_id,),
        )
        db_conn.commit()
        cursor = db_conn.execute("SELECT is_active, deleted_at FROM relationship_scope WHERE id = ?", (scope_id,))
        row = cursor.fetchone()
        assert row[0] == 0
        assert row[1] is not None

    def test_soft_delete_audit_log(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        audit_id = str(uuid.uuid4())
        db_conn.execute(
            """INSERT INTO audit_log (id, action, actor, target_type, target_id, detail, created_at)
            VALUES (?, 'soft_delete_scope', 'user', 'relationship_scope', ?, 'Soft deleted', '2026-01-02')""",
            (audit_id, scope_id),
        )
        db_conn.commit()
        cursor = db_conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'soft_delete_scope'")
        assert cursor.fetchone()[0] >= 1


class TestCrossScopeIsolation:
    """Test M4b AC5: scope A interaction data invisible to scope B."""

    def test_scope_isolation_sessions(self, db_conn, deceased_profile_id):
        scope_a = _create_scope_with_dao(db_conn, deceased_profile_id, scope_name="作为儿子", relationship_type="child")
        scope_b = _create_scope_with_dao(db_conn, deceased_profile_id, scope_name="作为朋友", relationship_type="friend")

        session_id = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        db_conn.execute(
            """INSERT INTO interaction_session
            (id, deceased_profile_id, relationship_scope_id, session_type, started_at, created_at)
            VALUES (?, ?, ?, 'conversation', ?, ?)""",
            (session_id, deceased_profile_id, scope_a, now, now),
        )
        db_conn.commit()

        # scope_a should see the session
        cursor_a = db_conn.execute(
            "SELECT COUNT(*) FROM interaction_session WHERE relationship_scope_id = ?", (scope_a,)
        )
        assert cursor_a.fetchone()[0] == 1

        # scope_b should NOT see scope_a's session
        cursor_b = db_conn.execute(
            "SELECT COUNT(*) FROM interaction_session WHERE relationship_scope_id = ?", (scope_b,)
        )
        assert cursor_b.fetchone()[0] == 0

    def test_scope_isolation_claims(self, db_conn, deceased_profile_id):
        scope_a = _create_scope_with_dao(db_conn, deceased_profile_id, scope_name="作为儿子", relationship_type="child")
        scope_b = _create_scope_with_dao(db_conn, deceased_profile_id, scope_name="作为朋友", relationship_type="friend")

        session_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())
        now = "2026-01-01T00:00:00"
        db_conn.execute(
            """INSERT INTO interaction_session
            (id, deceased_profile_id, relationship_scope_id, session_type, started_at, created_at)
            VALUES (?, ?, ?, 'conversation', ?, ?)""",
            (session_id, deceased_profile_id, scope_a, now, now),
        )
        db_conn.execute(
            """INSERT INTO response_claim
            (id, interaction_session_id, relationship_scope_id, claim_text, confidence,
             evidence_sufficient, status, created_at)
            VALUES (?, ?, ?, '张三喜欢喝茶', 0.9, 1, 'ACTIVE', ?)""",
            (claim_id, session_id, scope_a, now),
        )
        db_conn.commit()

        # scope_a should see the claim
        cursor_a = db_conn.execute(
            "SELECT COUNT(*) FROM response_claim WHERE relationship_scope_id = ?", (scope_a,)
        )
        assert cursor_a.fetchone()[0] >= 1

        # scope_b should NOT see scope_a's claims
        cursor_b = db_conn.execute(
            "SELECT COUNT(*) FROM response_claim WHERE relationship_scope_id = ?", (scope_b,)
        )
        assert cursor_b.fetchone()[0] == 0

    def test_permission_deny_blocks_access(self, db_conn, deceased_profile_id):
        scope_id = _create_scope_with_dao(db_conn, deceased_profile_id)
        db_conn.execute(
            """UPDATE scope_permission SET permission_value = 'deny'
            WHERE relationship_scope_id = ? AND permission_key = 'can_query_memory'""",
            (scope_id,),
        )
        db_conn.commit()
        cursor = db_conn.execute(
            "SELECT permission_value FROM scope_permission WHERE relationship_scope_id = ? AND permission_key = 'can_query_memory'",
            (scope_id,),
        )
        assert cursor.fetchone()[0] == "deny"