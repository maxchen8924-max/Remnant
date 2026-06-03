"""Audit Logging — 白皮书 Step 16。

核心函数:
- log_response_audit(): 写入 response_claim + claim_evidence
- log_interaction_audit(): 写入 interaction_session + interaction_message

使用 schema.py 中的 DDL 表结构，直接操作 SQLite。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from remnant_core.claims import (
    Claim,
    ClaimType,
    EvidenceItem,
    EvidencePack,
    ProvenanceLevel,
    RemovedClaim,
    Response,
    SafetyDirectiveData,
    SupportStatus,
)


def _generate_id() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def _now_iso() -> str:
    """获取当前时间 ISO 8601 格式。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def log_response_audit(
    conn: sqlite3.Connection,
    scope_id: str,
    session_id: str,
    response_id: str,
    claims: list[Claim],
    removed_claims: list[RemovedClaim],
    evidence_pack: EvidencePack,
    trace_id: str,
    model_used: str = "rule_engine_v0.1",
) -> None:
    """写入 response_claim + claim_evidence — 白皮书 Step 16。

    将每个 Claim 写入 response_claim 表，将每个 EvidenceItem 写入 claim_evidence 表。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        session_id: 交互会话 ID
        response_id: 响应 ID
        claims: 有效 claim 列表
        removed_claims: 被移除的 claim 列表
        evidence_pack: 证据包
        trace_id: 检索追踪 ID
        model_used: 使用的模型
    """
    now = _now_iso()

    # 写入有效的 claim
    for claim in claims:
        claim_id = claim.claim_id or _generate_id()

        # 写入 response_claim 表
        conn.execute(
            """INSERT INTO response_claim (
                id, relationship_scope_id, interaction_session_id,
                claim_text, confidence, dissent_note, evidence_sufficient,
                model_used, model_parameters, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                claim_id,
                scope_id,
                session_id,
                claim.claim_text,
                claim.confidence,
                claim.dissent_note or None,
                1 if claim.support_status in (SupportStatus.fully_supported, SupportStatus.partially_supported) else 0,
                model_used,
                json.dumps({"claim_type": claim.claim_type.value, "provenance_level": claim.provenance_level.value, "support_status": claim.support_status.value}),
                "ACTIVE",
                now,
                now,
            ),
        )

        # 写入 claim_evidence 表
        for evidence in claim.evidence:
            evidence_id = _generate_id()

            # 映射 provenance_level 到 evidence_type
            evidence_type = _map_evidence_type(evidence, claim.support_status)

            conn.execute(
                """INSERT INTO claim_evidence (
                    id, claim_id, chunk_id, span_id, evidence_type,
                    relevance_score, is_direct_quote, excerpt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evidence_id,
                    claim_id,
                    evidence.chunk_id,
                    None,  # span_id — 暂无
                    evidence_type,
                    evidence.relevance_score,
                    1 if evidence.provenance_level == ProvenanceLevel.primary_source.value else 0,
                    evidence.source_span.get("excerpt", "") if evidence.source_span and isinstance(evidence.source_span, dict) else None,
                ),
            )

    # 写入被移除的 claim（标记为 DEPRECATED）
    for removed in removed_claims:
        claim_id = removed.claim.claim_id or _generate_id()

        conn.execute(
            """INSERT INTO response_claim (
                id, relationship_scope_id, interaction_session_id,
                claim_text, confidence, dissent_note, evidence_sufficient,
                model_used, model_parameters, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                claim_id,
                scope_id,
                session_id,
                removed.claim.claim_text,
                removed.claim.confidence,
                removed.reason,
                0,  # evidence_sufficient = False
                model_used,
                json.dumps({
                    "claim_type": removed.claim.claim_type.value,
                    "provenance_level": removed.claim.provenance_level.value,
                    "support_status": removed.claim.support_status.value,
                    "removal_reason": removed.reason,
                }),
                "DEPRECATED",  # 被移除的 claim 标记为 DEPRECATED
                now,
                now,
            ),
        )

    conn.commit()


def _map_evidence_type(
    evidence: EvidenceItem,
    support_status: SupportStatus,
) -> str:
    """映射证据类型到 claim_evidence.evidence_type。

    Args:
        evidence: 证据项
        support_status: 支持状态

    Returns:
        evidence_type 字符串 ("primary" / "supporting" / "contradictory")
    """
    if support_status == SupportStatus.contradicted:
        # contraddicted 的证据中矛盾的标记为 contradictory
        if evidence.provenance_score < 0.5:
            return "contradictory"
        return "supporting"

    if evidence.provenance_level == ProvenanceLevel.primary_source.value:
        return "primary"

    return "supporting"


def log_interaction_audit(
    conn: sqlite3.Connection,
    scope_id: str,
    deceased_profile_id: str,
    response: Response,
    trace_id: str,
) -> tuple[str, str]:
    """写入 interaction_session + interaction_message 表。

    创建或恢复一个交互会话，并记录交互消息。

    Args:
        conn: 数据库连接
        scope_id: 关系作用域 ID
        deceased_profile_id: 逝者档案 ID
        response: Response 对象
        trace_id: 检索追踪 ID

    Returns:
        (session_id, message_id) 元组
    """
    now = _now_iso()

    # 创建交互会话
    session_id = response.session_id or _generate_id()
    conn.execute(
        """INSERT INTO interaction_session (
            id, relationship_scope_id, deceased_profile_id,
            session_type, started_at, total_messages,
            llm_model_used, metadata, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            scope_id,
            deceased_profile_id,
            "conversation",
            now,
            1,  # total_messages = 1（一条 AI 响应）
            response.model_used,
            json.dumps({"response_mode": response.response_mode.value}),
            now,
            now,
        ),
    )

    # 创建交互消息
    message_id = _generate_id()
    claim_ids = json.dumps([c.claim_id for c in response.claims])
    safety_flags = json.dumps(response.safety_flags)

    conn.execute(
        """INSERT INTO interaction_message (
            id, session_id, relationship_scope_id, role,
            content, claim_ids, retrieval_trace_id,
            model_used, token_usage, duration_ms,
            safety_flags, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            message_id,
            session_id,
            scope_id,
            "assistant",
            response.response_text,
            claim_ids,
            trace_id or None,
            response.model_used,
            json.dumps({}),
            response.duration_ms,
            safety_flags,
            now,
        ),
    )

    # 写入 audit_log
    audit_id = _generate_id()
    conn.execute(
        """INSERT INTO audit_log (
            id, relationship_scope_id, action, actor,
            target_type, target_id, detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_id,
            scope_id,
            "PROVENANCE_RESPONSE",
            "system",
            "interaction_message",
            message_id,
            json.dumps({
                "response_id": response.response_id,
                "response_mode": response.response_mode.value,
                "claim_count": len(response.claims),
                "removed_claim_count": len(response.removed_claims),
                "safety_action": response.safety_directive.action,
            }),
            now,
        ),
    )

    conn.commit()

    return session_id, message_id


def get_claims_by_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """查询指定会话的所有 claim。

    Args:
        conn: 数据库连接
        session_id: 交互会话 ID

    Returns:
        claim 字典列表
    """
    cursor = conn.execute(
        "SELECT * FROM response_claim WHERE interaction_session_id = ? ORDER BY created_at",
        (session_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_evidence_by_claim(
    conn: sqlite3.Connection,
    claim_id: str,
) -> list[dict[str, Any]]:
    """查询指定 claim 的所有证据。

    Args:
        conn: 数据库连接
        claim_id: 声明 ID

    Returns:
        证据字典列表
    """
    cursor = conn.execute(
        "SELECT * FROM claim_evidence WHERE claim_id = ? ORDER BY relevance_score DESC",
        (claim_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_messages_by_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """查询指定会话的所有消息。

    Args:
        conn: 数据库连接
        session_id: 交互会话 ID

    Returns:
        消息字典列表
    """
    cursor = conn.execute(
        "SELECT * FROM interaction_message WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    )
    return [dict(row) for row in cursor.fetchall()]