# Remnant Open-Source Roadmap

This document describes how to evolve Remnant from a v0.1 architecture preview
into a credible open-source local-first memory runtime.

## Positioning

Remnant should be opened as a **digital legacy memory safety/reference
architecture**, not as a finished mourning chatbot.

The strongest idea is the architecture:

- local-first storage and sidecar runtime
- immutable raw data plus derived annotations
- relationship-scope isolation
- evidence/provenance-first retrieval
- consent, deletion, and audit trails
- anti-dependency safety policy hooks

This framing gives stronger developers room to extend the system without
misunderstanding it as an "AI resurrection" demo.

## Application Range

Good fits:

- personal digital legacy archives
- family memory preservation tools
- grief-safe evidence browsing interfaces
- local-first RAG systems that need strict provenance
- compliance-heavy memory systems with deletion/audit needs
- research prototypes for consent-aware AI interaction

Poor fits:

- real-time companion bots that simulate the deceased without evidence
- cloud-first SaaS products that centralize private family data
- systems that optimize emotional dependency or daily retention
- voice/face cloning products without explicit consent and watermarking
- generic chatbots that treat provenance as optional

## Current v0.1 Scope

Working or partially working:

- schema creation and SQLite triggers
- source adapter import pipeline with universal chat JSON and WeChat TXT
- chunk provenance spans
- scope-aware chunk visibility
- FTS/vector retrieval primitives
- retrieval trace records
- safety policy primitives and tests
- Python bridge token auth
- bridge runtime helpers for import, query, and scoped deletion
- Tauri sidecar process management scaffold

## v0.2 Developer Alpha Progress

Implemented developer-alpha capabilities:

- Trace-based evidence inspection API:
  `GET /api/v1/evidence/trace/{trace_id}` enriches a retrieval trace with
  visible chunks, source artifact metadata, and span provenance.
- Evidence inspection redacts local `source_artifact.file_path` from API
  responses and returns `source_path_status: "redacted"` instead.
- The frontend query workflow links returned `retrieval_trace_id` values to the
  evidence inspector.
- The frontend evidence page can load a trace locally and display trace
  metadata, source artifact type/hash, scores, evidence chunks, and spans.
- Regression tests cover trace evidence enrichment, the FastAPI evidence route,
  and the React evidence inspection workflow.

Not production-ready:

- local LLM generation
- embedding generation and indexing workflow
- full embedding-backed retrieval workflow
- complete security review and external threat model
- encrypted production storage
- end-to-end packaged desktop distribution
- voice synthesis runtime

## Next Optimization Tracks

1. Runtime reliability

   - Add a sidecar smoke test that starts `python -m remnant_bridge` on a random
     port and checks `/health`.
   - Add structured startup diagnostics for missing Python modules, invalid DB
     paths, and port conflicts.
   - Keep bridge helpers testable without importing FastAPI/Pydantic.

2. Import credibility

   - Keep source adapters platform-neutral, with WeChat as a regional example
     rather than the default product assumption.
   - Publish a canonical `universal_chat_json` fixture so contributors can map
     WhatsApp, Telegram, Discord, Slack, LINE, KakaoTalk, iMessage, or email
     exports into the existing ETL flow.
   - Validate file type and path before ETL.
   - Add duplicate import behavior around `source_artifact.file_hash`.
   - Redact or hash stored source paths after import, or make path retention a
     deliberate privacy setting.
   - Add import progress state instead of pretending sync ETL is a background job.

3. Retrieval quality

   - Add query classification for time, speaker, and relationship intent.
   - Wire local embedding generation and store vectors deterministically.
   - Split retrieval traces into raw FTS/vector/reranked evidence with stable
     score semantics.
   - Add contradiction handling before any generated factual claim is emitted.

4. Safety and consent

   - Treat safety directives as a policy gate before ordinary retrieval.
   - Add consent checks around data categories and scope permissions.
   - Make hard deletion verification explicit: before count, after count,
     retained audit IDs, retained raw-data integrity.
   - Add crisis and dependency templates that do not rely on LLM generation.

5. Frontend readiness

   - Replace placeholder pages with real workflows:
     import, scope selection, query, evidence drawer, timeline, deletion.
   - Show source evidence beside every memory answer.
   - Make safety interruptions visible and calm rather than punitive.
   - Avoid marketing-first UX; this should feel like a careful local archive.

6. Open-source governance

   - Add `CONTRIBUTING.md`, `SECURITY.md`, and a minimal code of conduct.
   - Add a maturity badge: `Architecture Preview`.
   - Keep a public issue label set for storage, retrieval, safety, frontend,
     docs, and security.
   - Require tests for behavior changes touching deletion, consent, auth, or
     provenance.

## Release Gates

v0.1.1 preview:

- `python -m remnant_bridge` package entrypoint works.
- Auth token generated by Python validates itself.
- `REMNANT_AUTH_TOKEN` from Rust is honored.
- Import/query/destroy routes call real runtime helpers.
- Runnable preview demo imports a fixture, queries evidence, soft-deletes a
  scope, and verifies raw-data integrity.
- Tauri sidecar can select a supported interpreter with `REMNANT_PYTHON_BIN`.
- Python support is declared as 3.11/3.12 for the HTTP sidecar preview.
- Sidecar smoke test exists and runs on supported Python interpreters.
- GitHub Actions CI runs Python sidecar, frontend, and Rust preview gates.
- Open-source contribution, security, license, changelog, and issue templates
  are present.
- README states maturity and unfinished modules clearly.

v0.2 developer alpha:

- Sidecar smoke test passes in CI on Python 3.11 and 3.12.
- Import supports at least one real sample fixture end to end.
- Query returns evidence summaries with retrieval trace IDs.
- Frontend can import, query, and inspect evidence locally through trace IDs.
- Security checklist has owners and status for each threat item.

Remaining v0.2 hardening:

- Add duplicate import behavior around `source_artifact.file_hash`.
- Decide whether persisted `source_artifact.file_path` should be redacted on
  import or retained behind an explicit privacy setting.
- Turn the highest-risk security checklist items into automated tests.
- Add one documented end-to-end command that imports the sample fixture, queries
  it, and opens the trace evidence payload.

v0.3 research alpha:

- Local embedding pipeline is integrated.
- Local LLM response generation is evidence-gated.
- Claim extraction and evidence linking are persisted.
- Consent policy blocks unauthorized categories.
- Deletion verification report is generated after scoped deletion.

v1.0 candidate:

- Local encryption story is tested.
- Threat model has external review.
- Desktop package can be built and signed.
- Voice synthesis remains disabled unless consent, watermarking, and policy
  checks are implemented.
- End-to-end tests cover import, query, evidence, safety break, and deletion.

## Non-Negotiables

- Do not market this as resurrecting a person.
- Do not generate factual memories without evidence.
- Do not blur the boundary between archive, assistant, and the deceased person.
- Do not optimize for emotional dependency.
- Do not enable voice synthesis by default.
- Do not allow one relationship scope to silently read another scope's data.
