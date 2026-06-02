"""Consent 检查骨架 — 数据主体授权验证。

负责在访问数据前检查 data_subject_consent 表:
- 验证数据类别是否已授权
- 验证授权是否过期
- 验证授权范围（read / query / annotate / destroy）
"""

from __future__ import annotations

from typing import Any

from remnant_core.models import ConsentScope, ConsentType, DataCategory


class ConsentChecker:
    """授权检查器 — 在数据访问前验证授权。"""

    def __init__(self, db: Any = None) -> None:
        self.db = db

    async def check(
        self,
        scope_id: str,
        data_category: DataCategory,
        consent_scope: ConsentScope,
    ) -> bool:
        """检查指定作用域下某数据类别的授权状态。

        Args:
            scope_id: 关系作用域 ID
            data_category: 数据类别
            consent_scope: 请求的授权范围

        Returns:
            True 如果授权有效，False 如果未授权或已撤回
        """
        if self.db is None:
            return True

        # M1 阶段实现数据库查询
        return True

    async def is_expired(self, consent_id: str) -> bool:
        """检查授权是否已过期。

        Args:
            consent_id: data_subject_consent 的 ID

        Returns:
            True 如果已过期
        """
        if self.db is None:
            return False

        # M1 阶段实现数据库查询
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
        if self.db is None:
            return []

        # M1 阶段实现数据库查询
        return []