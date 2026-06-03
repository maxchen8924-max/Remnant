"""Claim 溯源响应数据结构 — 白皮书 Ch6 Response Schema。

核心数据结构:
- ClaimType: 事实声明类型枚举（supported_memory, inferred_but_supported, user_provided_context, unsupported_memory, safety_response, refusal）
- SupportStatus: 证据支持状态枚举（fully_supported, partially_supported, unsupported, contradicted, insufficient_evidence）
- ProvenanceLevel: 溯源等级枚举（primary_source, derived_from_source, inferred, user_provided_context）
- Claim: 事实声明数据类
- EvidenceItem: 证据项数据类
- EvidencePack: 证据包数据类
- Response: 完整响应数据类
- SafetyDirectiveData: 安全指令数据类（与 models.py SafetyDirective 兼容）

规则 (Ch6.3 + 6.4):
1. unsupported_memory 不进入 response_text — 必须被移除
2. inferred_but_supported 必须使用限定词
3. user_provided_context 必须标注来源
4. contradicted 的 claim 必须优先说明矛盾
5. 每个 claim 的 provenance_level 取所有 evidence 的最低值
6. confidence_score = weighted_avg * consistency_factor
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ==================== 枚举类型 ====================


class ClaimType(str, Enum):
    """事实声明类型枚举 — 白皮书 Ch6.2。

    - supported_memory: 有充分原始数据支撑
    - inferred_but_supported: 推断但有间接证据
    - user_provided_context: 用户补充信息
    - unsupported_memory: 无证据支撑（不允许出现在 response_text 中）
    - safety_response: 安全策略触发
    - refusal: 数据不足拒绝
    """
    supported_memory = "supported_memory"
    inferred_but_supported = "inferred_but_supported"
    user_provided_context = "user_provided_context"
    unsupported_memory = "unsupported_memory"
    safety_response = "safety_response"
    refusal = "refusal"


class SupportStatus(str, Enum):
    """证据支持状态枚举 — 白皮书 Ch6.2。

    - fully_supported: ≥2条 provenance_score≥0.8 的证据
    - partially_supported: 有证据但不够充分
    - unsupported: evidence 为空
    - contradicted: 存在矛盾证据
    - insufficient_evidence: 证据非空但 <0.5
    """
    fully_supported = "fully_supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    contradicted = "contradicted"
    insufficient_evidence = "insufficient_evidence"


class ProvenanceLevel(str, Enum):
    """溯源等级枚举 — 白皮书 Ch6.2。

    - primary_source: 溯源分数 1.0（原始消息直引）
    - derived_from_source: 溯源分数 0.8（分块级引用）
    - inferred: 溯源分数 0.5（推断得出）
    - user_provided_context: 溯源分数 0.3（用户提供）
    """
    primary_source = "primary_source"
    derived_from_source = "derived_from_source"
    inferred = "inferred"
    user_provided_context = "user_provided_context"


# 溯源等级到分数的映射
PROVENANCE_SCORES: dict[ProvenanceLevel, float] = {
    ProvenanceLevel.primary_source: 1.0,
    ProvenanceLevel.derived_from_source: 0.8,
    ProvenanceLevel.inferred: 0.5,
    ProvenanceLevel.user_provided_context: 0.3,
}


# ==================== 数据类 ====================


@dataclass
class EvidenceItem:
    """证据项 — 对应白皮书 Ch6.2 Evidence Schema。

    Attributes:
        chunk_id: 关联的 chunk ID
        source_artifact_id: 数据来源文件 ID
        timestamp_range: 时间范围 {start: ..., end: ...}
        source_span: 溯源映射 {char_start, char_end, excerpt}，可为 None
        speaker: 说话人
        quote_hash: SHA-256 内容哈希
        provenance_score: 溯源分数 0.0~1.0
        provenance_level: 溯源等级
        relevance_score: 与 claim 的相关性评分
    """
    chunk_id: str
    source_artifact_id: str = ""
    timestamp_range: dict[str, str | None] = field(default_factory=dict)
    source_span: dict[str, Any] | None = None
    speaker: str = ""
    quote_hash: str = ""
    provenance_score: float = 0.0
    provenance_level: str = "derived_from_source"
    relevance_score: float = 0.0


@dataclass
class Claim:
    """事实声明 — 对应白皮书 Ch6.2 Claim Schema。

    Attributes:
        claim_id: 声明唯一标识
        claim_text: 声明文本
        claim_type: 声明类型
        support_status: 证据支持状态
        confidence: 置信度 0.0~1.0
        provenance_level: 溯源等级（取所有 evidence 的最低值）
        evidence: 关联的证据列表
        dissent_note: 矛盾说明
        rejection_reason: 被拒绝/移除的原因
        qualified_text: 经过限定词处理的文本
        is_removable: 是否应被移除
    """
    claim_id: str
    claim_text: str
    claim_type: ClaimType = ClaimType.supported_memory
    support_status: SupportStatus = SupportStatus.partially_supported
    confidence: float = 0.5
    provenance_level: ProvenanceLevel = ProvenanceLevel.derived_from_source
    evidence: list[EvidenceItem] = field(default_factory=list)
    dissent_note: str = ""
    rejection_reason: str = ""
    qualified_text: str = ""
    is_removable: bool = False


@dataclass
class EvidencePack:
    """证据包 — 白皮书 Ch6.2。

    从检索结果中提取的证据集合，供 Claim-Evidence 对齐使用。

    Attributes:
        items: 证据项列表
        total_count: 总证据数量
        avg_provenance: 平均溯源分数
        is_sufficient: 是否充分
        rejected_items: 被拒绝的证据（consent 未授权等）
    """
    items: list[EvidenceItem] = field(default_factory=list)
    total_count: int = 0
    avg_provenance: float = 0.0
    is_sufficient: bool = False
    rejected_items: list[EvidenceItem] = field(default_factory=list)


@dataclass
class SafetyDirectiveData:
    """安全指令数据类 — 与 models.py SafetyDirective 兼容。

    使用 dataclass 而非 Pydantic，避免 macOS 签名问题。

    Attributes:
        action: 指令动作
        reason: 触发原因
        cooldown_minutes: 冷却期分钟数
        template_id: 安全回复模板 ID
        allow_llm: 是否允许 LLM 参与生成
        disconnect_after_response: 是否在响应后断开连接
    """
    action: str = "ALLOW"
    reason: str = ""
    cooldown_minutes: int = 0
    template_id: str = ""
    allow_llm: bool = True
    disconnect_after_response: bool = False


@dataclass
class RemovedClaim:
    """被移除的声明记录 — 用于追踪和审计。

    Attributes:
        claim: 被移除的声明
        reason: 移除原因
        original_index: 在原始列表中的位置
    """
    claim: Claim
    reason: str = ""
    original_index: int = 0


class ResponseMode(str, Enum):
    """响应模式枚举。

    - evidence_grounded: 证据充分，正常响应
    - archive_search: 证据部分充分，需要更多数据
    - limited_interaction: 证据不足，有限交互
    - refusal: 数据不足拒绝
    - safety_response: 安全策略触发
    """
    evidence_grounded = "evidence_grounded"
    archive_search = "archive_search"
    limited_interaction = "limited_interaction"
    refusal = "refusal"
    safety_response = "safety_response"


@dataclass
class Response:
    """完整响应 — 白皮书 Ch6.2 Response Schema。

    Attributes:
        response_id: 响应唯一标识
        trace_id: 检索追踪 ID
        session_id: 交互会话 ID
        scope_id: 关系作用域 ID
        response_text: 最终响应文本
        response_mode: 响应模式
        claims: 事实声明列表
        removed_claims: 被移除的声明记录
        evidence_pack: 证据包
        safety_directive: 安全指令
        model_used: 使用的 LLM 模型
        duration_ms: 生成耗时毫秒
        safety_flags: 安全标记
    """
    response_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    scope_id: str = ""
    response_text: str = ""
    response_mode: ResponseMode = ResponseMode.evidence_grounded
    claims: list[Claim] = field(default_factory=list)
    removed_claims: list[RemovedClaim] = field(default_factory=list)
    evidence_pack: EvidencePack = field(default_factory=EvidencePack)
    safety_directive: SafetyDirectiveData = field(default_factory=SafetyDirectiveData)
    model_used: str = "rule_engine_v0.1"
    duration_ms: int = 0
    safety_flags: list[str] = field(default_factory=list)