"""Consent 检查 — 数据主体授权验证。

负责在访问数据前检查 data_subject_consent 表:
- 验证数据类别是否已授权
- 验证授权是否过期
- 验证授权范围（read / query / annotate / destroy）
"""

from __future__ import annotations

import sqlite3
from typing import Any

from remnant_core.models import ConsentScope, ConsentType, DataCategory


class ConsentChecker:
    """授权检查器 — 在数据访问前验证授权。"""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn

    async def check(
        self,
        scope_id: str,
        data_category: DataCategory,
        consent_scope: ConsentScope,
    ) -> bool:
        """检查指定作用域下某数据类别的授权状态。

        验证逻辑:
        1. 在 data_subject_consent 表中查找匹配的记录
        2. consent_type 必须为 'granted'
        3. consent_scope 必须包含请求的权限范围
        4. withdrawn_at 必须为 NULL（未撤回）
        5. expires_at 必须为 NULL 或未过期

        Args:
            scope_id: 关系作用域 ID
            data_category: 数据类别
            consent_scope: 请求的授权范围

        Returns:
            True 如果授权有效，False 如果未授权或已撤回/过期
        """
        if self.conn is None:
            return True

        # 查找匹配的授权记录
        cursor = self.conn.execute(
            """SELECT id, consent_type, consent_scope, withdrawn_at, expires_at
            FROM data_subject_consent
            WHERE relationship_scope_id = ?
              AND data_category = ?
              AND consent_type = 'granted'
              AND withdrawn_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1""",
            (scope_id, data_category.value),
        )
        row = cursor.fetchone()

        if row is None:
            return False

        # 检查授权范围是否满足请求
        if not self._scope_covers(row["consent_scope"], consent_scope):
            return False

        # 检查是否过期
        if row["expires_at"] is not None:
            from datetime import datetime, timezone
            try:
                expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                if expires < datetime.now(timezone.utc):
                    return False
            except (ValueError, AttributeError):
                pass  # 无法解析过期时间，视为未过期

        return True

    async def is_expired(self, consent_id: str) -> bool:
        """检查授权是否已过期。

        Args:
            consent_id: data_subject_consent 的 ID

        Returns:
            True 如果已过期或已撤回
        """
        if self.conn is None:
            return False

        cursor = self.conn.execute(
            "SELECT withdrawn_at, expires_at FROM data_subject_consent WHERE id = ?",
            (consent_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return True  # 不存在的记录视为无效

        # 已撤回 = 过期
        if row["withdrawn_at"] is not None:
            return True

        # 检查过期时间
        if row["expires_at"] is not None:
            from datetime import datetime, timezone
            try:
                expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                return expires < datetime.now(timezone.utc)
            except (ValueError, AttributeError):
                return False

        return False

    async def get_consents(
        self, scope_id: str
    ) -> list[dict[str, Any]]:
        """获取指定作用域的所有授权记录。

        Args:
            scope_id: 关系作用域 ID

        Returns:
            授权记录字典列表
        """
        if self.conn is None:
            return []

        cursor = self.conn.execute(
            "SELECT * FROM data_subject_consent WHERE relationship_scope_id = ? ORDER BY created_at",
            (scope_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    async def grant_consent(
        self,
        scope_id: str,
        deceased_profile_id: str,
        data_category: str,
        consent_type: str = "granted",
        consent_scope: str = "read",
        consent_evidence: str | None = None,
    ) -> str:
        """授予数据授权。

        Args:
            scope_id: 关系作用域 ID
            deceased_profile_id: 逝者档案 ID
            data_category: 数据类别
            consent_type: 授权类型 (granted/denied/withdrawn)
            consent_scope: 授权范围 (read/query/annotate/destroy)
            consent_evidence: 授权证据

        Returns:
            授权记录 ID
        """
        if self.conn is None:
            raise RuntimeError("数据库连接不可用")

        import uuid
        from datetime import datetime, timezone

        consent_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        self.conn.execute(
            """INSERT INTO data_subject_consent
            (id, deceased_profile_id, relationship_scope_id, data_category,
             consent_type, consent_scope, granted_at, consent_evidence,
             metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)""",
            (
                consent_id,
                deceased_profile_id,
                scope_id,
                data_category,
                consent_type,
                consent_scope,
                now,
                consent_evidence,
                now,
                now,
            ),
        )
        self.conn.commit()
        return consent_id

    @staticmethod
    def _scope_covers(
        granted_scope: str,
        requested_scope: ConsentScope,
    ) -> bool:
        """检查已授权范围是否覆盖请求的范围。

        授权范围层级: destroy > annotate > query > read
        高层级范围隐含低层级范围。

        Args:
            granted_scope: 已授权的范围字符串
            requested_scope: 请求的授权范围枚举值

        Returns:
            True 如果已授权范围覆盖请求范围
        """
        # 权限层级映射（数值越大权限越高）
        scope_levels = {
            "read": 1,
            "query": 2,
            "annotate": 3,
            "destroy": 4,
        }

        granted_level = scope_levels.get(granted_scope, 0)
        requested_level = scope_levels.get(requested_scope.value, 0)

        return granted_level >= requested_level