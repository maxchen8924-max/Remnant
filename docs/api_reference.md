# Remnant v0.1 API 参考文档

> 覆盖 Chapter 15 全部接口的 OpenAPI 文档格式。

---

## 概述

- **Base URL**: `http://127.0.0.1:18731`
- **认证**: 所有请求必须携带本地 sidecar token。Rust bridge 默认使用
  `Authorization: Bearer <token>`；`X-Remnant-Token: <token>` 作为白皮书兼容
  header 仍被接受。
- **响应格式**: `{code, data, message}`
- **时间戳**: ISO 8601 UTC
- **流式接口**: SSE (`text/event-stream`)

---

## 通用响应格式

```json
{
  "code": 0,
  "data": {},
  "message": "ok"
}
```

### 错误码定义

| 错误码 | 含义 | HTTP Status |
|--------|------|-------------|
| 0 | 成功 | 200 |
| 1001 | 参数校验失败 | 400 |
| 1002 | Token 无效或缺失 | 401 |
| 1003 | Scope 不存在 | 404 |
| 1004 | Scope 权限不足 | 403 |
| 1005 | 数据不存在 | 404 |
| 1006 | 数据已存在（重复导入） | 409 |
| 1007 | 数据不可变（raw_message 不可修改） | 405 |
| 2001 | Safety 熔断触发 | 451 |
| 2002 | 会话超时 | 408 |
| 2003 | 依赖性检测：建议休息 | 202 |
| 3001 | ETL 管道错误 | 500 |
| 3002 | LLM 推理错误 | 502 |
| 3003 | 向量索引未就绪 | 503 |
| 4001 | Consent 未授权 | 403 |
| 4002 | 数据销毁请求已提交 | 202 |

---

## 1. POST /api/v1/import

启动数据导入任务。

### 安全考量

- 需要指定 `deceased_profile_id` 和 `relationship_scope_id`
- 导入操作写入 `audit_log`（action=DATA_IMPORT）
- 文件路径经过路径遍历检查（不允许 `..` 或绝对路径逃逸）
- 文件大小限制：单文件 ≤ 500MB

### Request

```http
POST /api/v1/import
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "source_type": "wechat_txt",
  "file_path": "/path/to/wechat_export.txt",
  "encoding": "auto",
  "import_options": {
    "skip_system_message": true,
    "skip_recall_message": true,
    "speaker_aliases": {
      "妈": "mother",
      "妈咪": "mother"
    },
    "consent_categories": ["raw_text"],
    "consent_evidence": "用户手动授权"
  }
}
```

### Request Schema

| 字段 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `deceased_profile_id` | string (UUID) | 是 | 逝者档案 ID |
| `scope_id` | string (UUID) | 是 | 关系作用域 ID |
| `source_type` | enum | 是 | 数据来源类型: `wechat_txt`, `diary`, `email` |
| `file_path` | string | 是 | 导入文件的绝对路径 |
| `encoding` | string | 否 | 文件编码，默认 `auto` 自动检测 |
| `import_options.skip_system_message` | boolean | 否 | 跳过系统消息，默认 true |
| `import_options.skip_recall_message` | boolean | 否 | 跳过撤回消息，默认 true |
| `import_options.speaker_aliases` | object | 否 | 说话人别名映射 |
| `import_options.consent_categories` | array | 否 | 数据授权类别 |
| `import_options.consent_evidence` | string | 否 | 授权声明文本 |

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "job_id": "019a1b2c-job1-job1-job1-job1job1job1",
    "status": "PENDING",
    "source_artifact_id": "019a1b2c-art1-art1-art1-art1art1art1",
    "file_hash": "sha256:a1b2c3d4e5f6...",
    "estimated_duration_seconds": 30
  },
  "message": "ok"
}
```

### Response Schema

| 字段 | 类型 | 描述 |
|------|------|------|
| `data.job_id` | string (UUID) | 导入任务 ID |
| `data.status` | enum | 任务状态: `PENDING` → `PARSING` → `NORMALIZING` → `CHUNKING` → `ANNOTATING` → `INDEXING` → `COMPLETED` / `FAILED` |
| `data.source_artifact_id` | string (UUID) | 数据制品 ID |
| `data.file_hash` | string | 文件 SHA-256 哈希 |
| `data.estimated_duration_seconds` | integer | 预估耗时（秒） |

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数缺失或无效 |
| 1002 | Token 无效 |
| 1006 | 文件 hash 重复（已导入） |
| 3001 | ETL 管道处理错误 |

---

## 2. GET /api/v1/import/{job_id}

查询导入任务状态。

### Request

```http
GET /api/v1/import/{job_id}?scope_id={scope_id}
X-Remnant-Token: <token>
```

### Request Schema

| 字段 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `job_id` | string (UUID) | 是 | 导入任务 ID（路径参数） |
| `scope_id` | string (UUID) | 是 | 作用域 ID（查询参数） |

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "job_id": "019a1b2c-job1-job1-job1-job1job1job1",
    "status": "PARSING",
    "progress": {
      "total_messages": 0,
      "parsed_messages": 0,
      "normalized_messages": 0,
      "chunked_messages": 0,
      "current_step": "normalization"
    },
    "source_artifact_id": "019a1b2c-art1-art1-art1-art1art1art1",
    "error": null
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1003 | job_id 不存在 |
| 1004 | scope 不匹配 |

---

## 3. POST /api/v1/query

执行记忆查询，返回 Claim-level 响应（SSE 流式）。

### 安全考量

- **必须指定 scope_id**，所有检索限定在该 scope 内
- 请求前先执行 Safety pre-check（Step 1）
- 如果 SafetyDirective.action ∈ {HARD_BREAK, ESCALATE}，不进入 LLM 推理，直接返回模板响应
- 查询操作记录审计日志（action=DATA_QUERY）
- 所有检索结果写入 `retrieval_trace`

### Request

```http
POST /api/v1/query
Content-Type: application/json
X-Remnant-Token: <token>
Accept: text/event-stream
```

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "session_id": "019a1b2c-sss1-sss1-sss1-sss1sss1sss1",
  "query": "妈妈说过想去西湖吗？",
  "context": {
    "conversation_history_ids": ["019a1b2c-msg1-msg1..."],
    "memory_set_level": 2
  },
  "options": {
    "top_k": 10,
    "rerank": true,
    "embedding_model": "bge-small-zh"
  }
}
```

### Request Schema

| 字段 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `scope_id` | string (UUID) | 是 | 关系作用域 ID |
| `deceased_profile_id` | string (UUID) | 否 | 逝者档案 ID |
| `session_id` | string (UUID) | 否 | 会话 ID（不指定则自动创建） |
| `query` | string | 是 | 查询文本 |
| `context.conversation_history_ids` | array | 否 | 当前会话历史消息 ID 列表 |
| `context.memory_set_level` | integer | 否 | 记忆集级别 |
| `options.top_k` | integer | 否 | 检索 top-K 结果数，默认 10 |
| `options.rerank` | boolean | 否 | 是否启用 rerank，默认 true |
| `options.embedding_model` | string | 否 | embedding 模型名称 |

### Response (SSE 流式)

```
event: safety_check
data: {"level": "caution", "action": "ALLOW", "buffer_text": "根据目前可用的记录——"}

event: retrieval_done
data: {"trace_id": "019a1b2c-tr1-tr1-tr1-tr1tr1tr1tr1", "chunk_count": 8, "evidence_count": 6}

event: token
data: {"text": "根据"}

event: token
data: {"text": "微信"}

...

event: claims
data: {"claims": [
  {
    "claim_id": "c_001",
    "claim_text": "妈妈在2024年3月15日提到想去西湖看看",
    "claim_type": "supported_memory",
    "support_status": "fully_supported",
    "confidence_score": 0.92,
    "evidence": [...]
  }
]}

event: audit
data: {"scope_id": "019a1b2c-1111-...", "session_id": "019a1b2c-sss1-...", "duration_ms": 1500}

event: done
data: ""
```

### SSE 事件类型

| 事件类型 | 触发时机 | 数据内容 |
|---------|---------|---------|
| `safety_check` | 安全评估完成后 | SafetyDirective level 和 action |
| `retrieval_done` | 检索阶段完成后 | trace_id, chunk_count, evidence_count |
| `token` | LLM 流式输出每个 token | `{"text": "..."}` |
| `claims` | Claim extraction 完成后 | claims 数组（含 evidence） |
| `unsupported` | Unsupported claim 移除后 | 被移除的 claims 列表 |
| `safety_directive` | 安全熔断触发时 | action, template_text |
| `audit` | 审计日志写入后 | scope_id, session_id, duration_ms |
| `done` | 流式响应结束 | 空 |

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1003 | scope 不存在 |
| 2001 | Safety 熔断触发 |
| 2003 | 建议休息 |

---

## 4. POST /api/v1/retrieve

混合检索接口（仅检索，不经过 LLM）。

### Request

```http
POST /api/v1/retrieve
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "query": "西湖 风车",
  "top_k": 10,
  "rerank": true,
  "embedding_model": "bge-small-zh"
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "chunk_id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
        "content": "春天的时候去西湖应该很漂亮",
        "chunk_type": "conversation_segment",
        "relevance_score": 0.95,
        "source": "hybrid",
        "time_range_start": "2024-03-15T10:30:00Z",
        "time_range_end": "2024-03-15T10:32:00Z"
      }
    ],
    "total": 8,
    "trace_id": "019a1b2c-tr1-tr1-tr1-tr1tr1tr1tr1"
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1003 | scope 不存在 |
| 3003 | 向量索引未就绪 |

---

## 5. GET /api/v1/evidence/{claim_id}

获取某个 claim 的完整证据链（追溯到原始消息）。

### 安全考量

- 只返回当前 scope 可见的证据
- evidence 中的 `chunk_id` → `chunk_span` → `normalized_message` → `raw_message` 溯源链完整
- raw_message 只在当前 scope 有 consent 时返回

### Request

```http
GET /api/v1/evidence/{claim_id}?scope_id={scope_id}
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "claim_id": "c_001",
    "evidence_chain": [
      {
        "evidence_id": "019a1b2c-ev1-ev1-ev1-ev1ev1ev1",
        "chunk_id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
        "evidence_type": "primary",
        "relevance_score": 0.95,
        "source_span": {
          "char_start": 156,
          "char_end": 203,
          "excerpt": "[妈妈] 春天的时候去西湖应该很漂亮"
        },
        "provenance_chain": {
          "chunk": {
            "id": "019a1b2c-aaaa-bbbb-cccc-dddddddddddd",
            "chunk_type": "conversation_segment",
            "time_range_start": "2024-03-15T10:30:00Z",
            "time_range_end": "2024-03-15T10:32:00Z"
          },
          "normalized_message": {
            "id": "019a1b2c-nm1-nm1-nm1-nm1nm1nm1",
            "speaker_normalized": "mother",
            "timestamp": "2024-03-15T10:30:22Z",
            "content": "春天的时候去西湖应该很漂亮"
          },
          "source_artifact": {
            "id": "019a1b2c-art1-art1-art1-art1art1art1",
            "file_type": "wechat_txt",
            "date_range_start": "2024-01-01",
            "date_range_end": "2024-06-30"
          }
        }
      }
    ]
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1005 | claim_id 不存在 |
| 1004 | scope 不匹配或 consent 未授权 |

---

## 6. POST /api/v1/scope

创建新的关系作用域。

### 安全考量

- 每个 relationship_scope 对应一个亲属视角，创建时必须声明与逝者的关系类型
- 创建操作记录审计日志（action=SCOPE_CREATE）
- 新 scope 自动创建默认 `scope_safety_policy` 和 `scope_permission` 记录

### Request

```http
POST /api/v1/scope
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
  "scope_name": "作为儿子",
  "relationship_type": "child",
  "scope_description": "我是妈妈的儿子，想回忆和她在一起的时光",
  "initial_permissions": {
    "can_query_memory": "allow",
    "can_browse_original": "ask",
    "can_add_oral_history": "allow",
    "can_view_financial": "deny",
    "can_view_medical": "deny",
    "can_view_intimate": "deny"
  },
  "safety_policy": {
    "max_session_minutes": 60,
    "max_sessions_daily": 5,
    "late_night_start": "22:00",
    "late_night_end": "06:00",
    "max_late_night_sessions": 2,
    "dependency_threshold": 0.7,
    "farewell_refusal_limit": 3,
    "hard_break_enabled": true,
    "cooldown_minutes": 30,
    "escalate_on_crisis": true
  }
}
```

### Request Schema

| 字段 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `deceased_profile_id` | string (UUID) | 是 | 逝者档案 ID |
| `scope_name` | string | 是 | 作用域名称 |
| `relationship_type` | enum | 是 | 关系类型: `spouse`, `child`, `parent`, `sibling`, `friend`, `colleague`, `other` |
| `scope_description` | string | 否 | 作用域描述 |
| `initial_permissions` | object | 否 | 初始权限配置 |
| `safety_policy` | object | 否 | 安全策略配置 |

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
    "scope_name": "作为儿子",
    "relationship_type": "child",
    "is_active": true,
    "created_at": "2024-12-01T14:00:00Z",
    "permissions": {
      "can_query_memory": "allow",
      "can_browse_original": "ask",
      "can_add_oral_history": "allow",
      "can_view_financial": "deny",
      "can_view_medical": "deny",
      "can_view_intimate": "deny"
    }
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1005 | deceased_profile 不存在 |
| 1006 | scope 已存在 |

---

## 7. GET /api/v1/scope

列出关系作用域。

### Request

```http
GET /api/v1/scope?deceased_profile_id={profile_id}
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scopes": [
      {
        "scope_id": "019a1b2c-1111-1111-1111-111111111111",
        "scope_name": "作为儿子",
        "relationship_type": "child",
        "is_active": true,
        "created_at": "2024-12-01T14:00:00Z"
      }
    ],
    "total": 1
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1005 | deceased_profile 不存在 |

---

## 8. GET /api/v1/scope/{scope_id}

查看作用域详情。

### Request

```http
GET /api/v1/scope/{scope_id}
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "deceased_profile_id": "019a1b2c-2222-2222-2222-222222222222",
    "scope_name": "作为儿子",
    "relationship_type": "child",
    "scope_description": "我是妈妈的儿子，想回忆和她在一起的时光",
    "is_active": true,
    "created_at": "2024-12-01T14:00:00Z",
    "permissions": {
      "can_query_memory": "allow",
      "can_browse_original": "ask",
      "can_add_oral_history": "allow",
      "can_view_financial": "deny",
      "can_view_medical": "deny",
      "can_view_intimate": "deny"
    }
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1003 | scope 不存在 |

---

## 9. PUT /api/v1/scope/{scope_id}/permissions

更新作用域权限。

### Request

```http
PUT /api/v1/scope/{scope_id}/permissions
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "can_query_memory": "allow",
  "can_browse_original": "deny",
  "can_add_oral_history": "allow",
  "can_view_financial": "deny",
  "can_view_medical": "ask",
  "can_view_intimate": "deny"
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "permissions": {
      "can_query_memory": "allow",
      "can_browse_original": "deny",
      "can_add_oral_history": "allow",
      "can_view_financial": "deny",
      "can_view_medical": "ask",
      "can_view_intimate": "deny"
    },
    "updated_at": "2024-12-01T15:00:00Z"
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1003 | scope 不存在 |
| 1004 | 权限不足 |

---

## 10. POST /api/v1/scope/{scope_id}/soft-delete

软删除作用域。

### 安全考量

- 设置 `deleted_at` 时间戳，保留审计日志但标记数据不可访问
- 软删除操作记录审计日志

### Request

```http
POST /api/v1/scope/{scope_id}/soft-delete
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "reason": "不再需要这个视角"
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "deleted_at": "2024-12-01T16:00:00Z",
    "reason": "不再需要这个视角"
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1003 | scope 不存在 |
| 1007 | scope 已被删除 |

---

## 11. POST /api/v1/scope/{scope_id}/hard-delete

硬删除作用域（不可逆）。

### 安全考量

- 物理删除所有 scoped 数据
- 审计日志内容标记为 `REDACTED`
- 需要双重确认（`confirmation_token`）

### Request

```http
POST /api/v1/scope/{scope_id}/hard-delete
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "confirmation_token": "019a1b2c-conf-conf-conf-confconfconf",
  "reason": "用户要求彻底删除所有数据"
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "affected_tables": [
      "interaction_session",
      "interaction_message",
      "retrieval_trace",
      "response_claim",
      "claim_evidence",
      "data_subject_consent",
      "scope_permission",
      "scope_prompt_policy",
      "chunk_scope_visibility"
    ],
    "affected_rows": 1250,
    "completed_at": "2024-12-01T16:30:00Z",
    "audit_log_ids": ["019a1b2c-aud1-aud1-aud1-aud1aud1aud1"]
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1003 | scope 不存在 |
| 1004 | confirmation_token 不匹配 |
| 1007 | scope 已被删除 |

---

## 12. GET /api/v1/scope/{scope_id}/visibility

查询 chunk 可见性。

### Request

```http
GET /api/v1/scope/{scope_id}/visibility
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "visibility_summary": {
      "scope_private": 45,
      "scope_shared": 12,
      "deceased_shared": 8,
      "global": 3
    },
    "total_visible_chunks": 68
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1003 | scope 不存在 |

---

## 13. POST /api/v1/scope/{scope_id}/visibility/upgrade

提升 chunk 可见性。

### 安全考量

- chunk 提升需要 `data_subject_consent` 显式授权
- 从 `scope_private` → `scope_shared` 或 `deceased_shared` 需要用户确认

### Request

```http
POST /api/v1/scope/{scope_id}/visibility/upgrade
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "chunk_ids": ["019a1b2c-aaaa-bbbb-cccc-dddddddddddd"],
  "target_visibility": "deceased_shared",
  "consent_evidence": "用户明确同意将这些记忆共享给其他亲属"
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "upgraded_chunks": 1,
    "consent_record_id": "019a1b2c-con1-con1-con1-con1con1con1"
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1003 | scope 不存在 |
| 4001 | consent 未授权 |

---

## 14. POST /api/v1/safety/evaluate

手动触发安全评估。

### 安全考量

- 此接口只读，不产生副作用
- 评估结果基于当前 session 的 8 项指标

### Request

```http
POST /api/v1/safety/evaluate
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "scope_id": "019a1b2c-1111-1111-1111-111111111111",
  "session_id": "019a1b2c-sss1-sss1-sss1-sss1sss1sss1",
  "current_query": "妈妈最近好吗？",
  "indicators_override": null
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "indicators": {
      "session_duration_minutes": 25.3,
      "sessions_today_count": 2,
      "late_night_count": 0,
      "emotional_risk_score": 0.1,
      "dependency_phrases": 0,
      "farewell_refusal_count": 0,
      "user_age_flag": "adult",
      "recent_safety_events": 0
    },
    "directive": {
      "action": "ALLOW",
      "reason": "",
      "cooldown_minutes": 0,
      "template_id": "",
      "allow_llm": true,
      "disconnect_after_response": false,
      "safety_event_data": null
    },
    "triggered_policies": []
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 指标无效 |
| 1002 | Token 无效 |
| 1003 | scope 或 session 不存在 |

---

## 15. GET /api/v1/safety/policy/{scope_id}

查看安全策略。

### Request

```http
GET /api/v1/safety/policy/{scope_id}
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "max_session_minutes": 60,
    "max_sessions_daily": 5,
    "late_night_start": "22:00",
    "late_night_end": "06:00",
    "max_late_night_sessions": 2,
    "dependency_threshold": 0.7,
    "farewell_refusal_limit": 3,
    "hard_break_enabled": true,
    "cooldown_minutes": 30,
    "escalate_on_crisis": true,
    "updated_at": "2024-12-01T14:00:00Z"
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1003 | scope 不存在 |

---

## 16. PUT /api/v1/safety/policy/{scope_id}

更新安全策略。

### Request

```http
PUT /api/v1/safety/policy/{scope_id}
Content-Type: application/json
X-Remnant-Token: <token>
```

```json
{
  "max_session_minutes": 45,
  "max_sessions_daily": 3,
  "dependency_threshold": 0.6
}
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "scope_id": "019a1b2c-1111-1111-1111-111111111111",
    "max_session_minutes": 45,
    "max_sessions_daily": 3,
    "late_night_start": "22:00",
    "late_night_end": "06:00",
    "max_late_night_sessions": 2,
    "dependency_threshold": 0.6,
    "farewell_refusal_limit": 3,
    "hard_break_enabled": true,
    "cooldown_minutes": 30,
    "escalate_on_crisis": true,
    "updated_at": "2024-12-01T15:00:00Z"
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1001 | 参数无效 |
| 1002 | Token 无效 |
| 1003 | scope 不存在 |

---

## 17. GET /api/v1/safety/events/{scope_id}

查看安全事件历史。

### Request

```http
GET /api/v1/safety/events/{scope_id}?limit=20
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "events": [
      {
        "event_id": "019a1b2c-se1-se1-se1-se1se1se1",
        "scope_id": "019a1b2c-1111-1111-1111-111111111111",
        "session_id": "019a1b2c-sss1-sss1-sss1-sss1sss1sss1",
        "action": "SOFT_BREAK",
        "trigger_level": "dependency",
        "detail": "检测到依赖性表达: '不能没有你'",
        "created_at": "2024-12-01T22:30:00Z"
      }
    ],
    "total": 1
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |
| 1003 | scope 不存在 |

---

## 18. GET /api/v1/data/artifacts

列出数据制品。

### Request

```http
GET /api/v1/data/artifacts?scope_id={scope_id}&source_type=wechat_txt
X-Remnant-Token: <token>
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "artifacts": [
      {
        "id": "019a1b2c-art1-art1-art1-art1art1art1",
        "scope_id": "019a1b2c-1111-1111-1111-111111111111",
        "source_type": "wechat_txt",
        "file_hash": "sha256:a1b2c3d4e5f6...",
        "file_path": "REDACTED",
        "date_range_start": "2024-01-01",
        "date_range_end": "2024-06-30",
        "total_messages": 120,
        "import_status": "COMPLETED",
        "created_at": "2024-12-01T14:00:00Z"
      }
    ],
    "total": 1
  },
  "message": "ok"
}
```

### Error Codes

| 错误码 | 描述 |
|--------|------|
| 1002 | Token 无效 |

---

## 19. GET /api/v1/health

健康检查。

### Request

```http
GET /api/v1/health
```

### Response (200 OK)

```json
{
  "code": 0,
  "data": {
    "status": "healthy",
    "version": "0.1.0",
    "uptime_seconds": 86400,
    "database_connected": true,
    "vector_index_ready": true
  },
  "message": "ok"
}
```

---

## 附录：数据类型定义

### Relationship Type

```
enum RelationshipType {
  spouse      // 配偶
  child       // 子女
  parent      // 父母
  sibling     // 兄弟姐妹
  friend      // 朋友
  colleague   // 同事
  other       // 其他
}
```

### Permission Values

```
enum PermissionValue {
  allow    // 允许
  ask      // 每次询问
  deny     // 拒绝
}
```

### Safety Action

```
enum SafetyAction {
  ALLOW              // 允许继续
  SOFT_BREAK         // 添加缓冲语，建议休息
  HARD_BREAK         // 强制暂停，显示模板消息
  COOLDOWN           // 冷却期，暂时禁止对话
  ESCALATE           // 升级处理，显示危机资源
}
```

### Import Job Status

```
enum ImportJobStatus {
  PENDING      // 等待处理
  PARSING      // 正在解析
  NORMALIZING  // 正在规范化
  CHUNKING     // 正在分块
  ANNOTATING   // 正在标注
  INDEXING     // 正在索引
  COMPLETED    // 已完成
  FAILED       // 失败
}
```

### Claim Type

```
enum ClaimType {
  supported_memory         // 有充分证据支撑的记忆
  inferred_but_supported   // 推断但有部分证据支撑
  unsupported_memory       // 无证据支撑（不应出现在输出中）
  user_provided_context    // 用户提供的背景信息
  refusal                  // 拒答标记
}
```

### Support Status

```
enum SupportStatus {
  fully_supported       // 完全有证据支撑
  partially_supported   // 部分有证据支撑
  unsupported           // 无证据支撑
  contradicted          // 证据矛盾
}
```

### Content Type

```
enum ContentType {
  text        // 文本消息
  system      // 系统消息
  recall      // 撤回消息
  image       // 图片
  voice       // 语音
  file        // 文件
  video       // 视频
  red_packet  // 红包/转账
  location    // 位置
  sticker     // 表情包
}
```
