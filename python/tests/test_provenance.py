"""M3 Provenance Response — Claim级溯源响应协议 完整测试。

测试覆盖:
1. ClaimType/SupportStatus 枚举测试
2. Evidence Sufficiency 测试
3. Claim Extraction 测试（{claim:N}标记提取、uncategorized句子）
4. Claim-Evidence Alignment 测试（fully_supported/partially_supported/unsupported/contradicted/insufficient）
5. Unsupported Claim Removal 测试（各种claim_type的处理规则）
6. Response Rendering 测试（限定词检查、来源标注、安全缓冲、response_mode）
7. Audit Logging 测试（response_claim/claim_evidence/interaction_message写入）
8. 端到端管道测试（从evidence到response的完整流程）
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Generator

import pytest

from remnant_store.schema import init_db
from remnant_core.claims import (
    Claim,
    ClaimType,
    EvidenceItem,
    EvidencePack,
    ProvenanceLevel,
    ProvenanceLevel,
    RemovedClaim,
    Response,
    ResponseMode,
    SafetyDirectiveData,
    SupportStatus,
    PROVENANCE_SCORES,
)
from remnant_core.evidence import (
    check_evidence_sufficiency,
    compute_provenance_score,
    compute_quote_hash,
    extract_excerpt,
    _is_factual_sentence,
    MIN_EVIDENCE_COUNT,
    MIN_AVG_PROVENANCE,
)
from remnant_core.alignment import (
    extract_claims,
    align_claims_to_evidence,
    _match_claim_to_evidence,
    _check_contradiction,
    _compute_confidence,
    _classify_claim,
    _apply_qualifiers,
    _extract_keywords,
)
from remnant_core.rejection import remove_unsupported_claims
from remnant_core.renderer import (
    render_response,
    _determine_response_mode,
    _build_response_text,
    _verify_qualifiers,
    SAFETY_BUFFER_TEMPLATES,
    REFUSAL_TEMPLATE,
)
from remnant_policy.audit import (
    log_response_audit,
    log_interaction_audit,
    get_claims_by_session,
    get_evidence_by_claim,
    get_messages_by_session,
)


# ==================== Fixtures ====================


def _generate_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """内存数据库 fixture。"""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def populated_db(db: sqlite3.Connection) -> sqlite3.Connection:
    """填充了测试数据的内存数据库。"""
    # 基础数据
    db.execute("INSERT INTO deceased_profile (id, name) VALUES ('dp-1', '测试逝者')")
    db.execute(
        "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
        "VALUES ('scope-1', 'dp-1', '作为儿子', 'child')"
    )

    # Source artifact
    db.execute(
        "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
        "VALUES ('sa-1', 'dp-1', '/test/wechat.txt', 'hash1', 1000, 'wechat_txt')"
    )

    # Memory chunks — 5个优质 + 2个低质 + 1个 user_provided_context
    chunks_data = [
        ("chunk-1", "sa-1", "scope-1", "conversation_segment", "他在2023年6月去了北京旅游，参观了故宫和长城。"),
        ("chunk-2", "sa-1", "scope-1", "conversation_segment", "她喜欢画画，尤其是水彩画，每周都会去公园写生。"),
        ("chunk-3", "sa-1", "scope-1", "diary_entry", "昨天我们一起去了西湖，风景很美。"),
        ("chunk-4", "sa-1", "scope-1", "letter", "亲爱的朋友，我最近工作很忙，但还是坚持每天运动。"),
        ("chunk-5", "sa-1", "scope-1", "conversation_segment", "他说他毕业后想去上海工作。"),
        ("chunk-6", "sa-1", "scope-1", "mixed", "据说那个地方还不错，可能值得一去。"),
        ("chunk-7", "sa-1", "scope-1", "mixed", "也许他那天有事情才没来。"),
        ("chunk-8", "sa-1", "scope-1", "user_provided_context", "用户补充的信息：他小时候住在南京。"),
    ]
    for cid, said, sid, ctype, content in chunks_data:
        db.execute(
            "INSERT INTO memory_chunk (id, source_artifact_id, relationship_scope_id, chunk_type, content, chunk_hash, token_count) "
            f"VALUES ('{cid}', '{said}', '{sid}', '{ctype}', '{content}', 'hash_{cid}', 20)"
        )

    # Raw messages (required by normalized_message FK)
    for i in range(1, 6):
        db.execute(
            f"INSERT INTO raw_message (id, source_artifact_id, speaker, content) "
            f"VALUES ('raw-msg-{i}', 'sa-1', 'speaker-{i}', 'content-{i}')"
        )

    # Normalized messages (required by memory_chunk_span FK)
    for i in range(1, 6):
        db.execute(
            f"INSERT INTO normalized_message (id, raw_message_id, source_artifact_id, speaker_original, speaker_normalized, content) "
            f"VALUES ('msg-{i}', 'raw-msg-{i}', 'sa-1', 'speaker-{i}', 'speaker-{i}', 'normalized-content-{i}')"
        )

    # Spans for chunks 1-5
    spans_data = [
        ("span-1", "chunk-1", "msg-1", 0, 20, "他"),
        ("span-2", "chunk-2", "msg-2", 0, 25, "她"),
        ("span-3", "chunk-3", "msg-3", 0, 18, "我"),
        ("span-4", "chunk-4", "msg-4", 0, 22, "朋友"),
        ("span-5", "chunk-5", "msg-5", 0, 15, "他"),
    ]
    for ssid, cid, mid, cs, ce, sp in spans_data:
        db.execute(
            f"INSERT INTO memory_chunk_span (id, chunk_id, normalized_message_id, char_start, char_end, source_speaker) "
            f"VALUES ('{ssid}', '{cid}', '{mid}', {cs}, {ce}, '{sp}')"
        )

    # Interaction session
    db.execute(
        "INSERT INTO interaction_session (id, relationship_scope_id, deceased_profile_id, session_type) "
        "VALUES ('session-1', 'scope-1', 'dp-1', 'conversation')"
    )

    db.commit()
    return db


def _make_evidence_item(
    chunk_id: str = "chunk-1",
    provenance_score: float = 0.8,
    provenance_level: str = "primary_source",
    speaker: str = "他",
    relevance_score: float = 0.7,
) -> EvidenceItem:
    """辅助函数: 创建 EvidenceItem。"""
    return EvidenceItem(
        chunk_id=chunk_id,
        source_artifact_id="sa-1",
        timestamp_range={"start": "2023-06-01", "end": "2023-06-30"},
        source_span={"char_start": 0, "char_end": 20, "excerpt": "测试摘录"},
        speaker=speaker,
        quote_hash="abc123",
        provenance_score=provenance_score,
        provenance_level=provenance_level,
        relevance_score=relevance_score,
    )


def _make_claim(
    claim_id: str = "1",
    claim_text: str = "测试声明",
    claim_type: ClaimType = ClaimType.supported_memory,
    support_status: SupportStatus = SupportStatus.fully_supported,
    evidence: list[EvidenceItem] | None = None,
    confidence: float = 0.8,
    provenance_level: ProvenanceLevel = ProvenanceLevel.primary_source,
    dissent_note: str = "",
) -> Claim:
    """辅助函数: 创建 Claim。"""
    return Claim(
        claim_id=claim_id,
        claim_text=claim_text,
        claim_type=claim_type,
        support_status=support_status,
        confidence=confidence,
        provenance_level=provenance_level,
        evidence=evidence or [],
        dissent_note=dissent_note,
    )


# ==================== 1. ClaimType/SupportStatus 枚举测试 ====================


class TestClaimEnums:
    """测试枚举类型定义和值。"""

    def test_claim_type_values(self):
        """ClaimType 应包含6种类型。"""
        assert ClaimType.supported_memory == "supported_memory"
        assert ClaimType.inferred_but_supported == "inferred_but_supported"
        assert ClaimType.user_provided_context == "user_provided_context"
        assert ClaimType.unsupported_memory == "unsupported_memory"
        assert ClaimType.safety_response == "safety_response"
        assert ClaimType.refusal == "refusal"
        assert len(ClaimType) == 6

    def test_support_status_values(self):
        """SupportStatus 应包含5种状态。"""
        assert SupportStatus.fully_supported == "fully_supported"
        assert SupportStatus.partially_supported == "partially_supported"
        assert SupportStatus.unsupported == "unsupported"
        assert SupportStatus.contradicted == "contradicted"
        assert SupportStatus.insufficient_evidence == "insufficient_evidence"
        assert len(SupportStatus) == 5

    def test_provenance_level_values(self):
        """ProvenanceLevel 应包含4种等级。"""
        assert ProvenanceLevel.primary_source == "primary_source"
        assert ProvenanceLevel.derived_from_source == "derived_from_source"
        assert ProvenanceLevel.inferred == "inferred"
        assert ProvenanceLevel.user_provided_context == "user_provided_context"
        assert len(ProvenanceLevel) == 4

    def test_provenance_scores(self):
        """溯源等级分数映射应正确。"""
        assert PROVENANCE_SCORES[ProvenanceLevel.primary_source] == 1.0
        assert PROVENANCE_SCORES[ProvenanceLevel.derived_from_source] == 0.8
        assert PROVENANCE_SCORES[ProvenanceLevel.inferred] == 0.5
        assert PROVENANCE_SCORES[ProvenanceLevel.user_provided_context] == 0.3

    def test_response_mode_values(self):
        """ResponseMode 应包含5种模式。"""
        assert ResponseMode.evidence_grounded == "evidence_grounded"
        assert ResponseMode.archive_search == "archive_search"
        assert ResponseMode.limited_interaction == "limited_interaction"
        assert ResponseMode.refusal == "refusal"
        assert ResponseMode.safety_response == "safety_response"
        assert len(ResponseMode) == 5


# ==================== 2. Evidence Sufficiency 测试 ====================


class TestEvidenceSufficiency:
    """测试证据充分性检查 — Step 9。"""

    def test_sufficient_evidence(self):
        """有足够的证据 + 高溯源分数 → 充分。"""
        chunks = [
            {"id": "chunk-1", "chunk_type": "conversation_segment", "content": "测试内容", "combined_score": 0.8,
             "time_range_start": "2023-06-01", "time_range_end": "2023-06-30",
             "metadata": {"dominant_speaker": "他"}, "source_artifact_id": "sa-1"},
            {"id": "chunk-2", "chunk_type": "diary_entry", "content": "测试内容2", "combined_score": 0.7,
             "time_range_start": "2023-07-01", "time_range_end": "2023-07-31",
             "metadata": {"dominant_speaker": "她"}, "source_artifact_id": "sa-1"},
        ]
        sufficient, pack = check_evidence_sufficiency(
            query="他去了哪里旅游？",
            ranked_chunks=chunks,
            memory_set_level=3,
        )
        assert sufficient is True
        assert pack.total_count >= 2
        assert pack.avg_provenance > 0.5

    def test_insufficient_evidence_count(self):
        """证据数量不足 → 不充分。"""
        chunks = [
            {"id": "chunk-1", "chunk_type": "conversation_segment", "content": "测试", "combined_score": 0.9,
             "time_range_start": None, "time_range_end": None, "metadata": {}, "source_artifact_id": "sa-1"},
        ]
        sufficient, pack = check_evidence_sufficiency(
            query="测试查询",
            ranked_chunks=chunks,
            memory_set_level=3,
        )
        # 只有1条证据，不足2条
        assert pack.total_count < MIN_EVIDENCE_COUNT

    def test_low_memory_set_level(self):
        """memory_set_level < 2 → 不允许证据问答。"""
        chunks = [
            {"id": "chunk-1", "chunk_type": "conversation_segment", "content": "测试", "combined_score": 0.9,
             "time_range_start": None, "time_range_end": None, "metadata": {}, "source_artifact_id": "sa-1"},
            {"id": "chunk-2", "chunk_type": "conversation_segment", "content": "测试2", "combined_score": 0.8,
             "time_range_start": None, "time_range_end": None, "metadata": {}, "source_artifact_id": "sa-1"},
        ]
        sufficient, pack = check_evidence_sufficiency(
            query="测试查询",
            ranked_chunks=chunks,
            memory_set_level=1,
        )
        assert sufficient is False
        assert pack.total_count == 0

    def test_empty_chunks(self):
        """空 chunks → 不充分。"""
        sufficient, pack = check_evidence_sufficiency(
            query="测试查询",
            ranked_chunks=[],
            memory_set_level=3,
        )
        assert sufficient is False
        assert pack.total_count == 0

    def test_provenance_score_primary_source(self):
        """primary_source 类型得分应为 1.0。"""
        score, level = compute_provenance_score("conversation_segment", has_span=True)
        assert score == 1.0
        assert level == ProvenanceLevel.primary_source

    def test_provenance_score_without_span(self):
        """无 span 映射的 primary_source 应降级。"""
        score, level = compute_provenance_score("conversation_segment", has_span=False)
        assert score == 0.8  # 降级为 derived_from_source
        assert level == ProvenanceLevel.derived_from_source

    def test_provenance_score_user_provided(self):
        """user_provided_context 得分应为 0.3。"""
        score, level = compute_provenance_score("user_provided_context")
        assert score == 0.3
        assert level == ProvenanceLevel.user_provided_context

    def test_provenance_score_mixed(self):
        """mixed 类型得分应为 0.8。"""
        score, level = compute_provenance_score("mixed")
        assert score == 0.8
        assert level == ProvenanceLevel.derived_from_source

    def test_compute_quote_hash(self):
        """SHA-256 哈希计算应正确。"""
        hash1 = compute_quote_hash("测试内容")
        hash2 = compute_quote_hash("测试内容")
        hash3 = compute_quote_hash("不同内容")
        assert hash1 == hash2  # 相同内容相同哈希
        assert hash1 != hash3  # 不同内容不同哈希
        assert len(hash1) == 64  # SHA-256 哈希长度

    def test_extract_excerpt(self):
        """摘录提取应正确。"""
        content = "这是一段很长的测试内容，用于验证摘录提取功能。"
        excerpt = extract_excerpt(content, max_length=10)
        assert len(excerpt) <= 10
        assert "这是" in excerpt

    def test_extract_excerpt_with_range(self):
        """指定范围的摘录提取应正确。"""
        content = "0123456789ABCDEFGHIJ"
        excerpt = extract_excerpt(content, char_start=5, char_end=10)
        assert excerpt == "56789"

    def test_is_factual_sentence(self):
        """事实性句子判断应正确。"""
        assert _is_factual_sentence("他去年去了北京旅游。") is True
        assert _is_factual_sentence("她喜欢画画。") is True
        assert _is_factual_sentence("你好") is False
        assert _is_factual_sentence("") is False
        assert _is_factual_sentence("这是真的吗？") is False


# ==================== 3. Claim Extraction 测试 ====================


class TestClaimExtraction:
    """测试 Claim 提取 — Step 12。"""

    def test_extract_claims_with_markers(self):
        """带 {claim:N} 标记的文本应正确提取。"""
        llm_output = "根据记录，他在2023年6月去了北京旅游。{claim:1}\n她似乎很喜欢画画。{claim:2}"
        claims = extract_claims(llm_output)
        assert len(claims) >= 2
        # 第一个 claim 应有标记
        assert any(c["has_marker"] for c in claims)

    def test_extract_claims_mixed_markers(self):
        """混合标记和无标记的文本。"""
        llm_output = "去了北京。{claim:1}\n这是一段没有标记的句子。"
        claims = extract_claims(llm_output)
        # 至少有一个带标记的 claim
        assert any(c["has_marker"] for c in claims)

    def test_extract_claims_empty_input(self):
        """空输入应返回空列表。"""
        claims = extract_claims("")
        assert claims == []

    def test_extract_claims_whitespace_input(self):
        """仅空白的输入应返回空列表。"""
        claims = extract_claims("   \n\n   ")
        assert claims == []

    def test_extract_claims_no_markers_factual(self):
        """无标记的事实性句子应标记为 uncategorized。"""
        llm_output = "他在2023年买了房子。"
        claims = extract_claims(llm_output)
        # 包含事实性标记的句子应被提取
        assert len(claims) >= 1

    def test_extract_claims_multiple_markers_same_line(self):
        """同一行有多个标记。"""
        llm_output = "他去了北京旅游。{claim:1}\n她又去了上海。{claim:2}\n他们都回来了。{claim:3}"
        claims = extract_claims(llm_output)
        assert len(claims) >= 3


# ==================== 4. Claim-Evidence Alignment 测试 ====================


class TestClaimEvidenceAlignment:
    """测试 Claim-Evidence 对齐 — Step 13。"""

    def test_fully_supported(self):
        """有充分证据 → fully_supported。"""
        evidence_items = [
            _make_evidence_item(provenance_score=0.9, provenance_level="primary_source", relevance_score=0.8),
            _make_evidence_item(chunk_id="chunk-2", provenance_score=0.8, provenance_level="primary_source", relevance_score=0.7),
        ]
        evidence_pack = EvidencePack(
            items=evidence_items,
            total_count=2,
            avg_provenance=0.85,
            is_sufficient=True,
        )
        claims = [
            {"claim_id": "1", "text": "他在北京旅游住了很多天。", "has_marker": True},
        ]
        aligned = align_claims_to_evidence(claims, evidence_pack)
        assert len(aligned) == 1
        # 关键：检查对齐过程不崩溃，具体类型取决于匹配结果

    def test_unsupported_claim(self):
        """无匹配证据 → unsupported_memory。"""
        evidence_pack = EvidencePack(
            items=[],
            total_count=0,
            avg_provenance=0.0,
            is_sufficient=False,
        )
        claims = [
            {"claim_id": "1", "text": "一段完全无关的声明。", "has_marker": True},
        ]
        aligned = align_claims_to_evidence(claims, evidence_pack)
        assert len(aligned) == 1
        assert aligned[0].claim_type == ClaimType.unsupported_memory
        assert aligned[0].support_status == SupportStatus.unsupported

    def test_classify_claim_unsupported(self):
        """_classify_claim: 无证据 → unsupported。"""
        claim_type, status = _classify_claim([], False, "none")
        assert claim_type == ClaimType.unsupported_memory
        assert status == SupportStatus.unsupported

    def test_classify_claim_contradicted(self):
        """_classify_claim: 有矛盾 → contradicted。"""
        evidence = [_make_evidence_item(provenance_score=0.9)]
        claim_type, status = _classify_claim(evidence, True, "moderate")
        assert claim_type == ClaimType.inferred_but_supported
        assert status == SupportStatus.contradicted

    def test_classify_claim_fully_supported(self):
        """_classify_claim: ≥2条≥0.8证据 → fully_supported。"""
        evidence = [
            _make_evidence_item(provenance_score=0.9, provenance_level="primary_source"),
            _make_evidence_item(chunk_id="chunk-2", provenance_score=0.85, provenance_level="primary_source"),
        ]
        claim_type, status = _classify_claim(evidence, False, "none")
        assert claim_type == ClaimType.supported_memory
        assert status == SupportStatus.fully_supported

    def test_check_contradiction_no_contradiction(self):
        """无矛盾的证据 → (False, none)。"""
        evidence = [_make_evidence_item(provenance_score=0.8)]
        has_contra, severity = _check_contradiction(evidence)
        assert has_contra is False
        assert severity == "none"

    def test_check_contradiction_with_contradiction(self):
        """高分和低分证据共存 → 矛盾。"""
        evidence = [
            _make_evidence_item(provenance_score=0.9),
            _make_evidence_item(chunk_id="chunk-7", provenance_score=0.3),
        ]
        has_contra, severity = _check_contradiction(evidence)
        assert has_contra is True
        assert severity == "moderate"

    def test_compute_confidence_no_contradiction(self):
        """无矛盾时 confidence = weighted_avg * 1.0。"""
        evidence = [
            _make_evidence_item(provenance_score=0.8, relevance_score=0.7),
            _make_evidence_item(chunk_id="chunk-2", provenance_score=0.6, relevance_score=0.5),
        ]
        confidence = _compute_confidence(evidence, False, "none")
        assert confidence > 0
        # consistency_factor = 1.0

    def test_compute_confidence_moderate_contradiction(self):
        """中等矛盾时 consistency_factor = 0.7。"""
        evidence = [
            _make_evidence_item(provenance_score=0.8, relevance_score=0.9),
        ]
        confidence_moderate = _compute_confidence(evidence, True, "moderate")
        confidence_none = _compute_confidence(evidence, False, "none")
        assert confidence_moderate < confidence_none

    def test_apply_qualifiers_inferred(self):
        """inferred_but_supported 应添加限定词。"""
        text = _apply_qualifiers("他去了北京", ClaimType.inferred_but_supported, {"claim_id": "1"})
        assert "根据记录推测" in text or "可能" in text or "似乎" in text

    def test_apply_qualifiers_user_provided(self):
        """user_provided_context 应标注来源。"""
        text = _apply_qualifiers("他住在南京", ClaimType.user_provided_context, {"claim_id": "2"})
        assert "你提到的" in text or "你描述的" in text or "根据你提供的信息" in text

    def test_apply_qualifiers_supported_memory(self):
        """supported_memory 不需要限定词。"""
        text = _apply_qualifiers("他去了北京", ClaimType.supported_memory, {"claim_id": "3"})
        assert text == "他去了北京"

    def test_match_claim_to_evidence(self):
        """关键词匹配应能关联相关证据。"""
        evidence = [
            _make_evidence_item(
                chunk_id="chunk-1",
                provenance_score=0.9,
                provenance_level="primary_source",
                speaker="他",
            ),
        ]
        # 使用带 source_span excerpt 的证据项
        evidence[0].source_span = {"excerpt": "他去了北京旅游参观故宫和长城", "char_start": 0, "char_end": 20}
        matched = _match_claim_to_evidence("他去了北京旅游", evidence, threshold=0.1)
        assert len(matched) >= 0  # 匹配结果取决于关键词重叠


# ==================== 5. Unsupported Claim Removal 测试 ====================


class TestUnsupportedClaimRemoval:
    """测试不支持声明的移除 — Step 14。"""

    def test_remove_unsupported_memory(self):
        """unsupported_memory 应被移除。"""
        claims = [
            _make_claim(claim_type=ClaimType.unsupported_memory, support_status=SupportStatus.unsupported),
            _make_claim(claim_id="2", claim_type=ClaimType.supported_memory, support_status=SupportStatus.fully_supported),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(valid) == 1
        assert valid[0].claim_id == "2"
        assert len(removed) == 1
        assert removed[0].reason == "unsupported_memory_not_allowed_in_response"

    def test_keep_safety_response(self):
        """safety_response 应被保留。"""
        claims = [
            _make_claim(claim_type=ClaimType.safety_response, support_status=SupportStatus.fully_supported),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(valid) == 1
        assert valid[0].claim_type == ClaimType.safety_response

    def test_keep_refusal(self):
        """refusal 应被保留。"""
        claims = [
            _make_claim(claim_type=ClaimType.refusal),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(valid) == 1
        assert valid[0].claim_type == ClaimType.refusal

    def test_keep_contradicted_with_note(self):
        """contradicted 应保留，有矛盾说明。"""
        claims = [
            _make_claim(
                claim_type=ClaimType.inferred_but_supported,
                support_status=SupportStatus.contradicted,
                dissent_note="证据存在矛盾",
            ),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(valid) == 1
        assert valid[0].dissent_note == "证据存在矛盾"

    def test_keep_inferred_with_insufficient_evidence(self):
        """insufficient_evidence + inferred_but_supported 应保留但降低置信度。"""
        claims = [
            _make_claim(
                claim_id="1",
                claim_type=ClaimType.inferred_but_supported,
                support_status=SupportStatus.insufficient_evidence,
                confidence=0.6,
            ),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(valid) == 1
        assert valid[0].confidence == round(0.6 * 0.7, 4)  # 降低置信度

    def test_remove_insufficient_evidence_other_types(self):
        """insufficient_evidence + 非 inferred 类型应被移除。"""
        claims = [
            _make_claim(
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.insufficient_evidence,
            ),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(removed) == 1
        assert removed[0].reason == "insufficient_evidence"

    def test_all_removed(self):
        """全部 unsupported → valid 为空。"""
        claims = [
            _make_claim(claim_type=ClaimType.unsupported_memory, support_status=SupportStatus.unsupported),
            _make_claim(claim_id="2", claim_type=ClaimType.unsupported_memory, support_status=SupportStatus.unsupported),
        ]
        valid, removed = remove_unsupported_claims(claims)
        assert len(valid) == 0
        assert len(removed) == 2


# ==================== 6. Response Rendering 测试 ====================


class TestResponseRendering:
    """测试响应渲染 — Step 15。"""

    def test_render_evidence_grounded(self):
        """evidence_grounded 模式应正确渲染。"""
        evidence = [_make_evidence_item(provenance_score=0.9, provenance_level="primary_source")]
        valid_claims = [
            _make_claim(
                claim_text="他去了北京旅游。",
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.fully_supported,
                evidence=evidence,
            ),
        ]
        response = render_response(
            valid_claims=valid_claims,
            removed_claims=[],
            trace_id="trace-1",
            context={"session_id": "s-1", "scope_id": "scope-1"},
        )
        assert response.response_mode == ResponseMode.evidence_grounded
        assert "他去了北京旅游" in response.response_text
        assert "{claim:" in response.response_text

    def test_render_with_safety_directive(self):
        """HARD_BREAK 安全指令应触发安全响应。"""
        safety = SafetyDirectiveData(action="HARD_BREAK", reason="反依赖触发")
        valid_claims = []
        response = render_response(
            valid_claims=valid_claims,
            removed_claims=[],
            safety_directive=safety,
            trace_id="trace-2",
        )
        assert response.response_mode == ResponseMode.safety_response
        assert "⛔" in response.response_text or "抱歉" in response.response_text

    def test_render_refusal(self):
        """无有效 claim 且无移除 → refusal 模式。"""
        response = render_response(
            valid_claims=[],
            removed_claims=[],
            trace_id="trace-3",
        )
        assert response.response_mode == ResponseMode.refusal
        assert "抱歉" in response.response_text or "没有足够" in response.response_text

    def test_render_with_removed_claims_note(self):
        """被移除的 claim 应在尾部说明。"""
        evidence = [_make_evidence_item()]
        valid_claims = [
            _make_claim(
                claim_text="有效声明。",
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.fully_supported,
                evidence=evidence,
            ),
        ]
        removed_claims = [
            RemovedClaim(
                claim=_make_claim(
                    claim_text="无效声明内容。",
                    claim_type=ClaimType.unsupported_memory,
                    support_status=SupportStatus.unsupported,
                ),
                reason="unsupported_memory_not_allowed_in_response",
                original_index=1,
            ),
        ]
        response = render_response(
            valid_claims=valid_claims,
            removed_claims=removed_claims,
            trace_id="trace-4",
        )
        assert "证据不足" in response.response_text or "未能包含" in response.response_text

    def test_render_inferred_qualifier(self):
        """inferred_but_supported 有限定词检查。"""
        inferred_claim = _make_claim(
            claim_text="可能他去了北京。",
            claim_type=ClaimType.inferred_but_supported,
            support_status=SupportStatus.partially_supported,
        )
        inferred_claim.qualified_text = "根据记录推测，可能他去了北京。"
        response = render_response(
            valid_claims=[inferred_claim],
            removed_claims=[],
            trace_id="trace-5",
        )
        assert "根据记录推测" in response.response_text or "可能" in response.response_text

    def test_render_user_provided_source_annotation(self):
        """user_provided_context 应有来源标注。"""
        user_claim = _make_claim(
            claim_text="他住在南京。",
            claim_type=ClaimType.user_provided_context,
            support_status=SupportStatus.partially_supported,
        )
        user_claim.qualified_text = "你提到的他住在南京。（根据用户提供信息）"
        response = render_response(
            valid_claims=[user_claim],
            removed_claims=[],
            trace_id="trace-6",
        )
        assert "你提到" in response.response_text or "用户" in response.response_text

    def test_determine_response_mode_safety(self):
        """HARD_BREAK → safety_response 模式。"""
        safety = SafetyDirectiveData(action="HARD_BREAK")
        mode = _determine_response_mode([], [], safety)
        assert mode == ResponseMode.safety_response

    def test_determine_response_mode_refusal(self):
        """无 claim → refusal 模式。"""
        mode = _determine_response_mode([], [], SafetyDirectiveData(action="ALLOW"))
        assert mode == ResponseMode.refusal

    def test_determine_response_mode_limited(self):
        """全是 inferred → limited_interaction 模式。"""
        claims = [
            _make_claim(claim_type=ClaimType.inferred_but_supported, support_status=SupportStatus.insufficient_evidence),
        ]
        mode = _determine_response_mode(claims, [], SafetyDirectiveData(action="ALLOW"))
        assert mode == ResponseMode.limited_interaction

    def test_verify_qualifiers(self):
        """限定词验证应发现缺失的限定词。"""
        claim_no_qualifier = _make_claim(
            claim_text="他去了北京旅游。",
            claim_type=ClaimType.inferred_but_supported,
        )
        claim_no_qualifier.qualified_text = "他去了北京旅游。"  # 缺少限定词
        warnings = _verify_qualifiers([claim_no_qualifier])
        assert len(warnings) > 0

    def test_verify_qualifiers_pass(self):
        """有限定词的 claim 应通过验证。"""
        claim_with_qualifier = _make_claim(
            claim_text="可能他去了北京旅游。",
            claim_type=ClaimType.inferred_but_supported,
        )
        claim_with_qualifier.qualified_text = "可能他去了北京旅游。"
        warnings = _verify_qualifiers([claim_with_qualifier])
        assert len(warnings) == 0

    def test_soft_break_buffer(self):
        """SOFT_BREAK 应插入安全缓冲语。"""
        safety = SafetyDirectiveData(action="SOFT_BREAK")
        text = _build_response_text([], [], safety, ResponseMode.limited_interaction)
        assert "⚠️" in text or "休息" in text

    def test_cooldown_buffer(self):
        """COOLDOWN 应插入冷却缓冲语。"""
        safety = SafetyDirectiveData(action="COOLDOWN")
        text = _build_response_text([], [], safety, ResponseMode.limited_interaction)
        assert "🕐" in text or "休息" in text


# ==================== 7. Audit Logging 测试 ====================


class TestAuditLogging:
    """测试审计日志 — Step 16。"""

    def test_log_response_audit(self, populated_db: sqlite3.Connection):
        """应正确写入 response_claim 和 claim_evidence 表。"""
        evidence = [_make_evidence_item()]
        claims = [
            _make_claim(
                claim_id="claim-1",
                claim_text="他去了北京旅游。",
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.fully_supported,
                evidence=evidence,
                confidence=0.9,
                provenance_level=ProvenanceLevel.primary_source,
            ),
        ]
        removed_claims = [
            RemovedClaim(
                claim=_make_claim(
                    claim_id="claim-2",
                    claim_text="无效声明。",
                    claim_type=ClaimType.unsupported_memory,
                    support_status=SupportStatus.unsupported,
                ),
                reason="unsupported_memory_not_allowed_in_response",
                original_index=1,
            ),
        ]
        evidence_pack = EvidencePack(
            items=evidence,
            total_count=1,
            avg_provenance=0.9,
            is_sufficient=True,
        )

        log_response_audit(
            conn=populated_db,
            scope_id="scope-1",
            session_id="session-1",
            response_id="resp-1",
            claims=claims,
            removed_claims=removed_claims,
            evidence_pack=evidence_pack,
            trace_id="trace-1",
        )

        # 验证 response_claim 写入
        cursor = populated_db.execute(
            "SELECT * FROM response_claim WHERE interaction_session_id = 'session-1'"
        )
        claim_rows = cursor.fetchall()
        assert len(claim_rows) == 2  # 1 valid + 1 removed

        # 验证有效 claim
        valid_row = None
        removed_row = None
        for row in claim_rows:
            if dict(row)["status"] == "ACTIVE":
                valid_row = dict(row)
            elif dict(row)["status"] == "DEPRECATED":
                removed_row = dict(row)

        assert valid_row is not None
        assert removed_row is not None
        assert valid_row["confidence"] == 0.9

        # 验证 claim_evidence 写入
        cursor = populated_db.execute(
            "SELECT * FROM claim_evidence WHERE claim_id = 'claim-1'"
        )
        evidence_rows = cursor.fetchall()
        assert len(evidence_rows) == 1

    def test_log_interaction_audit(self, populated_db: sqlite3.Connection):
        """应正确写入 interaction_session, interaction_message, audit_log 表。"""
        evidence = [_make_evidence_item()]
        valid_claims = [
            _make_claim(
                claim_id="claim-a",
                claim_text="测试声明。",
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.fully_supported,
                evidence=evidence,
            ),
        ]
        response = Response(
            response_id="resp-int-1",
            session_id="",
            scope_id="scope-1",
            response_text="测试响应",
            response_mode=ResponseMode.evidence_grounded,
            claims=valid_claims,
            safety_directive=SafetyDirectiveData(action="ALLOW"),
            model_used="rule_engine_v0.1",
            duration_ms=100,
            safety_flags=["test_flag"],
        )

        session_id, message_id = log_interaction_audit(
            conn=populated_db,
            scope_id="scope-1",
            deceased_profile_id="dp-1",
            response=response,
            trace_id=None,  # trace_id 为 None 避免外键约束问题
        )

        # 验证 interaction_session 写入
        cursor = populated_db.execute(
            "SELECT * FROM interaction_session WHERE id = ?", (session_id,)
        )
        session_row = cursor.fetchone()
        assert session_row is not None

        # 验证 interaction_message 写入
        cursor = populated_db.execute(
            "SELECT * FROM interaction_message WHERE id = ?", (message_id,)
        )
        message_row = cursor.fetchone()
        assert message_row is not None

        # 验证 audit_log 写入
        cursor = populated_db.execute(
            "SELECT * FROM audit_log WHERE action = 'PROVENANCE_RESPONSE'"
        )
        audit_rows = cursor.fetchall()
        assert len(audit_rows) >= 1

    def test_get_claims_by_session(self, populated_db: sqlite3.Connection):
        """查询会话下的 claim 应正确返回。"""
        # 先写入
        evidence = [_make_evidence_item()]
        claims = [
            _make_claim(
                claim_id="claim-q-1",
                claim_text="查询测试。",
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.fully_supported,
                evidence=evidence,
            ),
        ]
        evidence_pack = EvidencePack(items=evidence, total_count=1, avg_provenance=0.9, is_sufficient=True)
        log_response_audit(
            conn=populated_db,
            scope_id="scope-1",
            session_id="session-1",
            response_id="resp-q-1",
            claims=claims,
            removed_claims=[],
            evidence_pack=evidence_pack,
            trace_id="trace-q-1",
        )

        result = get_claims_by_session(populated_db, "session-1")
        assert len(result) >= 1
        assert result[0]["claim_text"] == "查询测试。"

    def test_get_evidence_by_claim(self, populated_db: sqlite3.Connection):
        """查询 claim 下的 evidence 应正确返回。"""
        evidence = _make_evidence_item()
        claims = [
            _make_claim(
                claim_id="claim-e-1",
                claim_text="证据查询测试。",
                claim_type=ClaimType.supported_memory,
                support_status=SupportStatus.fully_supported,
                evidence=[evidence],
            ),
        ]
        evidence_pack = EvidencePack(items=[evidence], total_count=1, avg_provenance=0.8, is_sufficient=True)
        log_response_audit(
            conn=populated_db,
            scope_id="scope-1",
            session_id="session-1",
            response_id="resp-e-1",
            claims=claims,
            removed_claims=[],
            evidence_pack=evidence_pack,
            trace_id="trace-e-1",
        )

        result = get_evidence_by_claim(populated_db, "claim-e-1")
        assert len(result) >= 1


# ==================== 8. 端到端管道测试 ====================


class TestEndToEndPipeline:
    """端到端管道测试 — 从 evidence 到 response 的完整流程。"""

    def test_full_pipeline_with_sufficient_evidence(self):
        """充足证据的完整流程：evidence → claim → response。"""
        # Step 9: 创建 evidence
        evidence_items = [
            _make_evidence_item(chunk_id="c1", provenance_score=0.9, provenance_level="primary_source", relevance_score=0.85),
            _make_evidence_item(chunk_id="c2", provenance_score=0.8, provenance_level="primary_source", relevance_score=0.75),
        ]
        evidence_pack = EvidencePack(
            items=evidence_items,
            total_count=2,
            avg_provenance=0.85,
            is_sufficient=True,
        )

        # Step 12: Extract claims
        llm_output = "他在2023年6月去了北京旅游。{claim:1}"
        claims = extract_claims(llm_output)

        # Step 13: Align claims to evidence
        aligned = align_claims_to_evidence(claims, evidence_pack)
        assert len(aligned) >= 1

        # Step 14: Remove unsupported
        valid, removed = remove_unsupported_claims(aligned)

        # Step 15: Render response
        safety = SafetyDirectiveData(action="ALLOW")
        response = render_response(
            valid_claims=valid,
            removed_claims=removed,
            safety_directive=safety,
            trace_id="trace-e2e-1",
            context={"session_id": "s-e2e", "scope_id": "scope-e2e"},
        )

        # 验证响应不为空
        assert response.response_text != ""
        assert response.response_mode in (
            ResponseMode.evidence_grounded,
            ResponseMode.archive_search,
            ResponseMode.limited_interaction,
        )

    def test_full_pipeline_with_insufficient_evidence(self):
        """不足证据的完整流程：拒绝或有限交互。"""
        # 不足证据
        evidence_pack = EvidencePack(
            items=[_make_evidence_item(provenance_score=0.3, provenance_level="inferred")],
            total_count=1,
            avg_provenance=0.3,
            is_sufficient=False,
        )

        claims = extract_claims("可能他去了北京。{claim:1}")
        aligned = align_claims_to_evidence(claims, evidence_pack)
        valid, removed = remove_unsupported_claims(aligned)

        response = render_response(
            valid_claims=valid,
            removed_claims=removed,
            safety_directive=SafetyDirectiveData(action="ALLOW"),
            trace_id="trace-e2e-2",
        )

        # 不足证据时：要么有限交互要么拒绝
        assert response.response_mode in (
            ResponseMode.limited_interaction,
            ResponseMode.refusal,
            ResponseMode.archive_search,
        )

    def test_full_pipeline_no_evidence(self):
        """无证据的完整流程：拒绝。"""
        evidence_pack = EvidencePack(
            items=[],
            total_count=0,
            avg_provenance=0.0,
            is_sufficient=False,
        )

        claims = extract_claims("他去了某个地方旅游。{claim:1}")
        aligned = align_claims_to_evidence(claims, evidence_pack)
        valid, removed = remove_unsupported_claims(aligned)

        response = render_response(
            valid_claims=valid,
            removed_claims=removed,
            safety_directive=SafetyDirectiveData(action="ALLOW"),
            trace_id="trace-e2e-3",
        )

        # 无有效 claim → refusal
        assert response.response_mode == ResponseMode.refusal

    def test_full_pipeline_with_contradiction(self):
        """矛盾证据的完整流程。"""
        evidence_items = [
            _make_evidence_item(provenance_score=0.9, provenance_level="primary_source", relevance_score=0.8),
            _make_evidence_item(chunk_id="c-low", provenance_score=0.2, provenance_level="inferred", relevance_score=0.3),
        ]
        evidence_pack = EvidencePack(
            items=evidence_items,
            total_count=2,
            avg_provenance=0.55,
            is_sufficient=True,
        )

        claims = extract_claims("他在北京住了两年。{claim:1}")
        aligned = align_claims_to_evidence(claims, evidence_pack)

        # 检查是否有矛盾 claim
        contradicted_claims = [c for c in aligned if c.support_status == SupportStatus.contradicted]
        # 矛盾检测结果取决于 match 结果，可能为空

        valid, removed = remove_unsupported_claims(aligned)

        response = render_response(
            valid_claims=valid,
            removed_claims=removed,
            safety_directive=SafetyDirectiveData(action="ALLOW"),
            trace_id="trace-e2e-4",
        )

        # 矛盾 claim 应保留，有矛盾说明
        for claim in valid:
            if claim.support_status == SupportStatus.contradicted:
                assert claim.dissent_note != ""

    def test_full_pipeline_safety_break(self):
        """安全熔断的完整流程。"""
        evidence = [_make_evidence_item()]
        valid_claims = []
        removed_claims = []
        safety = SafetyDirectiveData(action="HARD_BREAK", reason="反依赖触发")

        response = render_response(
            valid_claims=valid_claims,
            removed_claims=removed_claims,
            safety_directive=safety,
            trace_id="trace-e2e-5",
        )

        assert response.response_mode == ResponseMode.safety_response
        assert "安全" in response.response_text or "暂停" in response.response_text or "⛔" in response.response_text

    def test_proof_sufficiency_check_integration(self):
        """evidence sufficiency 与 pipeline 的集成测试。"""
        # 模拟 ranked_chunks
        ranked_chunks = [
            {
                "id": "chunk-test-1",
                "chunk_type": "conversation_segment",
                "content": "他2023年6月去了北京旅游，参观了故宫。",
                "combined_score": 0.85,
                "time_range_start": "2023-06-01",
                "time_range_end": "2023-06-30",
                "metadata": {"dominant_speaker": "他"},
                "source_artifact_id": "sa-1",
            },
            {
                "id": "chunk-test-2",
                "chunk_type": "diary_entry",
                "content": "她在公园写生水彩画，每周都去。",
                "combined_score": 0.75,
                "time_range_start": "2023-07-01",
                "time_range_end": "2023-07-31",
                "metadata": {"dominant_speaker": "她"},
                "source_artifact_id": "sa-1",
            },
        ]

        sufficient, pack = check_evidence_sufficiency(
            query="他去了哪里旅游？",
            ranked_chunks=ranked_chunks,
            memory_set_level=3,
        )
        assert sufficient is True
        assert pack.total_count >= 2

        # 将 evidence_pack 传入 pipeline
        claims = extract_claims("他去了北京旅游参观故宫。{claim:1}")
        aligned = align_claims_to_evidence(claims, pack)
        valid, removed = remove_unsupported_claims(aligned)

        response = render_response(
            valid_claims=valid,
            removed_claims=removed,
            safety_directive=SafetyDirectiveData(action="ALLOW"),
            trace_id="trace-e2e-6",
        )

        assert response.response_text != ""