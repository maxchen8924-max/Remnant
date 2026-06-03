"""Tests for the repository-level Python environment bootstrap script."""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "tools" / "bootstrap-python.sh"


def _fake_python(bin_dir: Path, name: str, version: str) -> Path:
    path = bin_dir / name
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env sh
            if [ "$1" = "--version" ]; then
              echo "Python {version}"
              exit 0
            fi
            echo "{name} fake runner called with: $@"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_bootstrap_dry_run_selects_supported_python(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_python(bin_dir, "python3.12", "3.12.13")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        ["bash", str(BOOTSTRAP), "--dry-run"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Using Python:" in result.stdout
    assert "python3.12" in result.stdout
    assert "python/.venv" in result.stdout
    assert "pip install -e '.[dev]'" in result.stdout


def test_bootstrap_rejects_unsupported_python_313(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_bin = _fake_python(bin_dir, "python3.13", "3.13.12")

    env = os.environ.copy()
    env["REMNANT_PYTHON_BIN"] = str(python_bin)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        ["bash", str(BOOTSTRAP), "--dry-run"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Python 3.11 or 3.12" in result.stderr


def test_bootstrap_help_documents_override_and_dry_run():
    result = subprocess.run(
        ["bash", str(BOOTSTRAP), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "REMNANT_PYTHON_BIN" in result.stdout
