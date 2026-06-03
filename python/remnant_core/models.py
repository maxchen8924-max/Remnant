"""Pydantic 数据模型 — Remnant v0.1 全部核心模型。

基于白皮书 Ch5/Ch6/Ch9/Ch10/Ch12 定义，涵盖:
- MemoryChunkSchema（Ch5 全部字段）
- ResponseSchema（Ch6）
- ClaimSchema（Ch6）
- EvidenceSchema（Ch6）
- SafetyDirective（Ch10）
- QueryRequest / QueryResponse
- ImportRequest / ImportResponse
- ScopeCreateRequest / ScopeDeleteRequest
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ==================== 枚举类型 ====================

class ChunkType(str, Enum):
    """记忆分块类型枚举。"""
    CONVERSATION_SEGMENT = "conversation_segment"
    DIARY_ENTRY = "diary_entry"
    LETTER = "letter"
    MIXED = "mixed"
    USER_PROVIDED_CONTEXT = "user_provided_context"
    TRANSCRIPTION = "transcription"


class ConsentType(str, Enum):
    """授权类型枚举。"""
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"


class ConsentScope(str, Enum):
    """授权范围枚举。"""
    READ = "read"
    QUERY = "query"
    ANNOTATE = "annotate"
    DESTROY = "destroy"


class DataCategory(str, Enum):
    """数据类别枚举。"""
    RAW_TEXT = "raw_text"
    VOICE = "voice"
    IMAGE = "image"
    FINANCIAL = "financial"
    MEDICAL = "medical"


class RelationshipType(str, Enum):
    """关系类型枚举。"""
    CHILD = "child"
    SPOUSE = "spouse"
    SIBLING = "sibling"
    PARENT = "parent"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    OTHER = "other"


class SafetySeverity(str, Enum):
    """安全事件严重程度枚举。"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class SafetyEventType(str, Enum):
    """安全事件类型枚举。"""
    ANTI_DEPENDENCY_TRIGGER = "ANTI_DEPENDENCY_TRIGGER"
    CONSENT_VIOLATION = "CONSENT_VIOLATION"
    DATA_EXPORT_BLOCKED = "DATA_EXPORT_BLOCKED"
    LATE_NIGHT_USAGE = "LATE_NIGHT_USAGE"
    EMOTIONAL_DISTRESS = "EMOTIONAL_DISTRESS"
    EXCESSIVE_USAGE = "EXCESSIVE_USAGE"
    CRISIS_EXPRESSION = "CRISIS_EXPRESSION"
    REALITY_SUBSTITUTION = "REALITY_SUBSTITUTION"
    COMMITMENT_REQUEST = "COMMITMENT_REQUEST"


class EvidenceType(str, Enum):
    """证据类型枚举。"""
    PRIMARY = "primary"
    SUPPORTING = "supporting"
    CONTRADICTORY = "contradictory"


class ChunkVisibility(str, Enum):
    """分块可见性枚举。"""
    SCOPE_PRIVATE = "scope_private"
    SCOPE_SHARED = "scope_shared"
    DECEASED_SHARED = "deceased_shared"


class DeletionType(str, Enum):
    """删除类型枚举。"""
    SCOPE_SOFT_DELETE = "scope_soft_delete"
    SCOPE_HARD_DELETE = "scope_hard_delete"
    SELECTIVE_DELETE = "selective_delete"


# ==================== 核心数据模型（Ch5） ====================

class MemoryChunkSchema(BaseModel):
    """记忆分块模型 — 对应 memory_chunk 表全部字段（Ch5）。"""
    id: str = Field(description="UUID v7 主键")
    source_artifact_id: str = Field(description="所属数据来源文件 ID")
    relationship_scope_id: str | None = Field(
        default=None, description="所属关系作用域（NULL 表示公共/待分配）"
    )
    chunk_hash: str = Field(description="SHA-256 内容哈希")
    chunk_type: ChunkType = Field(description="分块类型")
    content: str = Field(description="拼接后的文本内容")
    token_count: int = Field(default=0, description="Token 数量")
    time_range_start: str | None = Field(default=None, description="时间范围起始 ISO 8601")
    time_range_end: str | None = Field(default=None, description="时间范围结束 ISO 8601")
    message_count: int = Field(default=0, description="消息数量")
    speaker_count: int = Field(default=0, description="说话人数量")
    overlap_previous: int = Field(default=0, description="与前一个 chunk 的重叠消息数")
    overlap_next: int = Field(default=0, description="与下一个 chunk 的重叠消息数")
    status: str = Field(default="ACTIVE", description="ACTIVE / DEPRECATED / ARCHIVED")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = Field(default=None, description="创建时间 ISO 8601")
    updated_at: str | None = Field(default=None, description="更新时间 ISO 8601")
    deleted_at: str | None = Field(default=None, description="软删除时间戳")


class MemoryChunkSpanSchema(BaseModel):
    """分块溯源映射模型。"""
    id: str = Field(description="UUID v7 主键")
    chunk_id: str = Field(description="所属 chunk ID")
    normalized_message_id: str = Field(description="溯源的规范化消息 ID")
    char_start: int = Field(description="在 chunk.content 中的起始字符偏移")
    char_end: int = Field(description="在 chunk.content 中的结束字符偏移")
    source_speaker: str = Field(description="这段内容的说话人")
    source_timestamp: str | None = Field(default=None, description="时间戳")


class MemoryAnnotationSchema(BaseModel):
    """记忆标注模型。"""
    id: str = Field(description="UUID v7 主键")
    chunk_id: str = Field(description="所属 chunk ID")
    annotation_type: str = Field(description="SENTIMENT / TOPIC / COREFERENCE / KEY_EVENT / RISK")
    annotation_value: str = Field(description="标注值")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度 0.0~1.0")
    source: str = Field(default="llm", description="llm / user / rule")
    is_valid: bool = Field(default=True, description="是否有效")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = Field(default=None)
    updated_at: str | None = Field(default=None)


# ==================== 响应与 Claim 模型（Ch6） ====================

class ClaimSchema(BaseModel):
    """事实声明模型 — 对应 response_claim 表（Ch6）。"""
    id: str = Field(description="UUID v7 主键")
    relationship_scope_id: str = Field(description="所属关系作用域")
    interaction_session_id: str = Field(description="关联的交互会话 ID")
    interaction_message_id: str | None = Field(default=None, description="关联的用户消息 ID")
    claim_text: str = Field(description="事实声明文本")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度 0.0~1.0")
    dissent_note: str | None = Field(default=None, description="矛盾说明")
    evidence_sufficient: bool = Field(default=True, description="证据是否充分")
    model_used: str | None = Field(default=None, description="生成此 claim 的 LLM 模型")
    model_parameters: dict[str, Any] = Field(default_factory=dict, description="模型参数")
    status: str = Field(default="ACTIVE", description="ACTIVE / REVISED / DEPRECATED")
    created_at: str | None = Field(default=None)
    updated_at: str | None = Field(default=None)
    deleted_at: str | None = Field(default=None, description="软删除时间戳")


class EvidenceSchema(BaseModel):
    """声明证据关联模型 — 对应 claim_evidence 表（Ch6）。"""
    id: str = Field(description="UUID v7 主键")
    claim_id: str = Field(description="所属 claim ID")
    chunk_id: str = Field(description="溯源的 chunk ID")
    span_id: str | None = Field(default=None, description="可选：具体到 span 级别")
    evidence_type: EvidenceType = Field(description="primary / supporting / contradictory")
    relevance_score: float | None = Field(default=None, description="与 claim 的相关性评分")
    is_direct_quote: bool = Field(default=False, description="是否为直接引用")
    excerpt: str | None = Field(default=None, description="证据摘录文本")


class ResponseSchema(BaseModel):
    """响应模型 — 表示一次 RAG 查询的完整响应（Ch6）。"""
    claims: list[ClaimSchema] = Field(default_factory=list, description="事实声明列表")
    evidences: list[EvidenceSchema] = Field(default_factory=list, description="证据列表")
    retrieval_trace_id: str | None = Field(default=None, description="检索追踪 ID")
    model_used: str | None = Field(default=None, description="使用的 LLM 模型")
    duration_ms: int | None = Field(default=None, description="生成耗时毫秒")
    safety_flags: list[str] = Field(default_factory=list, description="安全标记")


# ==================== 安全模型（Ch10） ====================

class SafetyAction(str, Enum):
    """安全指令动作枚举 — 对应白皮书 Ch10 SafetyDirective。"""
    ALLOW = "ALLOW"
    SOFT_BREAK = "SOFT_BREAK"
    HARD_BREAK = "HARD_BREAK"
    COOLDOWN = "COOLDOWN"
    ESCALATE = "ESCALATE"


class SafetyDirective(BaseModel):
    """安全指令模型 — 严格对齐白皮书 Ch10 SafetyDirective JSON Schema。

    熔断是 policy 层接管，不是动态修改 system prompt。
    HARD_BREAK 时不进入普通 RAG，安全回复来自模板。
    """
    action: SafetyAction = Field(description="指令动作: ALLOW / SOFT_BREAK / HARD_BREAK / COOLDOWN / ESCALATE")
    reason: str = Field(default="", description="触发原因说明")
    cooldown_minutes: int = Field(default=0, description="冷却期分钟数（COOLDOWN 时有效）")
    template_id: str = Field(default="", description="安全回复模板 ID（用于 HARD_BREAK / COOLDOWN / ESCALATE）")
    allow_llm: bool = Field(default=True, description="是否允许 LLM 参与生成（HARD_BREAK 时为 False）")
    disconnect_after_response: bool = Field(default=False, description="是否在响应后断开连接（ESCALATE 时可能为 True）")
    safety_event_data: dict[str, Any] = Field(default_factory=dict, description="安全事件附加数据（用于记录到 safety_event 表）")


class SafetyIndicators(BaseModel):
    """8项安全指标 — 对应白皮书 Ch10.2。"""
    session_duration_minutes: float = Field(description="当前会话时长(分钟)")
    sessions_today_count: int = Field(description="今日该scope的会话数")
    late_night_count: int = Field(description="最近7天深夜会话数(22:00-06:00)")
    emotional_risk_score: float = Field(default=0.0, ge=0.0, le=1.0, description="情绪风险分0-1")
    dependency_phrases: int = Field(default=0, description="依赖性表达次数")
    farewell_refusal_count: int = Field(default=0, description="拒绝结束对话次数")
    user_age_flag: str = Field(default="adult", description="minor/senior/adult")
    recent_safety_events: int = Field(default=0, description="近7天安全事件数")


# ==================== API 请求/响应模型 ====================

class QueryRequest(BaseModel):
    """查询请求模型。"""
    scope_id: str = Field(description="关系作用域 ID")
    query: str = Field(description="用户查询文本")
    top_k: int = Field(default=10, ge=1, le=50, description="检索返回数量")
    include_evidence: bool = Field(default=True, description="是否包含证据溯源")
    stream: bool = Field(default=True, description="是否使用 SSE 流式响应")


class QueryResponse(BaseModel):
    """查询响应模型。"""
    session_id: str = Field(description="交互会话 ID")
    message_id: str = Field(description="交互消息 ID")
    content: str = Field(default="", description="响应内容")
    claims: list[ClaimSchema] = Field(default_factory=list, description="事实声明")
    evidences: list[EvidenceSchema] = Field(default_factory=list, description="证据溯源")
    retrieval_trace_id: str | None = Field(default=None, description="检索追踪 ID")
    safety_flags: list[str] = Field(default_factory=list, description="安全标记")
    duration_ms: int | None = Field(default=None, description="总耗时毫秒")


class ImportRequest(BaseModel):
    """数据导入请求模型。"""
    deceased_profile_id: str = Field(description="逝者档案 ID")
    file_path: str = Field(description="原始文件路径")
    file_type: str = Field(description="文件类型: universal_chat_json / wechat_txt / email_mbox / ...")
    scope_id: str | None = Field(default=None, description="关联的关系作用域 ID（可选）")
    encoding: str = Field(default="utf-8", description="文件编码")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class ImportResponse(BaseModel):
    """数据导入响应模型。"""
    artifact_id: str = Field(description="创建的 source_artifact ID")
    file_hash: str = Field(description="文件 SHA-256 哈希")
    message_count: int = Field(default=0, description="解析出的消息数量")
    chunk_count: int = Field(default=0, description="生成的分块数量")
    parse_status: str = Field(default="PENDING", description="PENDING / PARSING / PARSED / FAILED")
    errors: list[str] = Field(default_factory=list, description="导入过程中的错误信息")


class ScopeCreateRequest(BaseModel):
    """关系作用域创建请求模型。"""
    deceased_profile_id: str = Field(description="逝者档案 ID")
    scope_name: str = Field(description="作用域名称（如 '作为儿子'）")
    relationship_type: RelationshipType = Field(description="关系类型")
    scope_description: str | None = Field(default=None, description="作用域描述")


class ScopeDeleteRequest(BaseModel):
    """关系作用域删除请求模型。"""
    scope_id: str = Field(description="要删除的关系作用域 ID")
    deletion_type: DeletionType = Field(
        default=DeletionType.SCOPE_SOFT_DELETE,
        description="删除类型: scope_soft_delete / scope_hard_delete / selective_delete",
    )
    confirm: bool = Field(default=False, description="用户确认删除")
    target_chunk_ids: list[str] | None = Field(
        default=None,
        description="selective_delete 时指定的 chunk ID 列表",
    )


# ==================== 作用域配置模型（Ch9） ====================

class ScopePermissionSchema(BaseModel):
    """作用域权限配置模型。"""
    id: str = Field(description="UUID v7 主键")
    relationship_scope_id: str = Field(description="关联的作用域 ID")
    permission_key: str = Field(description="权限键名")
    permission_value: str = Field(description="权限值: allow / deny / ask")
    granted_at: str | None = Field(default=None, description="授权时间")
    granted_by: str | None = Field(default=None, description="user / system / inherited")
    expires_at: str | None = Field(default=None, description="过期时间")


class ScopePromptPolicySchema(BaseModel):
    """作用域 Prompt 策略配置模型。"""
    id: str = Field(description="UUID v7 主键")
    relationship_scope_id: str = Field(description="关联的作用域 ID")
    policy_key: str = Field(description="策略键名")
    policy_value: str = Field(description="JSON 值")


class ChunkScopeVisibilitySchema(BaseModel):
    """分块作用域可见性模型。"""
    id: str = Field(description="UUID v7 主键")
    chunk_id: str = Field(description="chunk ID")
    relationship_scope_id: str = Field(description="作用域 ID")
    visibility: ChunkVisibility = Field(default=ChunkVisibility.SCOPE_PRIVATE)
    elevated_at: str | None = Field(default=None, description="提升为共享的时间")
    elevated_by_scope: str | None = Field(default=None, description="由哪个 scope 提升")
    consent_id: str | None = Field(default=None, description="关联的授权记录 ID")


class ScopeSafetyPolicySchema(BaseModel):
    """作用域安全策略配置模型。"""
    id: str = Field(description="UUID v7 主键")
    relationship_scope_id: str = Field(description="关联的作用域 ID")
    max_session_minutes: int = Field(default=60, description="单次会话最大时长（分钟）")
    max_sessions_daily: int = Field(default=5, description="每日最大会话数")
    late_night_start: str = Field(default="22:00", description="深夜时段开始")
    late_night_end: str = Field(default="06:00", description="深夜时段结束")
    max_late_night_sessions: int = Field(default=2, description="深夜最大会话数")
    dependency_threshold: float = Field(default=0.7, description="情绪依赖阈值")
    farewell_refusal_limit: int = Field(default=3, description="拒绝结束次数上限")
    hard_break_enabled: bool = Field(default=True, description="是否允许硬熔断")
    cooldown_minutes: int = Field(default=30, description="冷却期分钟数")
    escalate_on_crisis: bool = Field(default=True, description="危机表达是否触发升级")


class ScopeDeletionLogSchema(BaseModel):
    """作用域删除记录模型。"""
    id: str = Field(description="UUID v7 主键")
    relationship_scope_id: str = Field(description="关联的作用域 ID")
    deletion_type: DeletionType = Field(description="删除类型")
    target_tables: list[str] = Field(description="被删除涉及的表名列表")
    affected_rows: int = Field(description="受影响行数")
    redacted: bool = Field(default=False, description="内容是否已脱敏")
    requested_at: str = Field(description="用户请求时间")
    completed_at: str | None = Field(default=None, description="完成时间")
    audit_log_ids: list[str] = Field(default_factory=list, description="关联的 audit_log IDs")
