"""Unsupported Claim Removal — 白皮书 Step 14。

核心函数:
- remove_unsupported_claims(): 移除不支持的 claim

规则:
1. unsupported_memory → 移除
2. safety_response / refusal → 保留
3. contradicted → 保留但添加矛盾说明
4. insufficient_evidence + inferred_but_supported → 保留但降低置信度
5. insufficient_evidence + 其他 → 移除
"""

from __future__ import annotations

from remnant_core.claims import (
    Claim,
    ClaimType,
    RemovedClaim,
    SupportStatus,
)


def remove_unsupported_claims(
    claims: list[Claim],
) -> tuple[list[Claim], list[RemovedClaim]]:
    """移除不支持的 claim — 白皮书 Step 14。

    处理规则:
    1. unsupported_memory → 移除，记录原因 "unsupported_memory_not_allowed_in_response"
    2. safety_response / refusal → 保留（安全响应和拒绝直接输出）
    3. contradicted → 保留，添加矛盾说明（dissent_note 已在 alignment 阶段设置）
    4. insufficient_evidence + inferred_but_supported → 保留，降低置信度 (*0.7)
    5. insufficient_evidence + 其他类型 → 移除，记录原因 "insufficient_evidence"

    Args:
        claims: 对齐后的 claim 列表（来自 align_claims_to_evidence）

    Returns:
        (valid_claims, removed_claims) 元组
    """
    valid_claims: list[Claim] = []
    removed_claims: list[RemovedClaim] = []

    for idx, claim in enumerate(claims):
        # Rule 1: unsupported_memory — 必须移除
        if claim.claim_type == ClaimType.unsupported_memory:
            removed_claims.append(RemovedClaim(
                claim=claim,
                reason="unsupported_memory_not_allowed_in_response",
                original_index=idx,
            ))
            continue

        # Rule 2: safety_response / refusal — 直接保留
        if claim.claim_type in (ClaimType.safety_response, ClaimType.refusal):
            valid_claims.append(claim)
            continue

        # Rule 3: contradicted — 保留，矛盾说明已在 alignment 阶段设置
        if claim.support_status == SupportStatus.contradicted:
            valid_claims.append(claim)
            continue

        # Rule 4: insufficient_evidence + inferred_but_supported — 保留但降低置信度
        if (
            claim.support_status == SupportStatus.insufficient_evidence
            and claim.claim_type == ClaimType.inferred_but_supported
        ):
            claim.confidence = round(claim.confidence * 0.7, 4)
            valid_claims.append(claim)
            continue

        # Rule 5: insufficient_evidence + 其他类型 — 移除
        if claim.support_status == SupportStatus.insufficient_evidence:
            removed_claims.append(RemovedClaim(
                claim=claim,
                reason="insufficient_evidence",
                original_index=idx,
            ))
            continue

        # 默认: 保留
        valid_claims.append(claim)

    return valid_claims, removed_claims