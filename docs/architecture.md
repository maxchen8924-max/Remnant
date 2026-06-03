# Remnant Architecture Overview

Remnant is a local-first digital legacy memory runtime. It is designed as a
reference architecture for evidence-bounded memory preservation and retrieval,
not as an "AI resurrection" product.

## System Shape

```text
User desktop
├── Tauri shell
│   ├── React UI
│   └── Rust bridge and sidecar process manager
└── Python sidecar
    ├── FastAPI routes
    ├── framework-light runtime helpers
    ├── ETL and retrieval modules
    ├── safety and consent policy modules
    └── local SQLite store
```

The current preview keeps the main runtime local. The desktop bridge starts or
connects to the sidecar, injects an ephemeral token, and calls localhost routes.

## Core Principles

- **Local-first**: private memory data is processed on the user's machine by
  default.
- **Evidence-first**: factual answers must be grounded in stored source
  evidence.
- **Provenance-first**: chunks and claims should trace back to source spans.
- **Raw data immutable**: imported raw messages are append-only and protected by
  SQLite triggers.
- **Derived annotation only**: cleaning, normalization, chunking, labels, and
  retrieval traces are derived layers.
- **Relationship isolation**: each relationship scope controls visibility and
  policy independently.
- **Consent-aware deletion**: scoped deletion is auditable and distinguishes
  derived data from immutable raw records.
- **Anti-dependency**: safety rules should interrupt risky usage patterns
  instead of optimizing for retention.

## Data Flow

1. **Import**: a source adapter parses a local export, such as
   `universal_chat_json` or `wechat_txt`.
2. **Normalize**: ETL normalizes speakers, timestamps, and message metadata.
3. **Chunk**: conversation chunks are created as derived evidence units.
4. **Attach spans**: each chunk records which raw source rows contributed to it.
5. **Persist**: raw messages, source artifacts, chunks, spans, and audit records
   are stored in SQLite.
6. **Scope**: relationship-space visibility controls which chunks can be seen by
   a given user context.
7. **Retrieve**: scoped FTS/vector primitives find candidate chunks.
8. **Trace**: retrieval traces record query evidence and timing.
9. **Respond**: the current preview returns evidence summaries. Local LLM
   generation is intentionally not integrated yet.

## Storage Layers

The SQLite store separates immutable facts from derived interpretation:

- `raw_message`: source message rows protected by immutability triggers
- `source_artifact`: imported file metadata and hashes
- `memory_chunk`: derived conversation chunks
- `chunk_source_span`: provenance links from chunks to raw source rows
- `relationship_scope`: user-facing relationship spaces
- `scope_chunk_visibility`: per-scope visibility for chunks
- `retrieval_trace`: query and evidence trace records
- `safety_event`: safety decisions and interruptions
- `consent_record`: consent and data-category metadata
- `deletion_log`: scoped soft/hard deletion audit records

This separation lets contributors improve retrieval, labeling, or UI workflows
without rewriting the raw data model.

## Relationship Spaces

Remnant does not expose internal scope IDs as a user-facing concept in the main
app flow. Users create or select relationship spaces by name, such as "as a
daughter" or "old classmates". The runtime still keeps stable IDs internally for
auditability, deletion, and permission checks.

Each relationship space can have its own:

- relationship type
- scope description
- visibility rules
- safety policy
- deletion/audit history

The goal is to let humans use natural names while preserving machine-grade
traceability.

## Import Adapter Strategy

The import layer is intentionally global and platform-neutral. WeChat is a
regional adapter example, not the product assumption.

The canonical adapter format is `universal_chat_json`. Contributors can map
WhatsApp, Telegram, Discord, Slack, LINE, KakaoTalk, iMessage, email, diary, or
other exports into that shape before entering the ETL pipeline.

Adapter work should preserve:

- sender identity
- timestamp and timezone behavior
- message text and attachment references where safe
- source row identity
- enough metadata for provenance and audit

## Safety Layer

The safety system is a policy gate around use patterns, not a generic content
moderation label. Current preview primitives include:

- session duration and daily session limits
- late-night usage limits
- dependency threshold settings
- soft break, hard break, and escalation event records
- crisis/dependency hooks that can be made visible in the UI

Safety features should remain calm, explainable, and auditable.

## Bridge And Auth

The Rust bridge talks to the Python sidecar over localhost and sends:

```http
Authorization: Bearer <token>
```

The Python sidecar also accepts:

```http
X-Remnant-Token: <token>
```

The Tauri sidecar manager injects `REMNANT_AUTH_TOKEN` when it starts Python.
Standalone sidecar runs can set the same variable manually.

## Preview Limitations

The following are intentionally not production-ready:

- local LLM generation
- embedding generation and indexing workflow
- voice synthesis runtime
- packaged and signed desktop distribution
- encrypted production storage
- externally reviewed threat model

Any contribution that touches auth, deletion, provenance, consent, scope
isolation, or safety policy should include focused regression tests.

## Extension Points

Good first contribution areas:

- new import adapters that target `universal_chat_json`
- duplicate import detection and user-visible import validation
- CJK and multilingual retrieval quality
- local embedding generation behind deterministic tests
- evidence drawer and timeline UI workflows
- safety event presentation and policy editing
- threat model and security checklist tracking

## Next Reading

- [Quickstart](quickstart.md)
- [Open-source roadmap](open-source-roadmap.md)
- [API reference](api_reference.md)
- [Security checklist](security_review_checklist.md)
- [Contributing guide](../CONTRIBUTING.md)
