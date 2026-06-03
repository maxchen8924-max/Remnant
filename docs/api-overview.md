# Remnant Preview API Overview

This document summarizes the HTTP sidecar routes registered in the current
v0.1 preview runtime. It is written for developers who want to run, inspect, or
extend Remnant locally.

For setup instructions, see [Quickstart](quickstart.md). For the system model,
see [Architecture Overview](architecture.md). The older detailed reference is
available in [api_reference.md](api_reference.md).

## Maturity

The API is a developer preview, not a production contract.

- It is intended for localhost sidecar usage.
- It uses an ephemeral local token instead of user-account authentication.
- Some routes are scaffolds for future behavior.
- Response shapes may change before a stable release.
- Local LLM generation and embedding generation are not wired end to end yet.

## Base URL

The default sidecar address is:

```text
http://127.0.0.1:18731
```

Start it with API docs enabled:

```bash
cd python
REMNANT_AUTH_TOKEN=dev-token REMNANT_ENABLE_DOCS=1 .venv/bin/python -m remnant_bridge
```

Then open:

```text
http://127.0.0.1:18731/docs
```

## Authentication

`GET /health` is public. All other routes require a local sidecar token.

Preferred header:

```http
Authorization: Bearer dev-token
```

Compatibility header:

```http
X-Remnant-Token: dev-token
```

When the Tauri desktop shell starts the sidecar, it injects
`REMNANT_AUTH_TOKEN` automatically. When running Python directly, set it
manually as shown above.

## Active Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check. No token required. |
| `POST` | `/api/v1/profile/resolve` | Resolve or create a user-facing deceased profile name. |
| `POST` | `/api/v1/import` | Import a source file through the ETL pipeline. |
| `POST` | `/api/v1/query` | Run scoped retrieval and return either SSE or a JSON response. |
| `POST` | `/api/v1/scope/create` | Create a relationship space. |
| `POST` | `/api/v1/scope/delete` | Delete a relationship space by deletion type. |
| `POST` | `/api/v1/scope/soft-delete` | Soft-delete a relationship space. |
| `POST` | `/api/v1/scope/hard-delete` | Hard-delete a relationship space. |
| `GET` | `/api/v1/scope/{scope_id}` | Get relationship-space details. |
| `GET` | `/api/v1/scope/list/{deceased_profile_id}` | List active relationship spaces for a profile. |
| `GET` | `/api/v1/scope/{scope_id}/permissions` | Read scope permissions. |
| `PUT` | `/api/v1/scope/{scope_id}/permissions/{permission_key}` | Update a permission value. |
| `GET` | `/api/v1/scope/{scope_id}/safety-policy` | Read scope safety policy. |
| `GET` | `/api/v1/scope/{scope_id}/prompt-policies` | Read prompt policy settings. |
| `PUT` | `/api/v1/scope/{scope_id}/prompt-policy/{policy_key}` | Update a prompt policy value. |
| `GET` | `/api/v1/scope/{scope_id}/visibility` | List visible chunks for a scope. |
| `POST` | `/api/v1/scope/{scope_id}/visibility/upgrade` | Upgrade chunk visibility to shared scope visibility. |
| `GET` | `/api/v1/evidence/{claim_id}` | Return evidence records for a claim. Preview scaffold. |
| `POST` | `/api/v1/safety/evaluate` | Evaluate session safety indicators and directives. |
| `GET` | `/api/v1/safety/policy/{scope_id}` | Read safety policy. |
| `PUT` | `/api/v1/safety/policy/{scope_id}` | Update safety policy fields. |
| `GET` | `/api/v1/safety/events/{scope_id}` | List recent safety events. |
| `POST` | `/api/v1/data/destroy` | Destroy scoped data through the deletion runtime. |

## Common Flow

1. Resolve a profile name.
2. Create a relationship space under that profile.
3. Import a chat source into that profile and optional relationship space.
4. Query within the relationship space.
5. Inspect evidence, safety, visibility, and deletion behavior.

## Examples

### Resolve A Profile

```bash
curl -s http://127.0.0.1:18731/api/v1/profile/resolve \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"profile_name":"Mom"}'
```

Response:

```json
{
  "deceased_profile_id": "profile-uuid",
  "profile_name": "Mom",
  "display_name": "Mom",
  "created": true
}
```

### Create A Relationship Space

```bash
curl -s http://127.0.0.1:18731/api/v1/scope/create \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "deceased_profile_id": "profile-uuid",
    "scope_name": "As her child",
    "relationship_type": "child",
    "scope_description": "Conversations from the child relationship context"
  }'
```

Response:

```json
{
  "scope_id": "scope-uuid",
  "status": "created",
  "scope": {}
}
```

Users should name relationship spaces in natural language. `scope_id` is an
internal identifier returned by the runtime for API routing and storage
integrity.

### Import Universal Chat JSON

```bash
curl -s http://127.0.0.1:18731/api/v1/import \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "deceased_profile_id": "profile-uuid",
    "scope_id": "scope-uuid",
    "file_path": "/absolute/path/to/chat.json",
    "file_type": "universal_chat_json",
    "encoding": "utf-8",
    "metadata": {
      "source": "example-adapter"
    }
  }'
```

Response:

```json
{
  "artifact_id": "artifact-uuid",
  "file_hash": "sha256...",
  "message_count": 42,
  "chunk_count": 8,
  "parse_status": "PARSED",
  "errors": []
}
```

Remnant should not be limited to one platform. Platform-specific adapters should
normalize exports into `universal_chat_json` before entering the core ETL
pipeline. Candidate adapters include WhatsApp, Telegram, Signal, Discord, Slack,
email mbox, WeChat, LINE, and iMessage exports when legally and technically
available.

### Query A Relationship Space

```bash
curl -s http://127.0.0.1:18731/api/v1/query \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "scope_id": "scope-uuid",
    "query": "What did she say about moving to New York?",
    "top_k": 10,
    "include_evidence": true,
    "stream": false
  }'
```

Response:

```json
{
  "session_id": "session-uuid",
  "message_id": "message-uuid",
  "content": "",
  "claims": [],
  "evidences": [],
  "retrieval_trace_id": "trace-uuid",
  "safety_flags": [],
  "duration_ms": 12
}
```

In this preview, querying exercises retrieval and traceability. Full answer
generation is still a future integration point.

### Safety Evaluation

```bash
curl -s http://127.0.0.1:18731/api/v1/safety/evaluate \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "scope_id": "scope-uuid",
    "session_id": "session-uuid",
    "current_query": "I cannot stop talking tonight",
    "session_stats": {
      "duration_minutes": 90
    }
  }'
```

This route returns a safety directive, collected indicators, and whether the
session should proceed.

### Scoped Deletion

Soft delete:

```bash
curl -s http://127.0.0.1:18731/api/v1/data/destroy \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "scope_id": "scope-uuid",
    "deletion_type": "scope_soft_delete",
    "confirm": true,
    "actor": "user"
  }'
```

Hard delete:

```bash
curl -s http://127.0.0.1:18731/api/v1/data/destroy \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "scope_id": "scope-uuid",
    "deletion_type": "scope_hard_delete",
    "confirm": true,
    "actor": "user"
  }'
```

Hard deletion is irreversible. It is retained as a developer-preview capability
so contributors can inspect deletion semantics and audit behavior.

## Preview Caveats

- `/api/v1/evidence/{claim_id}` is currently a scaffold and returns an empty
  evidence list.
- Query retrieval is active, but generative answering is not integrated.
- Embedding generation is not wired end to end.
- A retrieval route exists in the source tree but is not registered in the
  current FastAPI application.
- API schemas should be treated as preview shapes until a stable release is
  declared.
