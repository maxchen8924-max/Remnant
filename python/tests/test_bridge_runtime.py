"""Bridge runtime regression tests.

These tests keep the local sidecar honest without requiring a running FastAPI
process. They cover the minimum behaviors an open-source preview needs to be
credible: executable package entrypoint, token validation, scoped search, and
runtime helpers that bridge API routes to real storage functions.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from remnant_store.chunk_visibility import search_fts_with_scope
from remnant_store.schema import init_db


def _seed_scope_with_chunk(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO deceased_profile (id, name) VALUES ('dp-1', 'Test Person')")
    conn.execute(
        "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
        "VALUES ('scope-a', 'dp-1', 'As child', 'child')"
    )
    conn.execute(
        "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
        "VALUES ('artifact-1', 'dp-1', '/tmp/chat.txt', 'hash-1', 100, 'wechat_txt')"
    )
    conn.execute(
        "INSERT INTO memory_chunk "
        "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, content, token_count) "
        "VALUES ('chunk-1', 'artifact-1', 'scope-a', 'chunk-hash-1', 'conversation_segment', ?, 5)",
        ("dad liked tea every afternoon",),
    )
    conn.commit()


@pytest.fixture
def conn() -> sqlite3.Connection:
    db = init_db(":memory:")
    yield db
    db.close()


def test_remnant_bridge_package_has_module_entrypoint() -> None:
    assert importlib.util.find_spec("remnant_bridge.__main__") is not None


def test_current_ephemeral_token_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMNANT_AUTH_TOKEN", raising=False)

    from remnant_bridge.middleware.auth import EphemeralTokenManager

    manager = EphemeralTokenManager()
    token = manager.get_current_token()

    assert manager.validate_token(token)


def test_ephemeral_token_manager_honors_rust_env_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REMNANT_AUTH_TOKEN", "token-from-rust")

    from remnant_bridge.middleware.auth import EphemeralTokenManager

    manager = EphemeralTokenManager()

    assert manager.get_current_token() == "token-from-rust"
    assert manager.validate_token("token-from-rust")


def test_extract_auth_token_accepts_bearer_and_x_remnant_header() -> None:
    from remnant_bridge.middleware.auth import extract_auth_token

    assert extract_auth_token({"Authorization": "Bearer abc123"}) == "abc123"
    assert extract_auth_token({"X-Remnant-Token": "legacy-token"}) == "legacy-token"
    assert extract_auth_token({"Authorization": "Basic abc123"}) is None


def test_search_fts_with_scope_uses_query_before_visible_ids(
    conn: sqlite3.Connection,
) -> None:
    _seed_scope_with_chunk(conn)

    results = search_fts_with_scope(conn, "tea", "scope-a", top_k=5)

    assert [row["id"] for row in results] == ["chunk-1"]


def test_build_query_response_content_uses_retrieved_evidence() -> None:
    from remnant_bridge.runtime import build_query_response_content

    content = build_query_response_content(
        query="What did dad like?",
        candidates=[
            {
                "id": "chunk-1",
                "content": "dad liked tea every afternoon",
                "combined_score": 0.91,
                "source": "fts",
            }
        ],
    )

    assert "dad liked tea every afternoon" in content
    assert "No matching evidence" not in content


def test_destroy_scope_data_soft_deletes_scope(conn: sqlite3.Connection) -> None:
    _seed_scope_with_chunk(conn)

    from remnant_bridge.runtime import destroy_scope_data

    result = destroy_scope_data(
        conn=conn,
        scope_id="scope-a",
        deletion_type="scope_soft_delete",
        confirm=True,
        actor="user",
    )

    scope_row = conn.execute(
        "SELECT deleted_at, is_active FROM relationship_scope WHERE id = 'scope-a'"
    ).fetchone()

    assert result["status"] == "completed"
    assert result["success"] is True
    assert scope_row["deleted_at"] is not None
    assert scope_row["is_active"] == 0


def test_run_import_pipeline_returns_real_file_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from remnant_bridge import runtime

    sample = tmp_path / "sample.txt"
    sample.write_text("2024-01-01 10:00:00 Dad\nhello\n", encoding="utf-8")

    class FakePipeline:
        def __init__(self, db_path: str) -> None:
            self.db_path = db_path

        def run(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "artifact_id": "artifact-1",
                "raw_count": 1,
                "chunk_count": 1,
                "errors": [],
            }

    monkeypatch.setattr(runtime, "ETLPipeline", FakePipeline)

    response = runtime.run_import_pipeline(
        db_path=":memory:",
        request=SimpleNamespace(
            deceased_profile_id="dp-1",
            file_path=str(sample),
            file_type="wechat_txt",
            scope_id="scope-a",
            metadata={},
        ),
    )

    assert response["artifact_id"] == "artifact-1"
    assert response["file_hash"] == hashlib.sha256(sample.read_bytes()).hexdigest()
    assert response["parse_status"] == "PARSED"
