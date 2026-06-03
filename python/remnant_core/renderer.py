"""Response Rendering — 白皮书 Step 15。

核心函数:
- render_response(): 渲染最终响应文本

规则:
1. 插入安全缓冲语（safety_buffer）
2. inferred_but_supported 有限定词检查
3. user_provided_context 标注来源
4. 安全响应和拒绝直接输出
5. 每个 claim 添加 {claim:claim_id} 标注
6. 被移除 claim 的尾部说明
7. 确定 response_mode
"""

from __future__ import annotations

import uuid

from remnant_core.claims import (
    Claim,
    ClaimType,
    EvidencePack,
    RemovedClaim,
    Response,
    ResponseMode,
    SafetyDirectiveData,
    SupportStatus,
)


# 安全缓冲语模板
SAFETY_BUFFER_TEMPLATES = {
    "ALLOW": "",
    "SOFT_BREAK": "⚠️ 我注意到你可能需要休息一下。让我们换个轻松的话题。\n\n",
    "HARD_BREAK": "⛔ 抱歉，为了你的健康和安全，本次对话需要暂停。\n\n",
    "COOLDOWN": "🕐 让我们先休息一下，稍后继续。\n\n",
    "ESCALATE": "🆘 检测到可能需要专业帮助。请考虑联系心理咨询热线。\n\n",
}

# 被移除 claim 的尾部说明模板
REMOVED_CLAIM_NOTE = "💡 以下信息因证据不足未能包含在回答中：\n{items}"

# 拒绝响应模板
REFUSAL_TEMPLATE = "抱歉，我目前没有足够的信息来回答这个问题。你可以尝试提供更多线索或换一种方式提问。"

# 安全响应模板（根据 template_id 选择）
SAFETY_TEMPLATES = {
    "anti_dependency": "我理解你对这个话题的感受。记住，这是一个数字记忆助手，可以帮助你怀念过去，但不能替代真实的人际关系。",
    "emotional_distress": "检测到你可能正在经历情绪困扰。请记住，如果需要帮助，可以联系专业心理咨询热线。\n\n全国心理援助热线：400-161-9995",
    "late_night": "夜深了，休息对身心都很重要。建议你早点休息，明天再继续。",
    "excessive_usage": "你已经和数字记忆相处了很长时间。适度使用可以帮助你更好地怀念，休息一下也很重要。",
    "default": "为了你的安全和健康，本次对话暂时中止。请稍后再试。",
}


def _determine_response_mode(
    valid_claims: list[Claim],
    removed_claims: list[RemovedClaim],
    safety_directive: SafetyDirectiveData,
) -> ResponseMode:
    """确定响应模式。

    优先级:
    1. safety_response — 如果安全指令为 HARD_BREAK / ESCALATE
    2. refusal — 如果无有效 claim 且无移除 claim（完全无数据）
    3. limited_interaction — 如果有效 claim 全是 inferred_but_supported 或 insufficient
    4. archive_search — 如果缺少部分 claim
    5. evidence_grounded — 证据充分

    Args:
        valid_claims: 有效 claim 列表
        removed_claims: 被移除的 claim 列表
        safety_directive: 安全指令

    Returns:
        ResponseMode 枚举值
    """
    # 安全响应最高优先级
    if safety_directive.action in ("HARD_BREAK", "ESCALATE"):
        return ResponseMode.safety_response

    # 完全无数据
    if not valid_claims and not removed_claims:
        return ResponseMode.refusal

    # 无有效 claim 但有被移除的 claim
    if not valid_claims and removed_claims:
        return ResponseMode.refusal

    # 检查有效 claim 的质量
    has_any_supported = any(
        c.claim_type == ClaimType.supported_memory and c.support_status in (SupportStatus.fully_supported, SupportStatus.partially_supported)
        for c in valid_claims
    )
    has_safety_or_refusal = any(
        c.claim_type in (ClaimType.safety_response, ClaimType.refusal)
        for c in valid_claims
    )

    # 如果全是安全响应或拒绝
    if has_safety_or_refusal and len(valid_claims) == len([
        c for c in valid_claims if c.claim_type in (ClaimType.safety_response, ClaimType.refusal)
    ]):
        return ResponseMode.safety_response if has_safety_or_refusal else ResponseMode.refusal

    # 有被移除的 claim，缺少部分数据
    if removed_claims and has_any_supported:
        return ResponseMode.archive_search

    # 全是推断或不足的证据
    if not has_any_supported:
        return ResponseMode.limited_interaction

    # 证据充分
    return ResponseMode.evidence_grounded


def _build_response_text(
    valid_claims: list[Claim],
    removed_claims: list[RemovedClaim],
    safety_directive: SafetyDirectiveData,
    response_mode: ResponseMode,
) -> str:
    """构建响应文本。

    Args:
        valid_claims: 有效 claim 列表
        removed_claims: 被移除的 claim 列表
        safety_directive: 安全指令
        response_mode: 响应模式

    Returns:
        最终响应文本
    """
    # 安全缓冲语
    safety_buffer = SAFETY_BUFFER_TEMPLATES.get(safety_directive.action, "")

    # 根据响应模式构建文本
    if response_mode == ResponseMode.safety_response:
        # 安全响应：直接输出安全模板
        template_id = safety_directive.template_id or "default"
        safety_text = SAFETY_TEMPLATES.get(template_id, SAFETY_TEMPLATES["default"])
        return f"{safety_buffer}{safety_text}"

    if response_mode == ResponseMode.refusal:
        # 拒绝响应
        return f"{safety_buffer}{REFUSAL_TEMPLATE}"

    # 正常响应：拼接 claim 文本
    parts: list[str] = []

    # 安全缓冲语
    if safety_buffer:
        parts.append(safety_buffer)

    # 每个 claim 的文本
    for claim in valid_claims:
        # 使用 qualified_text（经过限定词处理的文本）
        text = claim.qualified_text or claim.claim_text

        # 添加 {claim:claim_id} 标注
        text = f"{text} {{claim:{claim.claim_id}}}"

        # 矛盾说明
        if claim.dissent_note:
            text = f"{text} [{claim.dissent_note}]"

        parts.append(text)

    # 被移除 claim 的尾部说明
    if removed_claims:
        removed_items: list[str] = []
        for removed in removed_claims:
            reason_desc = _describe_removal_reason(removed.reason)
            removed_items.append(f"- 「{removed.claim.claim_text[:50]}...」{reason_desc}")
        removed_note = REMOVED_CLAIM_NOTE.format(items="\n".join(removed_items))
        parts.append("")
        parts.append(removed_note)

    return "\n\n".join(parts)


def _describe_removal_reason(reason: str) -> str:
    """将移除原因转换为用户友好的说明。

    Args:
        reason: 内部移除原因代码

    Returns:
        用户友好的说明文本
    """
    reasons = {
        "unsupported_memory_not_allowed_in_response": "（证据不足，无法确认此信息）",
        "insufficient_evidence": "（现有证据不足以支撑此信息）",
    }
    return reasons.get(reason, f"（{reason}）")


def _verify_qualifiers(claims: list[Claim]) -> list[str]:
    """验证限定词规则。

    检查:
    - inferred_but_supported 必须有限定词
    - user_provided_context 必须有来源标注

    Args:
        claims: 有效 claim 列表

    Returns:
        警告消息列表（空列表表示全部通过）
    """
    warnings: list[str] = []

    inferred_qualifiers = ["可能", "似乎", "根据记录推测", "大概", "或许", "推测"]
    user_source_markers = ["你提到的", "你描述的", "根据你提供的信息", "你说"]

    for claim in claims:
        if claim.claim_type == ClaimType.inferred_but_supported:
            has_qualifier = any(q in (claim.qualified_text or claim.claim_text) for q in inferred_qualifiers)
            if not has_qualifier:
                warnings.append(
                    f"Claim {claim.claim_id} (inferred_but_supported) 缺少限定词：{claim.claim_text[:50]}"
                )

        if claim.claim_type == ClaimType.user_provided_context:
            has_source = any(m in (claim.qualified_text or claim.claim_text) for m in user_source_markers)
            if not has_source:
                warnings.append(
                    f"Claim {claim.claim_id} (user_provided_context) 缺少来源标注：{claim.claim_text[:50]}"
                )

    return warnings


def render_response(
    valid_claims: list[Claim],
    removed_claims: list[RemovedClaim],
    safety_directive: SafetyDirectiveData | None = None,
    trace_id: str = "",
    context: dict | None = None,
) -> Response:
    """渲染最终响应 — 白皮书 Step 15。

    流程:
    1. 插入安全缓冲语
    2. inferred_but_supported 有限定词检查
    3. user_provided_context 标注来源
    4. 安全响应和拒绝直接输出
    5. 每个 claim 添加 {claim:claim_id} 标注
    6. 被移除 claim 的尾部说明
    7. 确定 response_mode

    Args:
        valid_claims: 有效 claim 列表（经过 remove_unsupported_claims 处理）
        removed_claims: 被移除的 claim 列表
        safety_directive: 安全指令（None 表示 ALLOW）
        trace_id: 检索追踪 ID
        context: 附加上下文（session_id, scope_id 等）

    Returns:
        完整的 Response 对象
    """
    if safety_directive is None:
        safety_directive = SafetyDirectiveData(action="ALLOW")

    # Step 1: 确定响应模式
    response_mode = _determine_response_mode(valid_claims, removed_claims, safety_directive)

    # Step 2: 验证限定词规则
    qualifier_warnings = _verify_qualifiers(valid_claims)

    # Step 3: 构建响应文本
    response_text = _build_response_text(valid_claims, removed_claims, safety_directive, response_mode)

    # Step 4: 构建 EvidencePack（从 valid_claims 中汇总）
    all_evidence: list[any] = []
    for claim in valid_claims:
        all_evidence.extend(claim.evidence)

    # 收集 safety_flags
    safety_flags: list[str] = qualifier_warnings.copy()
    if safety_directive.action != "ALLOW":
        safety_flags.append(f"safety_action:{safety_directive.action}")
    if removed_claims:
        safety_flags.append(f"claims_removed:{len(removed_claims)}")

    # Step 5: 构建 Response 对象
    response_id = str(uuid.uuid4()) if not context or "response_id" not in (context or {}) else context.get("response_id", str(uuid.uuid4()))

    response = Response(
        response_id=response_id,
        trace_id=trace_id,
        session_id=(context or {}).get("session_id", ""),
        scope_id=(context or {}).get("scope_id", ""),
        response_text=response_text,
        response_mode=response_mode,
        claims=valid_claims,
        removed_claims=removed_claims,
        evidence_pack=(context or {}).get("evidence_pack") if context and "evidence_pack" in context else None,
        safety_directive=safety_directive,
        model_used=(context or {}).get("model_used", "rule_engine_v0.1"),
        duration_ms=(context or {}).get("duration_ms", 0),
        safety_flags=safety_flags,
    )

    return response