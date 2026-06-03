#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tools/bootstrap-python.sh [options]

Create Remnant's Python sidecar environment with a supported interpreter.

Options:
  --python PATH      Use a specific Python executable.
  --dry-run         Print the commands without creating the environment.
  --skip-smoke      Install dependencies but skip the sidecar smoke test.
  -h, --help        Show this help.

Environment:
  REMNANT_PYTHON_BIN  Optional Python executable override.

Remnant's HTTP sidecar preview supports Python 3.11 or 3.12.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_DIR="$REPO_ROOT/python"

DRY_RUN=0
RUN_SMOKE=1
REQUESTED_PYTHON="${REMNANT_PYTHON_BIN:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --python)
      [ "$#" -ge 2 ] || die "--python requires a path"
      REQUESTED_PYTHON="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-smoke)
      RUN_SMOKE=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

select_python() {
  if [ -n "$REQUESTED_PYTHON" ]; then
    command_exists "$REQUESTED_PYTHON" || [ -x "$REQUESTED_PYTHON" ] || die "Python executable not found: $REQUESTED_PYTHON"
    printf '%s\n' "$REQUESTED_PYTHON"
    return
  fi

  if command_exists python3.12; then
    printf '%s\n' "python3.12"
    return
  fi

  if command_exists python3.11; then
    printf '%s\n' "python3.11"
    return
  fi

  die "Python 3.11 or 3.12 was not found. On macOS, install one with: brew install python@3.12"
}

PYTHON_BIN="$(select_python)"
VERSION_OUTPUT="$("$PYTHON_BIN" --version 2>&1)"
VERSION_PAIR="$(printf '%s' "$VERSION_OUTPUT" | sed -n 's/^Python \([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1.\2/p')"

[ -n "$VERSION_PAIR" ] || die "Could not parse Python version from: $VERSION_OUTPUT"

if [ "$VERSION_PAIR" != "3.11" ] && [ "$VERSION_PAIR" != "3.12" ]; then
  die "Unsupported $VERSION_OUTPUT. Remnant's HTTP sidecar preview requires Python 3.11 or 3.12."
fi

print_plan() {
  printf 'Remnant Python bootstrap\n'
  printf 'Using Python: %s (%s)\n' "$PYTHON_BIN" "$VERSION_OUTPUT"
  printf 'Repository: %s\n' "$REPO_ROOT"
  printf 'Virtualenv: python/.venv\n'
  printf '+ cd python\n'
  printf '+ %s -m venv .venv\n' "$PYTHON_BIN"
  printf '+ .venv/bin/python -m pip install --upgrade pip\n'
  printf "+ .venv/bin/python -m pip install -e '.[dev]'\n"
  if [ "$RUN_SMOKE" -eq 1 ]; then
    printf '+ .venv/bin/python -m pytest tests/test_sidecar_smoke.py -q\n'
  fi
}

print_plan

if [ "$DRY_RUN" -eq 1 ]; then
  exit 0
fi

cd "$PYTHON_DIR"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'

if [ "$RUN_SMOKE" -eq 1 ]; then
  .venv/bin/python -m pytest tests/test_sidecar_smoke.py -q
fi

cat <<'EOF'

Python sidecar environment is ready.

Try:
  cd python
  .venv/bin/python scripts/run_preview_demo.py

For the Tauri app:
  cd src
  REMNANT_PYTHON_BIN=../python/.venv/bin/python npm run tauri dev
EOF
