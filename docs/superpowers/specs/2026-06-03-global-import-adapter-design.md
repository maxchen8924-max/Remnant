# Global Import Adapter Design

Status: design ready for review
Date: 2026-06-03

## Purpose

Remnant should support global memory data imports without treating any single
chat platform as the default world. WeChat text export remains a useful first
fixture, but the open-source architecture should be framed around source
adapters that convert legally obtained exports into a canonical message shape.

The goal for v0.2 is to make the import layer credible for global contributors:
someone should be able to add WhatsApp, Telegram, Discord, Slack, LINE,
KakaoTalk, iMessage, email, or another legally exported source by writing an
adapter instead of changing the core ETL pipeline.

## Product Boundary

The user-facing product should talk about named memory spaces and data sources,
not internal IDs or platform-specific assumptions.

Remnant can support all chat records that a user can legally obtain as export
files or local files. It must not bypass encryption, scrape cloud accounts
without authorization, extract private data from another user, or impersonate a
platform client.

## Recommended Approach

Use a two-layer import model:

```text
Raw export file
  -> Source adapter
  -> Canonical chat message
  -> Normalize
  -> Filter
  -> Chunk
  -> Evidence trace
  -> Scoped query
```

This keeps platform knowledge at the adapter edge and preserves the existing
Remnant core: immutable raw messages, derived chunks, scope isolation, evidence
traces, deletion, and safety policy.

## Alternatives Considered

### Add platform parsers one by one

This is fastest for isolated demos, but it makes the project look like a pile of
special cases. Contributors would not know what a new parser is supposed to
produce, and platform-specific logic would leak into downstream ETL.

### Build a full plugin system now

This is powerful, but too heavy for v0.2. It would introduce packaging,
permissions, version compatibility, and dynamic loading before the canonical
schema is proven.

### Recommended: canonical schema plus adapter registry

Define a stable `universal_chat_json` format and use an adapter registry for
platform-specific formats. This gives contributors a clear target while keeping
implementation small enough for the developer alpha.

## Components

### SourceAdapter

Adapters convert source files into canonical messages.

Expected adapter metadata:

- `file_type`: stable import type such as `universal_chat_json`, `wechat_txt`,
  `whatsapp_txt`, or `telegram_json`.
- `platform`: source platform or `generic`.
- `format`: export format such as `json`, `txt`, `csv`, `mbox`, or `eml`.
- `capabilities`: supported features such as timestamps, participants, text
  messages, attachments, replies, reactions, and system messages.

Expected adapter behavior:

- validate the file before parsing
- return messages in chronological order when timestamps are available
- preserve enough original metadata for evidence and future reprocessing
- mark partial or skipped records without silently fabricating content

### Adapter Registry

The registry maps `file_type` to adapter implementation. The current
`ETLPipeline._PARSER_REGISTRY` can evolve into this registry without changing
the whole pipeline at once.

Initial v0.2 registry:

- `universal_chat_json`: canonical global chat fixture and contributor target
- `wechat_txt`: existing adapter, retained as a regional example

Future registry entries:

- `whatsapp_txt`
- `telegram_json`
- `discord_export`
- `slack_export`
- `email_mbox`
- `email_eml`

### Canonical Chat Message

The canonical message shape should be adapter-neutral and close to the existing
`RawMessage` structure so the first implementation does not require a schema
migration.

Suggested JSON shape:

```json
{
  "version": 1,
  "source": {
    "platform": "generic",
    "export_format": "json",
    "exported_at": "2026-06-03T00:00:00Z"
  },
  "conversation": {
    "id": "family-chat",
    "title": "Family chat",
    "participants": [
      {
        "id": "u1",
        "display_name": "Alice",
        "role": "speaker"
      }
    ]
  },
  "messages": [
    {
      "id": "m1",
      "timestamp": "2024-01-15T10:30:00+08:00",
      "sender_id": "u1",
      "sender_name": "Alice",
      "content": "I want to visit West Lake this weekend.",
      "content_type": "text",
      "attachments": [],
      "metadata": {}
    }
  ]
}
```

Mapping into current storage:

- `source_artifact.file_type`: selected adapter type
- `source_artifact.metadata`: source platform, export format, adapter version,
  participant summary, parse warnings
- `raw_message.speaker`: `sender_name` or stable sender display fallback
- `raw_message.content`: message text or supported placeholder text
- `raw_message.content_type`: `text`, `image`, `voice`, `file`, `system`,
  `recall`, or another known type
- `raw_message.metadata`: canonical message ID, sender ID, attachments, reply
  references, reactions, original platform metadata

## Data Flow

1. Frontend or CLI sends `ImportRequest` with `file_path`, `file_type`, optional
   scope, and metadata.
2. Import runtime validates the path, file type, and adapter availability.
3. Registry selects the adapter for `file_type`.
4. Adapter parses source export into canonical messages.
5. Existing normalizer, filters, chunker, span attachment, hashing, and storage
   continue to run.
6. Retrieval and Query pages remain scope-based and evidence-first.

## Error Handling

Adapters must fail loudly for unsupported formats and report partial parse
warnings for recoverable records.

Expected errors:

- unknown `file_type`
- file missing or unreadable
- invalid `universal_chat_json` schema version
- missing required message fields
- timestamp parse failures
- duplicate source artifact hash
- unsupported attachment-only records

Recoverable warnings should be stored in import response errors and
`source_artifact.metadata` without corrupting successful messages.

## Frontend Impact

The Import page should stop presenting WeChat as the default. It should show
memory data sources in platform-neutral language:

- chat exports
- email archives
- documents
- photos and attachments
- manual notes

For v0.2, the first usable import flow should expose `universal_chat_json` and
the existing `wechat_txt` adapter. Internal IDs can remain available for
developer diagnostics, but normal users should choose a named memory space and a
source type.

## Documentation Impact

README, roadmap, and release notes should describe Remnant as a local-first
memory import runtime with source adapters. WeChat should be described as an
example fixture, not as the central product assumption.

Contributor docs should include:

- canonical chat JSON schema
- adapter authoring contract
- adapter test requirements
- safety and legal boundaries

## Testing

v0.2 implementation should add tests for:

- `universal_chat_json` happy path
- invalid schema version
- missing required fields
- attachment metadata preservation
- adapter registry supported type list
- unknown file type failure
- existing `wechat_txt` behavior remains unchanged
- import API returns useful errors for unsupported adapters
- README or roadmap references do not frame WeChat as the only default import

## Non-Goals For v0.2

- dynamic third-party plugin loading
- platform account login
- cloud scraping
- encryption bypass
- full attachment OCR or voice transcription
- automatic import from every global platform
- migration of existing storage columns solely for adapter metadata

## Success Criteria

- A developer can inspect one canonical JSON fixture and understand how to
  contribute a new source adapter.
- The preview demo no longer reads as a WeChat-only product.
- Core ETL still works with the current WeChat sample.
- A new `universal_chat_json` fixture can be imported, chunked, queried, and
  traced through the existing evidence pipeline.
- Unsupported platforms fail with clear messages rather than silent best-effort
  parsing.
