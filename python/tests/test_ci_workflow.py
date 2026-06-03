"""Repository CI workflow contract tests."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run_commands(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def test_ci_python_job_covers_supported_sidecar_versions():
    workflow = _workflow()
    python_job = workflow["jobs"]["python"]

    assert python_job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]

    commands = _run_commands(python_job)
    assert "python scripts/run_preview_demo.py" in commands
    assert "python -m pytest tests -q" in commands


def test_ci_frontend_and_rust_jobs_cover_preview_release_gates():
    workflow = _workflow()

    frontend_commands = _run_commands(workflow["jobs"]["frontend"])
    assert "npm ci" in frontend_commands
    assert "npm test" in frontend_commands
    assert "npm run build" in frontend_commands

    rust_commands = _run_commands(workflow["jobs"]["rust"])
    assert "cargo check --locked" in rust_commands
    assert "cargo test --locked" in rust_commands
