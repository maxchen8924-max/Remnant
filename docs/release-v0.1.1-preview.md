# Remnant v0.1.1 Preview Release Checklist

This checklist prepares Remnant for an open-source architecture preview release.
It is not a production-readiness checklist.

## Release Positioning

- Release name: `v0.1.1-preview`
- Audience: developers, researchers, and privacy/safety reviewers
- Positioning: local-first digital legacy memory runtime architecture preview
- Explicit non-positioning: not an "AI resurrection" product, not a finished
  mourning chatbot, not a production desktop app

## Included Scope

- README reframed around architecture/runtime preview maturity.
- Runnable preview demo for fixture import, scoped evidence query, scoped soft
  deletion, and raw-data integrity verification.
- Python bridge runtime helpers for import, query, and data-destroy routes.
- `python -m remnant_bridge` package entrypoint.
- Sidecar auth alignment for `Authorization: Bearer` and `X-Remnant-Token`.
- Rust sidecar support for `REMNANT_PYTHON_BIN`.
- Open-source governance files: license, contributing guide, security policy,
  code of conduct, changelog, and issue templates.

## Verification Commands

Run these before tagging:

```bash
cd python
.venv/bin/python scripts/run_preview_demo.py
.venv/bin/python -m pytest tests -q

cd ../src
npm test
npm run build

cd src-tauri
cargo check
cargo test
```

Run the HTTP sidecar smoke test with a Python 3.11 or 3.12 environment:

```bash
cd python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/test_sidecar_smoke.py -q
```

The smoke test is skipped on Python 3.13 because the preview sidecar is declared
for Python 3.11/3.12.

## Release Blockers

Block the tag if any of these are true:

- preview demo cannot import, query, soft-delete, and verify raw data
- Python tests fail on a supported interpreter
- frontend build fails
- Rust `cargo check` or `cargo test` fails
- `python -m remnant_bridge` cannot serve `/health` on Python 3.11/3.12
- README claims production readiness or AI resurrection behavior
- auth, deletion, scope isolation, or provenance behavior changes without tests

## Known Preview Limits

- Local LLM generation is not integrated.
- Embedding generation is not wired end to end.
- Voice synthesis remains schema-only and disabled by design.
- The frontend is still a runtime scaffold.
- The security checklist has not completed external review.
- Python 3.13 is not part of the HTTP sidecar preview support range.

## Suggested Commit Boundary

Include the open-source preview work:

- `README.md`
- `CHANGELOG.md`
- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `LICENSE`
- `SECURITY.md`
- `.github/ISSUE_TEMPLATE/*`
- `docs/open-source-roadmap.md`
- `docs/release-v0.1.1-preview.md`
- `docs/api_reference.md`
- `python/pyproject.toml`
- `python/remnant_bridge/*`
- `python/remnant_store/chunk_visibility.py`
- `python/remnant_store/scope_deletion.py`
- `python/scripts/run_preview_demo.py`
- `python/tests/test_bridge_runtime.py`
- `python/tests/test_preview_demo.py`
- `python/tests/test_sidecar_smoke.py`
- `src/src-tauri/src/bridge.rs`
- `src/src-tauri/src/sidecar.rs`

Do not include unrelated local workspace state, agent memory logs, or experimental test edits unless they are intentionally part of a separate commit.

## Tag Notes

Recommended release note:

```text
Remnant v0.1.1-preview makes the v0.1 architecture runnable and easier to
evaluate: it adds a preview demo, real bridge runtime helpers, sidecar auth
alignment, Python interpreter override support for Tauri, and basic
open-source governance.

This is a developer architecture preview, not production software and not an
AI resurrection product.
```
