# Remnant Quickstart

This guide gets the current developer preview running locally. Remnant v0.1 is
an architecture/runtime preview, not production software.

## What You Will Run

- Python sidecar modules and tests under `python/`
- A runnable preview demo that imports a fixture, queries evidence, deletes a
  relationship scope, and verifies raw-data integrity
- React frontend tests and production build under `src/`
- Rust/Tauri bridge checks under `src/src-tauri/`

## Requirements

- macOS, Linux, or Windows with a POSIX-like shell for the scripts
- Python 3.11 or 3.12 for the HTTP sidecar preview
- Node.js 22 for frontend CI parity
- Rust stable for the Tauri bridge

Python 3.13 is not in the sidecar preview support range yet.

## 1. Bootstrap Python

From the repository root:

```bash
tools/bootstrap-python.sh
```

The script selects `python3.12` or `python3.11`, creates `python/.venv`, installs
`python` in editable mode with dev dependencies, and runs the sidecar smoke
test.

If your supported interpreter is not on `PATH`, pass it explicitly:

```bash
REMNANT_PYTHON_BIN=/path/to/python3.12 tools/bootstrap-python.sh
tools/bootstrap-python.sh --python /path/to/python3.12
```

Manual setup:

```bash
cd python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests -q
```

## 2. Run The Preview Demo

```bash
cd python
.venv/bin/python scripts/run_preview_demo.py
```

The demo creates a temporary SQLite database and demonstrates the current
runtime loop:

1. Create a sample deceased profile and relationship scope.
2. Import a sample universal chat fixture.
3. Chunk and persist derived evidence with source spans.
4. Run an evidence-bounded scoped query.
5. Soft-delete the scope.
6. Verify that immutable raw messages are still intact.

## 3. Start The Sidecar

```bash
cd python
REMNANT_AUTH_TOKEN=dev-token REMNANT_ENABLE_DOCS=1 .venv/bin/python -m remnant_bridge
```

The sidecar binds to localhost. API routes require a local token. The Rust
bridge uses:

```http
Authorization: Bearer <token>
```

The Python sidecar also accepts:

```http
X-Remnant-Token: <token>
```

That compatibility header exists because older docs and whitepaper examples use
it.

## 4. Run Frontend Checks

```bash
cd src
npm install
npm test
npm run build
```

For local frontend development:

```bash
cd src
npm run dev -- --host 127.0.0.1
```

The frontend is a runtime scaffold. Current workflows include import, profile
resolution, relationship-space selection, evidence query, safety policy loading,
and preview management screens.

## 5. Check The Tauri Bridge

```bash
cd src/src-tauri
cargo check --locked
cargo test --locked
```

When launching the desktop app, set `REMNANT_PYTHON_BIN` if your default
`python3` is not Python 3.11 or 3.12:

```bash
cd src
REMNANT_PYTHON_BIN=python3.12 npm run tauri dev
```

## 6. Run The Same Gates As CI

```bash
cd python
.venv/bin/python scripts/run_preview_demo.py
.venv/bin/python -m pytest tests -q

cd ../src
npm test
npm run build

cd src-tauri
cargo check --locked
cargo test --locked
```

## Troubleshooting

### `python3` is unsupported

Use `REMNANT_PYTHON_BIN=python3.12` or `REMNANT_PYTHON_BIN=python3.11`.

### FastAPI or Pydantic import fails on macOS

Recreate the venv with Python 3.11 or 3.12 and reinstall:

```bash
cd python
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### The sidecar rejects requests

Check that `REMNANT_AUTH_TOKEN` is set and that the client sends either
`Authorization: Bearer <token>` or `X-Remnant-Token: <token>`.

### The frontend cannot query evidence

The frontend needs the sidecar running for live requests. The tests mock the
bridge layer, so passing frontend tests does not mean the HTTP sidecar is
currently active.

## Next Reading

- [Architecture overview](architecture.md)
- [Open-source roadmap](open-source-roadmap.md)
- [Release checklist](release-v0.1.1-preview.md)
- [Contributing guide](../CONTRIBUTING.md)
