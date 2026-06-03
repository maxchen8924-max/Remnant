# Remnant v0.1

Local-first digital legacy memory runtime.

[English](README.md) | [简体中文](README.zh-CN.md)

Remnant is an evidence-first architecture for preserving, querying, and safely
interacting with a deceased person's digital memories. It is not positioned as
an "AI resurrection" product. The current release is an open-source architecture
and runtime preview: useful for developers who want to study or extend the
storage model, provenance pipeline, relationship-scope isolation, retrieval
traceability, and safety policy layer.

## Maturity

**v0.1 is a developer preview, not production software.**

What is already useful:

- SQLite schema for immutable raw messages, derived chunks, scopes, evidence,
  retrieval traces, safety events, consent records, and deletion logs.
- Source adapter import path for universal chat JSON and WeChat text exports:
  parse, normalize, filter, chunk, attach spans, hash, and persist.
- Scope-aware FTS/vector retrieval primitives and retrieval trace logging.
- Python sidecar bridge with localhost binding, ephemeral token auth, import,
  query, scope, safety, evidence, and data-destroy routes.
- Tauri/React shell with Rust bridge and Python sidecar lifecycle management.
- Regression tests for schema, ETL, scope safety, retrieval, token auth, and
  bridge runtime wiring.

What is intentionally unfinished:

- Local LLM generation is not integrated.
- Embedding generation is not wired end to end.
- Voice synthesis is schema-only and disabled by design.
- The frontend is a scaffold for the runtime, not a finished application.
- Security review items are documented but not fully certified.

## Design Principles

- **Local-first**: data is processed on the user's machine by default.
- **Evidence-first**: factual answers must come from stored evidence.
- **Provenance-first**: claims should be traceable back to source chunks/spans.
- **Raw data immutable**: raw messages are append-only and protected by triggers.
- **Derived annotation only**: cleaning, chunking, and labels are derived layers.
- **Relationship isolation**: each relationship scope has separate visibility.
- **Consent-aware deletion**: soft/hard scoped deletion is auditable.
- **Anti-dependency**: safety policies should interrupt risky usage patterns.

## Repository Layout

```text
remnant/
├── docs/               # whitepaper, API reference, handover, roadmap
├── python/             # Python backend and local sidecar
│   ├── remnant_etl/    # parser, cleaner, chunker, span, ETL pipeline
│   ├── remnant_core/   # retrieval, rerank, trace, prompt/safety primitives
│   ├── remnant_policy/ # safety, consent, scope policy modules
│   ├── remnant_store/  # SQLite schema, DAO, scope visibility/deletion
│   ├── remnant_bridge/ # FastAPI routes plus framework-light runtime helpers
│   └── tests/          # Python regression tests
└── src/                # Tauri 2 + React frontend
    ├── src/            # React pages, hooks, components
    └── src-tauri/      # Rust sidecar manager and IPC bridge
```

## Quick Start

For a detailed setup walkthrough, see [docs/quickstart.md](docs/quickstart.md).

Use Python 3.11 or 3.12 for the HTTP sidecar preview:

```bash
tools/bootstrap-python.sh
```

The bootstrap script selects `python3.12` or `python3.11`, creates
`python/.venv`, installs the Python sidecar dependencies, and runs the sidecar
smoke test. Use `REMNANT_PYTHON_BIN=/path/to/python3.12` or
`tools/bootstrap-python.sh --python /path/to/python3.12` when your supported
interpreter is not on `PATH`.

Manual setup:

```bash
cd python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests -q
```

Run the runnable preview demo:

```bash
cd python
.venv/bin/python scripts/run_preview_demo.py
```

The demo creates a temporary SQLite database, seeds a sample profile/scope,
imports a sample chat export, runs a scoped evidence query, performs scoped soft
deletion, and verifies that immutable raw messages are still intact.

Run the sidecar:

```bash
cd python
REMNANT_AUTH_TOKEN=dev-token REMNANT_ENABLE_DOCS=1 .venv/bin/python -m remnant_bridge
```

macOS note: if importing FastAPI fails with a `pydantic_core` code-signature
error, recreate the venv with Python 3.11 or 3.12 and reinstall `pip install -e
".[dev]"`. The framework-light bridge runtime tests do not require FastAPI, but
the HTTP sidecar does.

Frontend:

```bash
cd src
npm install
npm test
npm run build
```

Tauri:

```bash
cd src/src-tauri
cargo check
```

When launching the desktop app, set `REMNANT_PYTHON_BIN` if your default
`python3` is not a supported sidecar interpreter:

```bash
cd src
REMNANT_PYTHON_BIN=python3.12 npm run tauri dev
```

## API Auth

The Rust bridge sends `Authorization: Bearer <token>`. The Python sidecar also
accepts `X-Remnant-Token: <token>` for compatibility with the whitepaper and API
reference.

When the Tauri sidecar starts Python, it injects `REMNANT_AUTH_TOKEN`; standalone
Python runs can set that variable manually.

The Tauri sidecar uses `python3` by default. Override it with
`REMNANT_PYTHON_BIN=python3.12` or `REMNANT_PYTHON_BIN=python3.11` when needed.

## Contributor Tracks

- Storage and privacy: schema hardening, encryption, deletion verification.
- Retrieval quality: query classification, embedding generation, rerank tuning.
- Safety policy: anti-dependency metrics, crisis templates, audit evidence.
- Frontend runtime: import/query/timeline workflows and evidence inspection.
- Docs and governance: threat model, security checklist, contribution guide.

See [docs/open-source-roadmap.md](docs/open-source-roadmap.md) for the next
milestones and release gates.

## Start Here

- [Quickstart](docs/quickstart.md): set up Python, run the preview demo, test the
  frontend, and check the Tauri bridge.
- [Architecture overview](docs/architecture.md): understand the local-first
  runtime, storage model, evidence pipeline, scopes, safety layer, and bridge.
- [API overview](docs/api-overview.md): inspect the active localhost sidecar
  routes, token auth, common flow, examples, and preview caveats.
- [Open-source roadmap](docs/open-source-roadmap.md): current maturity, release
  gates, and contribution tracks.
- [Contributing guide](CONTRIBUTING.md): project boundaries, checks, PR
  expectations, and first contribution ideas.
- [Security policy](SECURITY.md): how to report security issues and what the
  preview security review covers.

## References

- [Quickstart](docs/quickstart.md)
- [Architecture overview](docs/architecture.md)
- [API overview](docs/api-overview.md)
- [Architecture whitepaper](docs/remnant-v0.1-architecture-whitepaper.md)
- [API reference](docs/api_reference.md)
- [v0.1 handover](docs/handover-v0.1.md)
- [Open-source roadmap](docs/open-source-roadmap.md)
- [v0.1.1 preview release checklist](docs/release-v0.1.1-preview.md)
- [Security checklist](docs/security_review_checklist.md)
