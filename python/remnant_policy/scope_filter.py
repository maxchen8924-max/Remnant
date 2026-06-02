"""Scope 过滤中间件 — 确保查询严格隔离。

核心职责:
1. 所有查询必须携带 scope_id，强制 WHERE scope_id = :scope_id
2. 防止跨 scope 数据泄露
3. 对共享 chunk 验证 chunk_scope_visibility 权限
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

# scope-private 的表：必须严格按 relationship_scope_id 过滤
_SCOPED_TABLES = frozenset({
    "interaction_session",
    "interaction_message",
    "retrieval_trace",
    "response_claim",
    "claim_evidence",
})

# 全局可见的表（只读，无 scope 过滤需要）
_GLOBAL_TABLES = frozenset({
    "deceased_profile",
    "source_artifact",
    "raw_message",
    "normalized_message",
})


class ScopeFilterMiddleware:
    """Scope 过滤中间件 — 确保所有数据查询按作用域隔离。"""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn

    def apply_scope_filter(
        self,
        query: str,
        scope_id: str,
    ) -> str:
        """为 SQL 查询注入 scope 过滤条件。

        只对 scoped 表（interaction_session, interaction_message,
        retrieval_trace, response_claim, claim_evidence）的查询添加
        relationship_scope_id 过滤。对全局可见表不做过滤。

        Args:
            query: 原始 SQL 查询
            scope_id: 关系作用域 ID

        Returns:
            添加了 scope 过滤条件的 SQL 查询
        """
        if not query or not query.strip():
            return query

        # 检测查询中涉及的 scoped 表
        detected_scoped_tables = set()
        for table in _SCOPED_TABLES:
            # 匹配表名（FROM/JOIN 后面），使用 \b 确保完整单词匹配
            pattern = rf'\b{table}\b'
            if re.search(pattern, query, re.IGNORECASE):
                detected_scoped_tables.add(table)

        if not detected_scoped_tables:
            return query

        # 构建 scope 过滤条件（使用 ? 参数占位符，防止 SQL 注入）
        # 注意：此方法返回修改后的 SQL 字符串，调用方需自行传递 scope_id 参数
        scope_condition = "relationship_scope_id = ?"

        # 尝试在 WHERE 子句中添加过滤条件
        where_match = re.search(r'\bWHERE\b', query, re.IGNORECASE)
        if where_match:
            # 已有 WHERE 子句，追加 AND 条件
            insert_pos = where_match.end()
            query = query[:insert_pos] + f" ({scope_condition}) AND" + query[insert_pos:]
        else:
            # 没有 WHERE 子句，需要找到合适的位置插入
            # 在 FROM/JOIN 子句之后，ORDER BY/GROUP BY/LIMIT 之前
            for keyword in ["ORDER BY", "GROUP BY", "LIMIT", "HAVING"]:
                match = re.search(rf'\b{keyword}\b', query, re.IGNORECASE)
                if match:
                    insert_pos = match.start()
                    query = query[:insert_pos] + f" WHERE {scope_condition}" + query[insert_pos:]
                    return query

            # 没有特殊子句，直接追加到末尾
            query = query.rstrip(';').rstrip() + f" WHERE {scope_condition}"

        return query

    def check_chunk_visibility(
        self,
        chunk_id: str,
        scope_id: str,
    ) -> bool:
        """检查 chunk 在指定 scope 下是否可见。

        可见性矩阵:
        1. scope_private chunk: 仅所属 scope 可见
        2. scope_shared chunk: chunk_scope_visibility 中有记录的 scope 可见
        3. deceased_shared chunk: 所有 scope 可见
        4. 全局 chunk (relationship_scope_id IS NULL): 所有 scope 可见

        Args:
            chunk_id: 记忆分块 ID
            scope_id: 关系作用域 ID

        Returns:
            True 如果 chunk 在此 scope 下可见
        """
        if self.conn is None:
            return True

        # 查询 chunk 信息
        cursor = self.conn.execute(
            "SELECT id, relationship_scope_id, status FROM memory_chunk WHERE id = ? AND deleted_at IS NULL",
            (chunk_id,),
        )
        chunk = cursor.fetchone()
        if chunk is None:
            return False

        # 非 ACTIVE 状态的 chunk 不可见
        if chunk["status"] != "ACTIVE":
            return False

        # 全局 chunk（relationship_scope_id IS NULL）对所有 scope 可见
        if chunk["relationship_scope_id"] is None:
            return True

        # 私有 chunk: 仅所属 scope 可见
        # 首先检查 chunk_scope_visibility 表中是否有记录
        vis_cursor = self.conn.execute(
            "SELECT visibility FROM chunk_scope_visibility WHERE chunk_id = ?",
            (chunk_id,),
        )
        vis_rows = vis_cursor.fetchall()

        # 如果有可见性记录，根据 visibility 判断
        if len(vis_rows) > 0:
            for vis_row in vis_rows:
                if vis_row["visibility"] == "deceased_shared":
                    # deceased_shared 对所有 scope 可见
                    return True
                if vis_row["visibility"] == "scope_shared":
                    # scope_shared: 检查当前 scope 是否在可见列表中
                    scope_vis_cursor = self.conn.execute(
                        """SELECT visibility FROM chunk_scope_visibility
                        WHERE chunk_id = ? AND relationship_scope_id = ?""",
                        (chunk_id, scope_id),
                    )
                    scope_vis_row = scope_vis_cursor.fetchone()
                    if scope_vis_row is not None:
                        return True
            # 如果没有匹配的可见性记录，检查是否是所属 scope
            if chunk["relationship_scope_id"] == scope_id:
                return True
            return False

        # 没有可见性记录，默认为 scope_private: 仅所属 scope 可见
        return chunk["relationship_scope_id"] == scope_id

    def validate_scope_access(
        self,
        scope_id: str,
        requested_action: str = "query",
    ) -> bool:
        """验证对指定 scope 的访问权限。

        检查:
        1. scope 是否存在且活跃
        2. 请求的操作是否有对应权限

        Args:
            scope_id: 关系作用域 ID
            requested_action: 请求的操作类型 (query / browse / add_oral_history /
                             elevate_shared / export / view_financial / view_medical /
                             view_intimate / interact_level3 / delete_scope)

        Returns:
            True 如果访问被允许
        """
        if self.conn is None:
            return True

        # 检查 scope 是否存在且活跃
        cursor = self.conn.execute(
            "SELECT is_active, deleted_at FROM relationship_scope WHERE id = ?",
            (scope_id,),
        )
        scope = cursor.fetchone()
        if scope is None:
            return False
        if scope["deleted_at"] is not None:
            return False
        if scope["is_active"] != 1:
            return False

        # 操作到权限键的映射
        action_to_permission = {
            "query": "can_query_memory",
            "browse": "can_browse_original",
            "add_oral_history": "can_add_oral_history",
            "elevate_shared": "can_elevate_shared",
            "export": "can_export_data",
            "view_financial": "can_view_financial",
            "view_medical": "can_view_medical",
            "view_intimate": "can_view_intimate",
            "interact_level3": "can_interact_level3",
            "delete_scope": "can_delete_scope",
        }

        perm_key = action_to_permission.get(requested_action)
        if perm_key is None:
            # 未知操作默认允许（不属于权限矩阵的操作）
            return True

        # 查询权限
        perm_cursor = self.conn.execute(
            "SELECT permission_value FROM scope_permission WHERE relationship_scope_id = ? AND permission_key = ?",
            (scope_id, perm_key),
        )
        perm_row = perm_cursor.fetchone()
        if perm_row is None:
            return False

        return perm_row["permission_value"] == "allow"