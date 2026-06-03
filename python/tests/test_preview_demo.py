"""Preview demo regression tests."""

from __future__ import annotations

from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sample_dataset"


def test_preview_demo_runs_import_query_and_delete(tmp_path: Path) -> None:
    from remnant_bridge.preview_demo import run_preview_demo

    result = run_preview_demo(
        db_path=tmp_path / "preview.db",
        fixture_dir=FIXTURE_DIR,
        query="西湖",
    )

    assert result["profile"]["id"]
    assert result["scope"]["id"]
    assert result["import"]["parse_status"] == "PARSED"
    assert result["import"]["message_count"] > 0
    assert result["query"]["retrieval_trace_id"]
    assert "Evidence-backed memory summary" in result["query"]["content"]
    assert result["delete"]["status"] == "completed"
    assert result["raw_data_integrity"]["raw_data_integrity"] is True


def test_preview_demo_summary_is_cli_friendly(tmp_path: Path) -> None:
    from remnant_bridge.preview_demo import format_preview_summary, run_preview_demo

    result = run_preview_demo(
        db_path=tmp_path / "preview.db",
        fixture_dir=FIXTURE_DIR,
        query="红烧肉",
    )

    summary = format_preview_summary(result)

    assert "Remnant preview demo" in summary
    assert "Import:" in summary
    assert "Query:" in summary
    assert "Soft delete:" in summary
