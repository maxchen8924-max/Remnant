"""Scope DAO — 关系作用域数据访问层。

负责 relationship_scope 及其关联表的 CRUD 操作:
- 创建/查询/软删除作用域
- 作用域权限配置管理（基于 relationship_type 自动继承默认权限）
- Prompt 策略配置管理
- 安全策略配置管理
- 作用域列表查询
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from remnant_core.models import (
    ScopeCreateRequest,
    ScopeDeletionLogSchema,
    ScopePermissionSchema,
    ScopePromptPolicySchema,
    ScopeSafetyPolicySchema,
)


def _generate_uuid_v7() -> str:
    """生成 UUID v7（基于时间戳）。

    简化实现：使用 uuid4 替代，M1 阶段替换为真正的 UUID v7。
    """
    return str(uuid.uuid4())


def _utcnow_iso() -> str:
    """获取当前 UTC 时间的 ISO 8601 格式字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ==================== 默认权限继承映射 ====================

# 10 个 permission_key 的基础默认值（无特殊关系类型时使用）
_BASE_PERMISSIONS: dict[str, str] = {
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

# 关系类型特定的权限覆盖
_RELATIONSHIP_PERMISSION_OVERRIDES: dict[str, dict[str, str]] = {
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

# 6 个 prompt policy_key 的默认值
_DEFAULT_PROMPT_POLICIES: dict[str, str] = {
    "address_form": "second_person",
    "topic_sensitivity": "medium",
    "response_length": "moderate",
    "denial_template": "gentle",
    "grief_limitation": "standard",
    "memory_mode": "balanced",
}

# 关系类型特定的 prompt policy 覆盖
_RELATIONSHIP_PROMPT_OVERRIDES: dict[str, dict[str, str]] = {
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


class ScopeDAO:
    """关系作用域数据访问对象。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ==================== Scope CRUD ====================

    def create_scope(self, request: ScopeCreateRequest) -> str:
        """创建关系作用域，同时自动创建默认权限和策略配置。

        Args:
            request: 创建请求

        Returns:
            新创建的 relationship_scope ID
        """
        scope_id = _generate_uuid_v7()
        now = _utcnow_iso()

        self.conn.execute(
            """INSERT INTO relationship_scope
            (id, deceased_profile_id, scope_name, relationship_type, scope_description, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                scope_id,
                request.deceased_profile_id,
                request.scope_name,
                request.relationship_type.value,
                request.scope_description,
                now,
                now,
            ),
        )

        # 创建默认安全策略（DDL 中有完整默认值）
        self.conn.execute(
            """INSERT INTO scope_safety_policy
            (id, relationship_scope_id, created_at, updated_at)
            VALUES (?, ?, ?, ?)""",
            (_generate_uuid_v7(), scope_id, now, now),
        )

        # 创建默认权限配置（基于 relationship_type 继承）
        relationship_type = request.relationship_type.value
        overrides = _RELATIONSHIP_PERMISSION_OVERRIDES.get(relationship_type, {})
        for perm_key, base_value in _BASE_PERMISSIONS.items():
            perm_value = overrides.get(perm_key, base_value)
            self.conn.execute(
                """INSERT INTO scope_permission
                (id, relationship_scope_id, permission_key, permission_value, granted_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (_generate_uuid_v7(), scope_id, perm_key, perm_value, now, now),
            )

        # 创建默认 Prompt 策略配置（基于 relationship_type 继承）
        prompt_overrides = _RELATIONSHIP_PROMPT_OVERRIDES.get(relationship_type, {})
        for policy_key, base_value in _DEFAULT_PROMPT_POLICIES.items():
            policy_value = prompt_overrides.get(policy_key, base_value)
            self.conn.execute(
                """INSERT INTO scope_prompt_policy
                (id, relationship_scope_id, policy_key, policy_value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (_generate_uuid_v7(), scope_id, policy_key, policy_value, now, now),
            )

        self.conn.commit()
        return scope_id

    def get_scope(self, scope_id: str) -> dict[str, Any] | None:
        """查询作用域详情。

        Args:
            scope_id: 作用域 ID

        Returns:
            作用域字典（sqlite3.Row），不存在返回 None
        """
        cursor = self.conn.execute(
            "SELECT * FROM relationship_scope WHERE id = ? AND deleted_at IS NULL",
            (scope_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_scopes(self, deceased_profile_id: str) -> list[dict[str, Any]]:
        """列出逝者下所有活跃作用域。

        Args:
            deceased_profile_id: 逝者档案 ID

        Returns:
            作用域字典列表
        """
        cursor = self.conn.execute(
            "SELECT * FROM relationship_scope WHERE deceased_profile_id = ? AND deleted_at IS NULL ORDER BY created_at",
            (deceased_profile_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def soft_delete_scope(self, scope_id: str) -> bool:
        """软删除作用域（触发器自动级联到关联 scoped 数据）。

        Args:
            scope_id: 作用域 ID

        Returns:
            True 如果成功
        """
        now = _utcnow_iso()
        cursor = self.conn.execute(
            "UPDATE relationship_scope SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now, now, scope_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # ==================== 权限配置 ====================

    def set_permission(
        self, scope_id: str, permission_key: str, permission_value: str
    ) -> str:
        """设置作用域权限。

        Args:
            scope_id: 作用域 ID
            permission_key: 权限键名
            permission_value: 权限值 (allow / deny / ask)

        Returns:
            权限记录 ID
        """
        perm_id = _generate_uuid_v7()
        now = _utcnow_iso()

        self.conn.execute(
            """INSERT OR REPLACE INTO scope_permission
            (id, relationship_scope_id, permission_key, permission_value, granted_at, updated_at)
            VALUES (
                COALESCE((SELECT id FROM scope_permission WHERE relationship_scope_id = ? AND permission_key = ?), ?),
                ?, ?, ?, ?, ?
            )""",
            (scope_id, permission_key, perm_id, scope_id, permission_key, permission_value, now, now),
        )
        self.conn.commit()
        return perm_id

    def get_permissions(self, scope_id: str) -> list[dict[str, Any]]:
        """获取作用域全部权限配置。

        Args:
            scope_id: 作用域 ID

        Returns:
            权限字典列表
        """
        cursor = self.conn.execute(
            "SELECT * FROM scope_permission WHERE relationship_scope_id = ? ORDER BY permission_key",
            (scope_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def check_permission(self, scope_id: str, permission_key: str) -> str | None:
        """检查作用域特定权限值。

        Args:
            scope_id: 作用域 ID
            permission_key: 权限键名

        Returns:
            权限值 (allow/deny/ask)，不存在返回 None
        """
        cursor = self.conn.execute(
            "SELECT permission_value FROM scope_permission WHERE relationship_scope_id = ? AND permission_key = ?",
            (scope_id, permission_key),
        )
        row = cursor.fetchone()
        return row["permission_value"] if row else None

    # ==================== 安全策略 ====================

    def get_safety_policy(self, scope_id: str) -> dict[str, Any] | None:
        """获取作用域安全策略。

        Args:
            scope_id: 作用域 ID

        Returns:
            安全策略字典，不存在返回 None
        """
        cursor = self.conn.execute(
            "SELECT * FROM scope_safety_policy WHERE relationship_scope_id = ?",
            (scope_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    # ==================== Prompt 策略 ====================

    def get_prompt_policies(self, scope_id: str) -> list[dict[str, Any]]:
        """获取作用域 Prompt 策略列表。

        Args:
            scope_id: 作用域 ID

        Returns:
            Prompt 策略字典列表
        """
        cursor = self.conn.execute(
            "SELECT * FROM scope_prompt_policy WHERE relationship_scope_id = ? ORDER BY policy_key",
            (scope_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def set_prompt_policy(
        self, scope_id: str, policy_key: str, policy_value: str
    ) -> str:
        """设置作用域 Prompt 策略。

        Args:
            scope_id: 作用域 ID
            policy_key: 策略键名
            policy_value: 策略值

        Returns:
            策略记录 ID
        """
        policy_id = _generate_uuid_v7()
        now = _utcnow_iso()

        self.conn.execute(
            """INSERT OR REPLACE INTO scope_prompt_policy
            (id, relationship_scope_id, policy_key, policy_value, created_at, updated_at)
            VALUES (
                COALESCE((SELECT id FROM scope_prompt_policy WHERE relationship_scope_id = ? AND policy_key = ?), ?),
                ?, ?, ?, ?, ?
            )""",
            (scope_id, policy_key, policy_id, scope_id, policy_key, policy_value, now, now),
        )
        self.conn.commit()
        return policy_id