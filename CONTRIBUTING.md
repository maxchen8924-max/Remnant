# Contributing to Remnant

Remnant v0.1 is an architecture preview for a local-first digital legacy memory
runtime. Contributions are welcome, especially in storage, provenance,
retrieval, safety policy, frontend workflows, and documentation.

## Project Boundaries

Please keep these boundaries intact:

- Do not position Remnant as resurrecting or replacing a deceased person.
- Do not generate factual memories without evidence.
- Do not bypass relationship-scope isolation.
- Do not make voice synthesis enabled by default.
- Do not optimize for emotional dependency, retention loops, or late-night use.
- Do not weaken deletion, audit, consent, or provenance behavior without tests.

## Development Setup

Use Python 3.11 or 3.12 for the HTTP sidecar preview.

```bash
cd python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests -q
```

Run the preview demo:

```bash
cd python
.venv/bin/python scripts/run_preview_demo.py
```

Run the HTTP sidecar smoke test from a Python 3.11 or 3.12 venv:

```bash
cd python
pytest tests/test_sidecar_smoke.py -q
```

Run frontend and Rust checks:

```bash
cd src
npm install
npm test
npm run build

cd src-tauri
cargo check
cargo test
```

## Pull Request Expectations

- Keep changes focused and explain the user-visible behavior.
- Add or update tests for behavior changes.
- Include raw-data, scope, deletion, safety, and provenance tests when those
  areas are touched.
- Document maturity honestly; do not describe preview features as production
  ready.
- Prefer small, reviewable PRs over sweeping rewrites.

## Useful First Issues

- Add a sidecar smoke test for Python 3.11/3.12.
- Improve CJK retrieval tokenization beyond the keyword fallback.
- Add import validation and duplicate-file handling.
- Build a minimal evidence drawer in the frontend.
- Turn the security checklist into tracked issues.
