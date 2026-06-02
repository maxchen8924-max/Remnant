"""DDL 定义 + init_db() — Remnant v0.1 全部 24 张表。

基于白皮书 Ch4/Ch9/Ch12 精确定义，所有字段名、类型、约束、外键
与白皮书完全一致。

表清单（按依赖顺序）:
1.  deceased_profile
2.  data_subject_consent
3.  relationship_scope
4.  source_artifact
5.  raw_message
6.  normalized_message
7.  memory_chunk
8.  memory_chunk_span
9.  memory_annotation
10. embedding_index_ref
11. retrieval_trace
12. response_claim
13. claim_evidence
14. interaction_session
15. interaction_message
16. safety_event
17. audit_log
18. scope_permission        (Ch9 新增)
19. scope_prompt_policy     (Ch9 新增)
20. chunk_scope_visibility  (Ch9 新增)
21. scope_safety_policy     (Ch9 新增)
22. scope_deletion_log      (Ch9 新增)
23. voice_profile           (Ch12 新增，v0.1 不启用但 DDL 就位)
24. voice_synthesis_log     (Ch12 新增)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from remnant_store.db import get_connection


# ==================== CREATE TABLE 语句（按依赖顺序） ====================

DDL_TABLES: list[str] = [
    # 1. deceased_profile — 逝者档案
    """CREATE TABLE IF NOT EXISTS deceased_profile (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    display_name    TEXT,
    birth_date      TEXT,
    death_date      TEXT,
    bio             TEXT,
    avatar_path     TEXT,
    metadata        TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at      TEXT
);""",

    # 2. data_subject_consent — 数据主体授权同意
    """CREATE TABLE IF NOT EXISTS data_subject_consent (
    id                  TEXT PRIMARY KEY,
    deceased_profile_id  TEXT NOT NULL,
    relationship_scope_id  TEXT NOT NULL,
    data_category       TEXT NOT NULL,
    consent_type        TEXT NOT NULL,
    consent_scope       TEXT NOT NULL,
    granted_at          TEXT,
    withdrawn_at        TEXT,
    expires_at          TEXT,
    consent_evidence    TEXT,
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);""",

    # 3. relationship_scope — 关系作用域
    """CREATE TABLE IF NOT EXISTS relationship_scope (
    id                  TEXT PRIMARY KEY,
    deceased_profile_id  TEXT NOT NULL,
    scope_name          TEXT NOT NULL,
    relationship_type    TEXT NOT NULL,
    scope_description    TEXT,
    encryption_key_hash  TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,

    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id)
);""",

    # 4. source_artifact — 数据来源文件
    """CREATE TABLE IF NOT EXISTS source_artifact (
    id                  TEXT PRIMARY KEY,
    deceased_profile_id  TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    file_hash           TEXT NOT NULL,
    file_size           INTEGER NOT NULL,
    file_type           TEXT NOT NULL,
    mime_type           TEXT,
    encoding            TEXT,
    parse_status        TEXT NOT NULL DEFAULT 'PENDING',
    parse_error         TEXT,
    date_range_start    TEXT,
    date_range_end      TEXT,
    message_count       INTEGER DEFAULT 0,
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,

    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id),
    UNIQUE(file_hash)
);""",

    # 5. raw_message — 原始消息（不可变）
    """CREATE TABLE IF NOT EXISTS raw_message (
    id                  TEXT PRIMARY KEY,
    source_artifact_id  TEXT NOT NULL,
    timestamp           TEXT,
    speaker             TEXT NOT NULL,
    content             TEXT NOT NULL,
    content_type        TEXT NOT NULL DEFAULT 'text',
    parse_status        TEXT NOT NULL DEFAULT 'OK',
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (source_artifact_id) REFERENCES source_artifact(id)
);""",

    # 6. normalized_message — 规范化消息
    """CREATE TABLE IF NOT EXISTS normalized_message (
    id                  TEXT PRIMARY KEY,
    raw_message_id      TEXT NOT NULL,
    source_artifact_id  TEXT NOT NULL,
    timestamp           TEXT,
    timestamp_confidence TEXT DEFAULT 'CERTAIN',
    speaker_original    TEXT NOT NULL,
    speaker_normalized  TEXT NOT NULL,
    person_id           TEXT,
    content             TEXT NOT NULL,
    content_type        TEXT NOT NULL DEFAULT 'text',
    status              TEXT NOT NULL DEFAULT 'NORMALIZED',
    filter_tags         TEXT DEFAULT '[]',
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (raw_message_id) REFERENCES raw_message(id),
    FOREIGN KEY (source_artifact_id) REFERENCES source_artifact(id)
);""",

    # 7. memory_chunk — 记忆分块
    """CREATE TABLE IF NOT EXISTS memory_chunk (
    id                  TEXT PRIMARY KEY,
    source_artifact_id  TEXT NOT NULL,
    relationship_scope_id TEXT,
    chunk_hash          TEXT NOT NULL,
    chunk_type          TEXT NOT NULL,
    content             TEXT NOT NULL,
    token_count         INTEGER NOT NULL DEFAULT 0,
    time_range_start    TEXT,
    time_range_end      TEXT,
    message_count       INTEGER NOT NULL DEFAULT 0,
    speaker_count       INTEGER NOT NULL DEFAULT 0,
    overlap_previous    INTEGER DEFAULT 0,
    overlap_next        INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'ACTIVE',
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,

    FOREIGN KEY (source_artifact_id) REFERENCES source_artifact(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);""",

    # 8. memory_chunk_span — 分块溯源映射
    """CREATE TABLE IF NOT EXISTS memory_chunk_span (
    id                      TEXT PRIMARY KEY,
    chunk_id                TEXT NOT NULL,
    normalized_message_id   TEXT NOT NULL,
    char_start              INTEGER NOT NULL,
    char_end                INTEGER NOT NULL,
    source_speaker          TEXT NOT NULL,
    source_timestamp        TEXT,

    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id),
    FOREIGN KEY (normalized_message_id) REFERENCES normalized_message(id)
);""",

    # 9. memory_annotation — 记忆标注
    """CREATE TABLE IF NOT EXISTS memory_annotation (
    id                  TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL,
    annotation_type     TEXT NOT NULL,
    annotation_value    TEXT NOT NULL,
    confidence          REAL DEFAULT 1.0,
    source              TEXT NOT NULL DEFAULT 'llm',
    is_valid            INTEGER NOT NULL DEFAULT 1,
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id)
);""",

    # 10. embedding_index_ref — 向量索引引用
    """CREATE TABLE IF NOT EXISTS embedding_index_ref (
    id                  TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    model_version       TEXT,
    vector_dimension    INTEGER NOT NULL,
    index_backend       TEXT NOT NULL DEFAULT 'sqlite_vec',
    index_status        TEXT NOT NULL DEFAULT 'PENDING',
    metadata            TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id)
);""",

    # 11. retrieval_trace — 检索追踪
    """CREATE TABLE IF NOT EXISTS retrieval_trace (
    id                      TEXT PRIMARY KEY,
    relationship_scope_id   TEXT NOT NULL,
    interaction_session_id  TEXT,
    query_text              TEXT NOT NULL,
    query_embedding_model   TEXT,
    fts_results             TEXT DEFAULT '[]',
    vector_results          TEXT DEFAULT '[]',
    reranked_results        TEXT DEFAULT '[]',
    evidence_validated      TEXT DEFAULT '[]',
    evidence_rejected       TEXT DEFAULT '[]',
    total_duration_ms       INTEGER,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (interaction_session_id) REFERENCES interaction_session(id)
);""",

    # 12. response_claim — 响应声明
    """CREATE TABLE IF NOT EXISTS response_claim (
    id                      TEXT PRIMARY KEY,
    relationship_scope_id   TEXT NOT NULL,
    interaction_session_id  TEXT NOT NULL,
    interaction_message_id  TEXT,
    claim_text              TEXT NOT NULL,
    confidence              REAL NOT NULL DEFAULT 0.5,
    dissent_note            TEXT,
    evidence_sufficient     INTEGER NOT NULL DEFAULT 1,
    model_used              TEXT,
    model_parameters        TEXT DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at              TEXT,

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (interaction_session_id) REFERENCES interaction_session(id)
);""",

    # 13. claim_evidence — 声明证据关联
    """CREATE TABLE IF NOT EXISTS claim_evidence (
    id                  TEXT PRIMARY KEY,
    claim_id            TEXT NOT NULL,
    chunk_id            TEXT NOT NULL,
    span_id             TEXT,
    evidence_type       TEXT NOT NULL,
    relevance_score     REAL,
    is_direct_quote     INTEGER NOT NULL DEFAULT 0,
    excerpt             TEXT,

    FOREIGN KEY (claim_id) REFERENCES response_claim(id),
    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id),
    FOREIGN KEY (span_id) REFERENCES memory_chunk_span(id)
);""",

    # 14. interaction_session — 交互会话
    """CREATE TABLE IF NOT EXISTS interaction_session (
    id                      TEXT PRIMARY KEY,
    relationship_scope_id   TEXT NOT NULL,
    deceased_profile_id     TEXT NOT NULL,
    session_type             TEXT NOT NULL DEFAULT 'conversation',
    started_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at                 TEXT,
    total_messages           INTEGER DEFAULT 0,
    total_duration_seconds   INTEGER,
    llm_model_used           TEXT,
    llm_model_version        TEXT,
    metadata                 TEXT DEFAULT '{}',
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id)
);""",

    # 15. interaction_message — 交互消息
    """CREATE TABLE IF NOT EXISTS interaction_message (
    id                      TEXT PRIMARY KEY,
    session_id              TEXT NOT NULL,
    relationship_scope_id   TEXT NOT NULL,
    role                    TEXT NOT NULL,
    content                 TEXT NOT NULL,
    claim_ids               TEXT DEFAULT '[]',
    retrieval_trace_id      TEXT,
    model_used              TEXT,
    token_usage             TEXT DEFAULT '{}',
    duration_ms             INTEGER,
    safety_flags            TEXT DEFAULT '[]',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (session_id) REFERENCES interaction_session(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (retrieval_trace_id) REFERENCES retrieval_trace(id)
);""",

    # 16. safety_event — 安全事件
    """CREATE TABLE IF NOT EXISTS safety_event (
    id                      TEXT PRIMARY KEY,
    relationship_scope_id   TEXT,
    event_type              TEXT NOT NULL,
    severity                TEXT NOT NULL DEFAULT 'warning',
    description             TEXT NOT NULL,
    trigger_data            TEXT DEFAULT '{}',
    action_taken            TEXT NOT NULL,
    resolved_at             TEXT,
    metadata                TEXT DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);""",

    # 17. audit_log — 审计日志（APPEND ONLY）
    """CREATE TABLE IF NOT EXISTS audit_log (
    id                      TEXT PRIMARY KEY,
    relationship_scope_id   TEXT,
    action                  TEXT NOT NULL,
    actor                   TEXT NOT NULL,
    target_type             TEXT NOT NULL,
    target_id               TEXT NOT NULL,
    detail                  TEXT DEFAULT '{}',
    ip_address              TEXT,
    user_agent              TEXT,
    redacted                INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);""",

    # 18. scope_permission — 作用域权限配置（Ch9 新增）
    """CREATE TABLE IF NOT EXISTS scope_permission (
    id                  TEXT PRIMARY KEY,
    relationship_scope_id TEXT NOT NULL,
    permission_key      TEXT NOT NULL,
    permission_value    TEXT NOT NULL,
    granted_at          TEXT,
    granted_by          TEXT,
    expires_at          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    UNIQUE(relationship_scope_id, permission_key)
);""",

    # 19. scope_prompt_policy — 作用域 Prompt 策略配置（Ch9 新增）
    """CREATE TABLE IF NOT EXISTS scope_prompt_policy (
    id                  TEXT PRIMARY KEY,
    relationship_scope_id TEXT NOT NULL,
    policy_key          TEXT NOT NULL,
    policy_value        TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    UNIQUE(relationship_scope_id, policy_key)
);""",

    # 20. chunk_scope_visibility — 分块作用域可见性（Ch9 新增）
    """CREATE TABLE IF NOT EXISTS chunk_scope_visibility (
    id                  TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL,
    relationship_scope_id TEXT NOT NULL,
    visibility          TEXT NOT NULL DEFAULT 'scope_private',
    elevated_at         TEXT,
    elevated_by_scope   TEXT,
    consent_id          TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (chunk_id) REFERENCES memory_chunk(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    FOREIGN KEY (elevated_by_scope) REFERENCES relationship_scope(id),
    FOREIGN KEY (consent_id) REFERENCES data_subject_consent(id),
    UNIQUE(chunk_id, relationship_scope_id)
);""",

    # 21. scope_safety_policy — 作用域安全策略配置（Ch9 新增）
    """CREATE TABLE IF NOT EXISTS scope_safety_policy (
    id                  TEXT PRIMARY KEY,
    relationship_scope_id TEXT NOT NULL,
    max_session_minutes INTEGER NOT NULL DEFAULT 60,
    max_sessions_daily  INTEGER NOT NULL DEFAULT 5,
    late_night_start    TEXT DEFAULT '22:00',
    late_night_end      TEXT DEFAULT '06:00',
    max_late_night_sessions INTEGER NOT NULL DEFAULT 2,
    dependency_threshold REAL NOT NULL DEFAULT 0.7,
    farewell_refusal_limit INTEGER NOT NULL DEFAULT 3,
    hard_break_enabled  INTEGER NOT NULL DEFAULT 1,
    cooldown_minutes    INTEGER NOT NULL DEFAULT 30,
    escalate_on_crisis  INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id),
    UNIQUE(relationship_scope_id)
);""",

    # 22. scope_deletion_log — 作用域删除记录（Ch9 新增）
    """CREATE TABLE IF NOT EXISTS scope_deletion_log (
    id                  TEXT PRIMARY KEY,
    relationship_scope_id TEXT NOT NULL,
    deletion_type       TEXT NOT NULL,
    target_tables       TEXT NOT NULL,
    affected_rows       INTEGER NOT NULL,
    redacted            INTEGER NOT NULL DEFAULT 0,
    requested_at        TEXT NOT NULL,
    completed_at        TEXT,
    audit_log_ids       TEXT DEFAULT '[]',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);""",

    # 23. voice_profile — 声音档案（Ch12 新增，v0.1 不启用）
    """CREATE TABLE IF NOT EXISTS voice_profile (
    id                      TEXT PRIMARY KEY,
    deceased_profile_id     TEXT NOT NULL,
    relationship_scope_id   TEXT NOT NULL,
    state                   TEXT NOT NULL DEFAULT 'DISABLED',
    sample_source_artifact_ids TEXT DEFAULT '[]',
    sample_count            INTEGER DEFAULT 0,
    sample_total_duration   REAL DEFAULT 0.0,
    model_backend           TEXT,
    model_path              TEXT,
    model_hash              TEXT,
    encryption_key_id       TEXT,
    consent_evidence        TEXT,
    consent_granted_at      TEXT,
    consent_withdrawn_at    TEXT,
    training_log_ids        TEXT DEFAULT '[]',
    destroyed_at            TEXT,
    metadata                TEXT DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (deceased_profile_id) REFERENCES deceased_profile(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);""",

    # 24. voice_synthesis_log — 声音合成日志（Ch12 新增）
    """CREATE TABLE IF NOT EXISTS voice_synthesis_log (
    id                      TEXT PRIMARY KEY,
    voice_profile_id        TEXT NOT NULL,
    relationship_scope_id   TEXT NOT NULL,
    session_id              TEXT,
    input_text              TEXT NOT NULL,
    input_text_hash         TEXT NOT NULL,
    output_duration_seconds REAL,
    output_file_path        TEXT,
    contains_ai_marker      INTEGER NOT NULL DEFAULT 1,
    watermark_verified      INTEGER NOT NULL DEFAULT 0,
    model_backend_version   TEXT,
    inference_duration_ms   INTEGER,
    safety_check_passed     INTEGER NOT NULL DEFAULT 0,
    safety_check_details    TEXT DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (voice_profile_id) REFERENCES voice_profile(id),
    FOREIGN KEY (relationship_scope_id) REFERENCES relationship_scope(id)
);""",
]

# ==================== CREATE INDEX 语句 ====================

DDL_INDEXES: list[str] = [
    # deceased_profile
    "CREATE INDEX IF NOT EXISTS idx_deceased_profile_name ON deceased_profile(name);",
    # data_subject_consent
    "CREATE INDEX IF NOT EXISTS idx_consent_scope ON data_subject_consent(relationship_scope_id, data_category);",
    "CREATE INDEX IF NOT EXISTS idx_consent_deceased ON data_subject_consent(deceased_profile_id);",
    # relationship_scope
    "CREATE INDEX IF NOT EXISTS idx_scope_deceased ON relationship_scope(deceased_profile_id);",
    # source_artifact
    "CREATE INDEX IF NOT EXISTS idx_artifact_deceased ON source_artifact(deceased_profile_id);",
    "CREATE INDEX IF NOT EXISTS idx_artifact_status ON source_artifact(parse_status);",
    # raw_message
    "CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_message(source_artifact_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_timestamp ON raw_message(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_raw_speaker ON raw_message(speaker);",
    # normalized_message
    "CREATE INDEX IF NOT EXISTS idx_norm_source ON normalized_message(source_artifact_id);",
    "CREATE INDEX IF NOT EXISTS idx_norm_timestamp ON normalized_message(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_norm_speaker ON normalized_message(speaker_normalized);",
    "CREATE INDEX IF NOT EXISTS idx_norm_status ON normalized_message(status);",
    "CREATE INDEX IF NOT EXISTS idx_norm_raw ON normalized_message(raw_message_id);",
    # memory_chunk
    "CREATE INDEX IF NOT EXISTS idx_chunk_source ON memory_chunk(source_artifact_id);",
    "CREATE INDEX IF NOT EXISTS idx_chunk_scope ON memory_chunk(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_chunk_hash ON memory_chunk(chunk_hash);",
    "CREATE INDEX IF NOT EXISTS idx_chunk_time ON memory_chunk(time_range_start, time_range_end);",
    "CREATE INDEX IF NOT EXISTS idx_chunk_status ON memory_chunk(status);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chunk_unique ON memory_chunk(source_artifact_id, chunk_hash);",
    # memory_chunk_span
    "CREATE INDEX IF NOT EXISTS idx_span_chunk ON memory_chunk_span(chunk_id);",
    "CREATE INDEX IF NOT EXISTS idx_span_message ON memory_chunk_span(normalized_message_id);",
    # memory_annotation
    "CREATE INDEX IF NOT EXISTS idx_annotation_chunk ON memory_annotation(chunk_id);",
    "CREATE INDEX IF NOT EXISTS idx_annotation_type ON memory_annotation(annotation_type);",
    "CREATE INDEX IF NOT EXISTS idx_annotation_valid ON memory_annotation(is_valid);",
    # embedding_index_ref
    "CREATE INDEX IF NOT EXISTS idx_embedding_chunk ON embedding_index_ref(chunk_id);",
    "CREATE INDEX IF NOT EXISTS idx_embedding_model ON embedding_index_ref(model_name);",
    "CREATE INDEX IF NOT EXISTS idx_embedding_status ON embedding_index_ref(index_status);",
    # retrieval_trace
    "CREATE INDEX IF NOT EXISTS idx_trace_scope ON retrieval_trace(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_trace_session ON retrieval_trace(interaction_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_trace_time ON retrieval_trace(created_at);",
    # response_claim
    "CREATE INDEX IF NOT EXISTS idx_claim_scope ON response_claim(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_claim_session ON response_claim(interaction_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_claim_confidence ON response_claim(confidence);",
    # claim_evidence
    "CREATE INDEX IF NOT EXISTS idx_evidence_claim ON claim_evidence(claim_id);",
    "CREATE INDEX IF NOT EXISTS idx_evidence_chunk ON claim_evidence(chunk_id);",
    "CREATE INDEX IF NOT EXISTS idx_evidence_type ON claim_evidence(evidence_type);",
    # interaction_session
    "CREATE INDEX IF NOT EXISTS idx_session_scope ON interaction_session(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_session_deceased ON interaction_session(deceased_profile_id);",
    "CREATE INDEX IF NOT EXISTS idx_session_time ON interaction_session(started_at);",
    # interaction_message
    "CREATE INDEX IF NOT EXISTS idx_msg_session ON interaction_message(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_msg_scope ON interaction_message(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_msg_time ON interaction_message(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_msg_role ON interaction_message(role);",
    # safety_event
    "CREATE INDEX IF NOT EXISTS idx_safety_scope ON safety_event(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_safety_type ON safety_event(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_safety_severity ON safety_event(severity);",
    "CREATE INDEX IF NOT EXISTS idx_safety_time ON safety_event(created_at);",
    # audit_log
    "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);",
    "CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_type, target_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_scope ON audit_log(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at);",
    # scope_permission
    "CREATE INDEX IF NOT EXISTS idx_perm_scope ON scope_permission(relationship_scope_id);",
    # chunk_scope_visibility
    "CREATE INDEX IF NOT EXISTS idx_chunk_vis_chunk ON chunk_scope_visibility(chunk_id);",
    "CREATE INDEX IF NOT EXISTS idx_chunk_vis_scope ON chunk_scope_visibility(relationship_scope_id);",
    # scope_deletion_log
    "CREATE INDEX IF NOT EXISTS idx_deletion_scope ON scope_deletion_log(relationship_scope_id);",
    # voice_profile
    "CREATE INDEX IF NOT EXISTS idx_voice_profile_deceased ON voice_profile(deceased_profile_id);",
    "CREATE INDEX IF NOT EXISTS idx_voice_profile_scope ON voice_profile(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_voice_profile_state ON voice_profile(state);",
    # voice_synthesis_log
    "CREATE INDEX IF NOT EXISTS idx_voice_log_profile ON voice_synthesis_log(voice_profile_id);",
    "CREATE INDEX IF NOT EXISTS idx_voice_log_scope ON voice_synthesis_log(relationship_scope_id);",
    "CREATE INDEX IF NOT EXISTS idx_voice_log_time ON voice_synthesis_log(created_at);",
]

# ==================== 触发器 ====================

DDL_TRIGGERS: list[str] = [
    # raw_message 不可变：禁止 UPDATE
    """CREATE TRIGGER IF NOT EXISTS trg_prevent_raw_message_update
BEFORE UPDATE ON raw_message
BEGIN
    SELECT RAISE(ABORT, 'raw_message is immutable: UPDATE not allowed');
END;""",

    # raw_message 不可变：禁止 DELETE
    """CREATE TRIGGER IF NOT EXISTS trg_prevent_raw_message_delete
BEFORE DELETE ON raw_message
BEGIN
    SELECT RAISE(ABORT, 'raw_message is immutable: DELETE not allowed');
END;""",

    # audit_log 不可变：禁止 UPDATE
    """CREATE TRIGGER IF NOT EXISTS trg_prevent_audit_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE not allowed');
END;""",

    # audit_log 不可变：禁止 DELETE
    """CREATE TRIGGER IF NOT EXISTS trg_prevent_audit_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE not allowed');
END;""",

    # FTS5 同步：INSERT
    """CREATE TRIGGER IF NOT EXISTS trg_chunk_fts_insert AFTER INSERT ON memory_chunk
BEGIN
    INSERT INTO memory_chunk_fts(rowid, content) VALUES (
        (SELECT rowid FROM memory_chunk WHERE id = NEW.id), NEW.content
    );
END;""",

    # FTS5 同步：UPDATE（先删旧，再插新）
    """CREATE TRIGGER IF NOT EXISTS trg_chunk_fts_update AFTER UPDATE ON memory_chunk
BEGIN
    INSERT INTO memory_chunk_fts(memory_chunk_fts, rowid, content) VALUES (
        'delete', (SELECT rowid FROM memory_chunk WHERE id = NEW.id), OLD.content
    );
    INSERT INTO memory_chunk_fts(rowid, content) VALUES (
        (SELECT rowid FROM memory_chunk WHERE id = NEW.id), NEW.content
    );
END;""",

    # FTS5 同步：DELETE
    """CREATE TRIGGER IF NOT EXISTS trg_chunk_fts_delete AFTER DELETE ON memory_chunk
BEGIN
    INSERT INTO memory_chunk_fts(memory_chunk_fts, rowid, content) VALUES (
        'delete', (SELECT rowid FROM memory_chunk WHERE id = OLD.id), OLD.content
    );
END;""",

    # 软删除级联：scope 被软删除时级联更新关联数据
    """CREATE TRIGGER IF NOT EXISTS trg_scope_soft_delete_chunks
AFTER UPDATE OF deleted_at ON relationship_scope
WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL
BEGIN
    UPDATE memory_chunk
    SET deleted_at = NEW.deleted_at
    WHERE relationship_scope_id = NEW.id AND deleted_at IS NULL;

    UPDATE interaction_session
    SET ended_at = CASE WHEN ended_at IS NULL THEN NEW.deleted_at ELSE ended_at END
    WHERE relationship_scope_id = NEW.id;

    INSERT INTO audit_log (id, action, actor, target_type, target_id, detail)
    VALUES (
        lower(hex(randomblob(4)) || hex(randomblob(2)) || hex(randomblob(2)) || hex(randomblob(2)) || hex(randomblob(6))),
        'DATA_DESTROY',
        'system',
        'relationship_scope',
        NEW.id,
        json('{"reason": "scope_soft_delete", "scope_name": "' || NEW.scope_name || '"}')
    );
END;""",
]

# ==================== FTS5 虚拟表 ====================

# 白皮书指定 tokenize='simple'（自定义分词器，需编译 C 扩展）
# 当前 Python 内置 SQLite 不含 simple tokenizer，回退为 unicode61
# 中文内容由 jieba 预分词后空格分隔入库，unicode61 可正确处理空格分隔的中文词

_FTS5_TOKENIZER = "simple"  # 白皮书标准
_FTS5_TOKENIZER_FALLBACK = "unicode61"  # 内置回退

DDL_VIRTUAL_TABLE_TEMPLATES: list[str] = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunk_fts USING fts5(
    content,
    content='memory_chunk',
    content_rowid='rowid',
    tokenize='{tokenizer}'
);""",
]


def init_db(
    db_path: str | Path = ":memory:",
    sqlcipher_key: str | None = None,
) -> sqlite3.Connection:
    """初始化数据库 — 创建全部表、索引、触发器、虚拟表。

    Args:
        db_path: 数据库文件路径，默认 ':memory:' 内存数据库
        sqlcipher_key: SQLCipher 加密密钥（None 则使用普通 SQLite）

    Returns:
        配置好的 sqlite3.Connection
    """
    conn = get_connection(db_path, sqlcipher_key=sqlcipher_key)

    # 依次执行 CREATE TABLE（按依赖顺序）
    for ddl in DDL_TABLES:
        conn.execute(ddl)

    # 执行 CREATE INDEX
    for ddl in DDL_INDEXES:
        conn.execute(ddl)

    # 执行 CREATE TRIGGER
    for ddl in DDL_TRIGGERS:
        conn.execute(ddl)

    # 执行 CREATE VIRTUAL TABLE（FTS5）
    # 尝试白皮书指定的 simple tokenizer，不可用时回退到 unicode61
    for template in DDL_VIRTUAL_TABLE_TEMPLATES:
        ddl = template.format(tokenizer=_FTS5_TOKENIZER)
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as e:
            if "no such tokenizer" in str(e).lower():
                import warnings
                warnings.warn(
                    f"FTS5 tokenizer '{_FTS5_TOKENIZER}' 不可用，"
                    f"回退到 '{_FTS5_TOKENIZER_FALLBACK}'。"
                    f"中文检索需依赖 jieba 预分词。",
                    stacklevel=2,
                )
                ddl = template.format(tokenizer=_FTS5_TOKENIZER_FALLBACK)
                conn.execute(ddl)
            else:
                raise

    conn.commit()
    return conn


def get_table_names(conn: sqlite3.Connection) -> list[str]:
    """获取数据库中所有用户表名。

    Args:
        conn: 数据库连接

    Returns:
        表名列表
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def get_index_names(conn: sqlite3.Connection) -> list[str]:
    """获取数据库中所有索引名。

    Args:
        conn: 数据库连接

    Returns:
        索引名列表
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def get_trigger_names(conn: sqlite3.Connection) -> list[str]:
    """获取数据库中所有触发器名。

    Args:
        conn: 数据库连接

    Returns:
        触发器名列表
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]