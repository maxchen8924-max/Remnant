"""Claim Alignment — 白皮书 Steps 12-13 + 置信度计算。

核心函数:
- extract_claims(): Step 12 — 从 LLM 输出提取 claim
- align_claims_to_evidence(): Step 13 — claim-evidence 对齐
- _match_claim_to_evidence(): claim 文本与 evidence 匹配
- _check_contradiction(): 证据矛盾检测
- _compute_confidence(): 综合置信度计算

规则:
- LLM 输出包含 {claim:N} 标记
- 无标记的事实性句子标记为 uncategorized
- 对齐规则: fully_supported / partially_supported / unsupported / contradicted / insufficient_evidence
- 置信度 = weighted_avg * consistency_factor
- 无矛盾 consistency_factor=1.0, 有矛盾=0.7, 严重矛盾=0.4
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from remnant_core.claims import (
    Claim,
    ClaimType,
    EvidenceItem,
    EvidencePack,
    ProvenanceLevel,
    SupportStatus,
    PROVENANCE_SCORES,
)


# ==================== Step 12: Claim Extraction ====================


def extract_claims(llm_output: str) -> list[dict[str, Any]]:
    """从 LLM 输出文本中提取事实声明 — 白皮书 Step 12。

    匹配 {claim:N} 标记，按句号分割句子，为每个句子分配 claim 标记。
    无标记的事实性句子标记为 uncategorized。

    输入格式示例::

        根据记录，他在2023年6月去了北京旅游。{claim:1}
        她似乎很喜欢画画。{claim:2}
        这是一段没有标记的句子。

    输出格式::

        [
            {"claim_id": "1", "text": "根据记录，他在2023年6月去了北京旅游。", "has_marker": True},
            {"claim_id": "2", "text": "她似乎很喜欢画画。", "has_marker": True},
            {"claim_id": "uncategorized_0", "text": "这是一段没有标记的句子。", "has_marker": False},
        ]

    Args:
        llm_output: LLM 生成的响应文本（可能包含 {claim:N} 标记）

    Returns:
        claim 字典列表，每个字典包含 claim_id, text, has_marker
    """
    if not llm_output or not llm_output.strip():
        return []

    claims: list[dict[str, Any]] = []
    uncategorized_idx = 0

    # 匹配 {claim:N} 标记的正则
    claim_marker_pattern = r"\{claim:(\d+)\}"

    # 按行处理
    lines = llm_output.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 尝试匹配带 claim 标记的行
        markers = list(re.finditer(claim_marker_pattern, line))

        if markers:
            # 有标记的行：移除标记后作为 claim 文本
            clean_text = re.sub(claim_marker_pattern, "", line).strip()
            for marker_match in markers:
                claim_id = marker_match.group(1)
                claims.append({
                    "claim_id": claim_id,
                    "text": clean_text,
                    "has_marker": True,
                })
        else:
            # 无标记的行：按句子分割，判断是否为事实性句子
            sentences = _split_sentences(line)
            from remnant_core.evidence import _is_factual_sentence

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                if _is_factual_sentence(sentence):
                    claims.append({
                        "claim_id": f"uncategorized_{uncategorized_idx}",
                        "text": sentence,
                        "has_marker": False,
                    })
                    uncategorized_idx += 1

    return claims


def _split_sentences(text: str) -> list[str]:
    """将文本按中英文句号、感叹号、问号分割为句子。

    Args:
        text: 待分割的文本

    Returns:
        句子列表
    """
    # 中英文句号、感叹号、问号作为分割点
    parts = re.split(r'[。！？\.!\?]', text)
    # 重新加上标点
    result: list[str] = []
    idx = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 找到原始文本中的标点
        end_idx = idx + len(part)
        if end_idx < len(text):
            punct = text[end_idx]
            if punct in '。！？.!?':
                result.append(part + punct)
                idx = end_idx + 1
            else:
                result.append(part)
                idx = end_idx
        else:
            result.append(part)
            idx = end_idx

    # 如果正则分割效果不好，回退到简单分割
    if not result:
        result = [text]

    return result


# ==================== Step 13: Claim-Evidence Alignment ====================


def align_claims_to_evidence(
    claims: list[dict[str, Any]],
    evidence_pack: EvidencePack,
) -> list[Claim]:
    """Claim-Evidence 对齐 — 白皮书 Step 13。

    将 claim 文本与 evidence 匹配:
    - 无匹配证据 → unsupported_memory
    - 仅有低质量证据 → inferred_but_supported + insufficient_evidence
    - 有充分证据 → supported_memory / fully_supported / partially_supported
    - 检查证据间矛盾 → contradicted

    Args:
        claims: 从 extract_claims() 输出的 claim 字典列表
        evidence_pack: 证据包

    Returns:
        对齐后的 Claim 对象列表
    """
    aligned_claims: list[Claim] = []

    for claim_dict in claims:
        claim_id = claim_dict.get("claim_id", str(uuid.uuid4()))
        claim_text = claim_dict.get("text", "")

        # 尝试匹配证据
        matched_evidence = _match_claim_to_evidence(claim_text, evidence_pack.items)

        # 计算 claim 的 provenance_level（取所有 evidence 的最低值）
        if matched_evidence:
            prov_levels = [
                ProvenanceLevel(e.provenance_level) if isinstance(e.provenance_level, str) else e.provenance_level
                for e in matched_evidence
            ]
            prov_level = min(
                prov_levels,
                key=lambda pl: PROVENANCE_SCORES.get(pl, 0.0),
            )
        else:
            prov_level = ProvenanceLevel.inferred

        # 检查矛盾
        has_contradiction, contradiction_severity = _check_contradiction(matched_evidence)

        # 计算 confidence
        confidence = _compute_confidence(matched_evidence, has_contradiction, contradiction_severity)

        # 确定 claim_type 和 support_status
        claim_type, support_status = _classify_claim(
            matched_evidence=matched_evidence,
            has_contradiction=has_contradiction,
            contradiction_severity=contradiction_severity,
        )

        # 构建矛盾说明
        dissent_note = ""
        if has_contradiction:
            dissent_note = f"证据存在矛盾（严重程度: {contradiction_severity}）"

        # 生成限定词处理的文本
        qualified_text = _apply_qualifiers(claim_text, claim_type, claim_dict)

        # 判断是否应移除
        is_removable = claim_type == ClaimType.unsupported_memory

        claim = Claim(
            claim_id=claim_id,
            claim_text=claim_text,
            claim_type=claim_type,
            support_status=support_status,
            confidence=confidence,
            provenance_level=prov_level,
            evidence=matched_evidence,
            dissent_note=dissent_note,
            is_removable=is_removable,
            qualified_text=qualified_text,
        )
        aligned_claims.append(claim)

    return aligned_claims


def _match_claim_to_evidence(
    claim_text: str,
    evidence_items: list[EvidenceItem],
    threshold: float = 0.3,
) -> list[EvidenceItem]:
    """将 claim 文本与 evidence 匹配 — 基于关键词重叠。

    M3 阶段使用规则引擎匹配（关键词重叠 + 说话人匹配 + 时间匹配）。
    后续里程将替换为 LLM 语义匹配。

    规则:
    1. 对 claim 和 evidence 摘录进行分词
    2. 计算关键词重叠率
    3. 匹配说话人
    4. 匹配时间范围
    5. 综合评分 ≥ threshold 的证据保留

    Args:
        claim_text: claim 文本
        evidence_items: 证据项列表
        threshold: 匹配阈值

    Returns:
        匹配的证据项列表
    """
    if not claim_text or not evidence_items:
        return []

    # 简单中文分词：按字符拆分（2-gram）
    claim_keywords = _extract_keywords(claim_text)

    matched: list[EvidenceItem] = []

    for evidence in evidence_items:
        score = _compute_match_score(claim_text, claim_keywords, evidence)
        if score >= threshold:
            matched.append(evidence)

    return matched


def _extract_keywords(text: str) -> set[str]:
    """从文本中提取关键词。

    使用 2-gram 和单字混合策略，过滤停用词。

    Args:
        text: 输入文本

    Returns:
        关键词集合
    """
    # 中文停用词
    stop_words = {
        "的", "了", "在", "是", "我", "你", "他", "她", "它", "们",
        "这", "那", "有", "和", "与", "或", "不", "也", "都",
        "就", "要", "会", "能", "可以", "被", "把", "从", "到",
        "很", "非常", "还", "又", "再", "才", "只", "都",
        "the", "a", "an", "is", "are", "was", "were", "be",
        "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might",
    }

    keywords: set[str] = set()

    # 英文单词
    en_words = re.findall(r"[a-zA-Z]{2,}", text.lower())
    keywords.update(w for w in en_words if w not in stop_words)

    # 中文 2-gram
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chinese_chars) - 1):
        bigram = chinese_chars[i] + chinese_chars[i + 1]
        if bigram not in stop_words:
            keywords.add(bigram)

    # 数字/日期
    numbers = re.findall(r"\d{4,}", text)
    keywords.update(numbers)

    return keywords


def _compute_match_score(
    claim_text: str,
    claim_keywords: set[str],
    evidence: EvidenceItem,
) -> float:
    """计算 claim 与 evidence 的匹配分数。

    综合考虑:
    1. 关键词重叠率
    2. provenance_score 加权
    3. 说话人匹配加分

    Args:
        claim_text: claim 文本
        claim_keywords: claim 关键词集合
        evidence: 证据项

    Returns:
        匹配分数 0.0~1.0
    """
    # 获取 evidence 摘录文本
    evidence_text = ""
    if evidence.source_span and isinstance(evidence.source_span, dict):
        evidence_text = evidence.source_span.get("excerpt", "")
    elif evidence.quote_hash:
        # 没有摘录时，使用 chunk_id 的元数据（模拟）
        pass

    if not evidence_text:
        # 无摘录时，仅基于 provenance_score 给基础分
        return evidence.provenance_score * 0.5

    # 关键词重叠率
    evidence_keywords = _extract_keywords(evidence_text)
    if not claim_keywords or not evidence_keywords:
        overlap = 0.0
    else:
        overlap_count = len(claim_keywords & evidence_keywords)
        overlap_rate = overlap_count / max(len(claim_keywords), 1)
        overlap = overlap_rate

    # provenance 加权
    prov_weight = evidence.provenance_score

    # 说话人匹配加分
    speaker_bonus = 0.0
    if evidence.speaker:
        # 检查 claim 中是否提到该说话人
        if evidence.speaker in claim_text:
            speaker_bonus = 0.15

    # 综合评分
    score = 0.4 * overlap + 0.4 * prov_weight + 0.1 * speaker_bonus + 0.1 * evidence.relevance_score

    return min(1.0, max(0.0, score))


def _check_contradiction(
    evidence_items: list[EvidenceItem],
) -> tuple[bool, str]:
    """检查证据间是否存在矛盾。

    M3 阶段使用简单启发式:
    - 如果有多个 evidence 且 provenance_score 差异很大（高置信与低置信共存）
    - 或者说话人之间矛盾

    后续将替换为 LLM 矛盾检测。

    Args:
        evidence_items: 证据项列表

    Returns:
        (has_contradiction, severity) 元组
        severity: "none" / "moderate" / "severe"
    """
    if len(evidence_items) < 2:
        return False, "none"

    # 检查 provenance_score 方差
    scores = [e.provenance_score for e in evidence_items]
    if not scores:
        return False, "none"

    avg_score = sum(scores) / len(scores)

    # 如果同时存在高分证据和低分证据，标记为矛盾
    high_scores = [s for s in scores if s >= 0.8]
    low_scores = [s for s in scores if s < 0.5]

    if high_scores and low_scores:
        # 高分和低分证据共存 — 中等矛盾
        return True, "moderate"

    # 检查说话人矛盾（多个不同说话人的证据对同一事实有不同描述）
    speakers = set(e.speaker for e in evidence_items if e.speaker)
    if len(speakers) > 2:
        # 3个以上不同说话人可能存在矛盾
        return True, "moderate"

    # 同一说话人不同内容的矛盾由后续 LLM 检测
    return False, "none"


def _compute_confidence(
    evidence_items: list[EvidenceItem],
    has_contradiction: bool,
    contradiction_severity: str,
) -> float:
    """计算综合置信度 — 白皮书 Step 13。

    公式: confidence = weighted_avg * consistency_factor

    consistency_factor:
    - 无矛盾: 1.0
    - 有矛盾（moderate）: 0.7
    - 严重矛盾（severe）: 0.4

    weighted_avg: 证据 provenance_score 的加权平均

    Args:
        evidence_items: 证据项列表
        has_contradiction: 是否存在矛盾
        contradiction_severity: 矛盾严重程度

    Returns:
        置信度分数 0.0~1.0
    """
    if not evidence_items:
        return 0.0

    # 计算 weighted average（按 relevance_score 加权）
    total_weight = sum(max(e.relevance_score, 0.1) for e in evidence_items)
    if total_weight == 0:
        avg = sum(e.provenance_score for e in evidence_items) / len(evidence_items)
    else:
        avg = sum(
            e.provenance_score * max(e.relevance_score, 0.1) for e in evidence_items
        ) / total_weight

    # consistency factor
    if not has_contradiction:
        consistency_factor = 1.0
    elif contradiction_severity == "severe":
        consistency_factor = 0.4
    else:
        consistency_factor = 0.7

    return round(avg * consistency_factor, 4)


def _classify_claim(
    matched_evidence: list[EvidenceItem],
    has_contradiction: bool,
    contradiction_severity: str,
) -> tuple[ClaimType, SupportStatus]:
    """根据证据匹配结果分类 claim。

    分类规则:
    - 无匹配证据 → (unsupported_memory, unsupported)
    - 有匹配但 < 2 条证据且 avg < 0.5 → (inferred_but_supported, insufficient_evidence)
    - 有矛盾 → (inferred_but_supported, contradicted)
    - ≥ 2 条 provenance ≥ 0.8 → (supported_memory, fully_supported)
    - 有匹配但不够充分 → (supported_memory, partially_supported)

    Args:
        matched_evidence: 匹配的证据列表
        has_contradiction: 是否存在矛盾
        contradiction_severity: 矛盾严重程度

    Returns:
        (claim_type, support_status) 元组
    """
    if not matched_evidence:
        return ClaimType.unsupported_memory, SupportStatus.unsupported

    # 有矛盾的情况
    if has_contradiction:
        return ClaimType.inferred_but_supported, SupportStatus.contradicted

    # 计算高质量证据数量
    high_quality = sum(1 for e in matched_evidence if e.provenance_score >= 0.8)
    avg_prov = sum(e.provenance_score for e in matched_evidence) / len(matched_evidence)

    # 充分支持
    if high_quality >= 2:
        return ClaimType.supported_memory, SupportStatus.fully_supported

    # 有证据但不够充分
    if len(matched_evidence) >= 2 and avg_prov >= 0.5:
        return ClaimType.supported_memory, SupportStatus.partially_supported

    # 证据不够（< 2条或 avg < 0.5）
    if len(matched_evidence) < 2 or avg_prov < 0.5:
        return ClaimType.inferred_but_supported, SupportStatus.insufficient_evidence

    # 默认
    return ClaimType.supported_memory, SupportStatus.partially_supported


# ==================== 限定词处理 ====================


# 限定词映射
QUALIFIER_WORDS = {
    ClaimType.inferred_but_supported: ["可能", "似乎", "根据记录推测", "大概", "或许"],
    ClaimType.user_provided_context: ["你提到的", "你描述的", "根据你提供的信息", "你说"],
}

SOURCE_ANNOTATIONS = {
    ClaimType.user_provided_context: "（根据用户提供信息）",
}


def _apply_qualifiers(
    claim_text: str,
    claim_type: ClaimType,
    claim_dict: dict[str, Any],
) -> str:
    """根据 claim_type 为文本添加限定词。

    规则:
    - inferred_but_supported: 必须使用限定词（"可能""似乎""根据记录推测"）
    - user_provided_context: 必须标注来源（"你提到的""你描述的"）
    - unsupported_memory: 不处理（将在 remove_unsupported_claims 中移除）
    - supported_memory: 不需要限定词

    Args:
        claim_text: 原始 claim 文本
        claim_type: 声明类型
        claim_dict: 原始 claim 字典

    Returns:
        经过限定词处理的文本
    """
    if claim_type == ClaimType.supported_memory:
        return claim_text

    if claim_type == ClaimType.safety_response:
        return claim_text

    if claim_type == ClaimType.refusal:
        return claim_text

    if claim_type == ClaimType.unsupported_memory:
        return claim_text

    if claim_type == ClaimType.inferred_but_supported:
        # 检查是否已有限定词
        qualifiers = QUALIFIER_WORDS.get(ClaimType.inferred_but_supported, [])
        has_qualifier = any(q in claim_text for q in qualifiers)
        if not has_qualifier:
            return f"根据记录推测，{claim_text}"
        return claim_text

    if claim_type == ClaimType.user_provided_context:
        # 检查是否已标注来源
        source_markers = QUALIFIER_WORDS.get(ClaimType.user_provided_context, [])
        has_source = any(m in claim_text for m in source_markers)
        annotation = SOURCE_ANNOTATIONS.get(ClaimType.user_provided_context, "")
        if not has_source:
            return f"你提到的{claim_text}{annotation}"
        return f"{claim_text}{annotation}" if annotation not in claim_text else claim_text

    return claim_text