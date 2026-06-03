"""Evidence Sufficiency Check — 白皮书 Step 9。

核心函数:
- check_evidence_sufficiency(): 证据充分性检查
- compute_provenance_score(): 根据 chunk_type 计算溯源分数
- compute_quote_hash(): SHA-256 内容哈希
- extract_excerpt(): 从 content 中提取摘录
- _is_factual_sentence(): 判断是否为事实性句子

规则:
- memory_set_level < 2 时不允许证据问答
- 过滤 consent 未授权的 chunk
- 对每个 chunk 验证溯源链路完整性（spans）
- 计算 evidence_count 和 avg_provenance
- 返回 (sufficient, EvidencePack)
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from remnant_core.claims import (
    EvidenceItem,
    EvidencePack,
    ProvenanceLevel,
    PROVENANCE_SCORES,
)


# chunk_type 到 ProvenanceLevel 的映射
_CHUNK_TYPE_PROVENANCE: dict[str, ProvenanceLevel] = {
    "conversation_segment": ProvenanceLevel.primary_source,
    "transcription": ProvenanceLevel.primary_source,
    "diary_entry": ProvenanceLevel.primary_source,
    "letter": ProvenanceLevel.primary_source,
    "mixed": ProvenanceLevel.derived_from_source,
    "user_provided_context": ProvenanceLevel.user_provided_context,
}

# 证据充分性阈值
MIN_EVIDENCE_COUNT = 2
MIN_AVG_PROVENANCE = 0.5
MIN_MEMORY_SET_LEVEL = 2


def compute_provenance_score(chunk_type: str, has_span: bool = True) -> tuple[float, ProvenanceLevel]:
    """根据 chunk_type 计算溯源分数和等级。

    规则:
    - conversation_segment/transcription/diary_entry/letter: primary_source (1.0)
    - mixed: derived_from_source (0.8)
    - user_provided_context: user_provided_context (0.3)
    - 无 span 映射的 chunk 降级一级

    Args:
        chunk_type: 记忆分块类型
        has_span: 是否有溯源映射（span）

    Returns:
        (provenance_score, provenance_level) 元组
    """
    level = _CHUNK_TYPE_PROVENANCE.get(chunk_type, ProvenanceLevel.inferred)
    score = PROVENANCE_SCORES[level]

    # 无 span 映射的 chunk 降级：溯源链路不完整
    if not has_span and level in (ProvenanceLevel.primary_source, ProvenanceLevel.derived_from_source):
        # 降级一级
        if level == ProvenanceLevel.primary_source:
            level = ProvenanceLevel.derived_from_source
            score = PROVENANCE_SCORES[level]
        elif level == ProvenanceLevel.derived_from_source:
            level = ProvenanceLevel.inferred
            score = PROVENANCE_SCORES[level]

    return score, level


def compute_quote_hash(content: str) -> str:
    """计算 SHA-256 内容哈希。

    Args:
        content: 原始文本内容

    Returns:
        SHA-256 哈希的十六进制字符串
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_excerpt(
    content: str,
    char_start: int = 0,
    char_end: int | None = None,
    max_length: int = 200,
) -> str:
    """从 content 中提取摘录。

    如果指定了 char_start 和 char_end，提取对应子串；
    否则返回前 max_length 个字符。

    Args:
        content: 原始文本
        char_start: 起始字符偏移（默认 0）
        char_end: 结束字符偏移（默认 None，表示到末尾）
        max_length: 最大摘录长度

    Returns:
        提取的摘录文本
    """
    if char_end is not None and char_start < char_end:
        excerpt = content[char_start:char_end]
    else:
        excerpt = content[:max_length]

    if len(excerpt) > max_length:
        excerpt = excerpt[:max_length - 3] + "..."

    return excerpt


def _check_span_integrity(
    conn: sqlite3.Connection,
    chunk_id: str,
) -> bool:
    """检查 chunk 的溯源链路完整性（是否有 span 记录）。

    Args:
        conn: 数据库连接
        chunk_id: 记忆分块 ID

    Returns:
        True 如果 chunk 有至少一条 span 记录
    """
    cursor = conn.execute(
        "SELECT COUNT(*) FROM memory_chunk_span WHERE chunk_id = ?",
        (chunk_id,),
    )
    count = cursor.fetchone()[0]
    return count > 0


def _filter_consent_chunks(
    conn: sqlite3.Connection,
    chunk_ids: list[str],
    scope_id: str,
) -> tuple[list[str], list[str]]:
    """过滤未授权的 chunk。

    检查 data_subject_consent 表，过滤掉未授权或已撤回的 chunk。

    Args:
        conn: 数据库连接
        chunk_ids: 候选 chunk ID 列表
        scope_id: 关系作用域 ID

    Returns:
        (allowed_ids, rejected_ids) 元组
    """
    if not chunk_ids:
        return [], []

    # 查询已授权的数据类别
    placeholders = ",".join("?" * len(chunk_ids))
    cursor = conn.execute(
        f"""SELECT mc.id, mc.chunk_type
        FROM memory_chunk mc
        LEFT JOIN data_subject_consent dsc
            ON dsc.relationship_scope_id = ?
            AND dsc.consent_type = 'granted'
            AND dsc.withdrawn_at IS NULL
        WHERE mc.id IN ({placeholders})
          AND mc.status = 'ACTIVE'
          AND mc.deleted_at IS NULL""",
        (scope_id, *chunk_ids),
    )

    # chunk_type 为 'user_provided_context' 时需要 consent_scope >= query
    allowed_ids: list[str] = []
    all_rows = cursor.fetchall()

    for row in all_rows:
        chunk_id = row[0]
        chunk_type = row[1]

        if chunk_type == "user_provided_context":
            # user_provided_context 需要专门的 consent
            consent_cursor = conn.execute(
                """SELECT COUNT(*) FROM data_subject_consent
                WHERE relationship_scope_id = ?
                  AND data_category = 'raw_text'
                  AND consent_type = 'granted'
                  AND consent_scope IN ('query', 'annotate', 'destroy')
                  AND withdrawn_at IS NULL""",
                (scope_id,),
            )
            has_consent = consent_cursor.fetchone()[0] > 0
            if has_consent:
                allowed_ids.append(chunk_id)
        else:
            allowed_ids.append(chunk_id)

    rejected_ids = [cid for cid in chunk_ids if cid not in allowed_ids]
    return allowed_ids, rejected_ids


def check_evidence_sufficiency(
    query: str,
    ranked_chunks: list[dict[str, Any]],
    memory_set_level: int = 2,
    min_evidence_count: int = MIN_EVIDENCE_COUNT,
    min_avg_provenance: float = MIN_AVG_PROVENANCE,
    conn: sqlite3.Connection | None = None,
    scope_id: str = "",
) -> tuple[bool, EvidencePack]:
    """证据充分性检查 — 白皮书 Step 9。

    检查规则:
    1. memory_set_level < 2 时不允许证据问答
    2. 过滤 consent 未授权的 chunk
    3. 对每个 chunk 验证溯源链路完整性（spans）
    4. 计算 evidence_count 和 avg_provenance
    5. 返回 (sufficient, EvidencePack)

    Args:
        query: 用户查询
        ranked_chunks: 检索排序后的 chunk 列表（来自 hybrid_retrieve）
        memory_set_level: 记忆集等级（< 2 时不允许证据问答）
        min_evidence_count: 最小证据数量阈值
        min_avg_provenance: 最小平均溯源分数阈值
        conn: 数据库连接（可选，用于 consent 和 span 检查）
        scope_id: 关系作用域 ID

    Returns:
        (sufficient, EvidencePack) 元组
    """
    pack = EvidencePack()

    # Rule 1: memory_set_level < 2 时不允许证据问答
    if memory_set_level < MIN_MEMORY_SET_LEVEL:
        pack.is_sufficient = False
        pack.total_count = 0
        pack.avg_provenance = 0.0
        return False, pack

    if not ranked_chunks:
        pack.is_sufficient = False
        return False, pack

    # Rule 2: 过滤 consent 未授权的 chunk
    chunk_ids = [c.get("id", "") for c in ranked_chunks]
    allowed_ids: list[str] = []
    rejected_ids: list[str] = []

    if conn is not None and scope_id:
        allowed_ids, rejected_ids = _filter_consent_chunks(conn, chunk_ids, scope_id)
    else:
        # 无数据库连接时，假设所有 chunk 都允许
        allowed_ids = chunk_ids

    # 构建 EvidenceItem 列表
    evidence_items: list[EvidenceItem] = []
    rejected_items: list[EvidenceItem] = []

    for chunk in ranked_chunks:
        chunk_id = chunk.get("id", "")

        # 跳过不允许的 chunk
        if chunk_id not in allowed_ids:
            rejected_item = EvidenceItem(
                chunk_id=chunk_id,
                source_artifact_id=chunk.get("source_artifact_id", ""),
                speaker=chunk.get("metadata", {}).get("dominant_speaker", "") if isinstance(chunk.get("metadata"), dict) else "",
                provenance_score=0.0,
                provenance_level="unsupported",
            )
            rejected_items.append(rejected_item)
            continue

        # Rule 3: 验证溯源链路完整性
        has_span = True
        if conn is not None:
            has_span = _check_span_integrity(conn, chunk_id)

        # 计算溯源分数
        chunk_type = chunk.get("chunk_type", "mixed")
        prov_score, prov_level = compute_provenance_score(chunk_type, has_span)

        # 提取时间范围
        timestamp_range = {
            "start": chunk.get("time_range_start"),
            "end": chunk.get("time_range_end"),
        }

        # 提取内容摘录
        content = chunk.get("content", "")
        excerpt = extract_excerpt(content) if content else ""

        # 计算引用哈希
        quote_hash = compute_quote_hash(content) if content else ""

        # 构建证据项
        evidence_item = EvidenceItem(
            chunk_id=chunk_id,
            source_artifact_id=chunk.get("source_artifact_id", ""),
            timestamp_range=timestamp_range,
            source_span={"excerpt": excerpt} if excerpt else None,
            speaker=chunk.get("metadata", {}).get("dominant_speaker", "") if isinstance(chunk.get("metadata"), dict) else "",
            quote_hash=quote_hash,
            provenance_score=prov_score,
            provenance_level=prov_level.value,
            relevance_score=chunk.get("combined_score", chunk.get("vector_score", 0.0)),
        )
        evidence_items.append(evidence_item)

    # 计算充分性
    total_count = len(evidence_items)
    avg_provenance = 0.0
    if total_count > 0:
        avg_provenance = sum(e.provenance_score for e in evidence_items) / total_count

    sufficient = (
        total_count >= min_evidence_count
        and avg_provenance >= min_avg_provenance
    )

    # 构建证据包
    pack = EvidencePack(
        items=evidence_items,
        total_count=total_count,
        avg_provenance=round(avg_provenance, 4),
        is_sufficient=sufficient,
        rejected_items=rejected_items,
    )

    return sufficient, pack


def _is_factual_sentence(sentence: str) -> bool:
    """判断句子是否为事实性陈述。

    事实性句子: 包含具体的人、事、时间、地点等可验证信息。
    非事实性句子: 问候语、感叹、问题等。

    启发式规则:
    - 包含日期/时间引用（数字+年/月/日）
    - 包含人名代词（他/她/他们）
    - 包含地点引用
    - 包含具体动作描述
    - 排除疑问句、感叹句、纯寒暄

    Args:
        sentence: 待判断的句子

    Returns:
        True 如果句子是事实性陈述
    """
    if not sentence or not sentence.strip():
        return False

    stripped = sentence.strip()

    # 排除短句（< 6 个字符的中文，< 10 个字符的英文）
    if len(stripped) < 6:
        return False

    # 排除疑问句
    if stripped.endswith("?") or stripped.endswith("？"):
        return False

    # 排除感叹句（纯情感表达）
    if stripped.endswith("!") or stripped.endswith("！"):
        # 但如果包含具体信息仍然算事实性
        factual_markers = ["年", "月", "日", "时候", "地方", "去", "来", "做", "说", "觉得"]
        if not any(marker in stripped for marker in factual_markers):
            return False

    # 排除纯问候语/寒暄
    greeting_patterns = [
        "你好", "您好", "谢谢", "再见", "没事", "没关系",
        "hello", "hi", "thanks", "bye", "ok", "好的", "嗯",
    ]
    if stripped.lower() in greeting_patterns:
        return False

    # 包含事实性标记
    factual_indicators = [
        # 时间引用
        "年", "月", "日", "时候", "之前", "之后", "昨天", "今天", "明天",
        "上周", "下周", "最近", "那天", "当时",
        # 人称代词
        "他", "她", "他们", "妈妈", "爸爸", "爷爷", "奶奶", "朋友",
        # 具体动作
        "去", "来", "做", "说", "觉得", "认为", "喜欢", "讨厌",
        "买了", "送给", "参加", "毕业", "工作", "住",
        # 地点引用
        "家", "学校", "医院", "公园", "城市", "地方",
        # English factual markers
        "went", "said", "was", "had", "did", "told", "visited",
        "lived", "worked", "graduated", "married", "born",
    ]

    has_factual = any(marker in stripped for marker in factual_indicators)

    # 如果不含任何事实性标记，检查是否是描述性句子
    if not has_factual:
        # 描述性句子通常包含"是"或"有"等判断动词
        descriptive_markers = ["是", "有", "叫", "在"]
        has_descriptive = any(marker in stripped for marker in descriptive_markers)
        if not has_descriptive:
            return False

    return True