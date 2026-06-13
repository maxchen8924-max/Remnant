"""Evidence API tests for trace-based provenance inspection."""

from __future__ import annotations

import sqlite3

from remnant_core.trace import record_retrieval_trace
from remnant_store.schema import init_db


def test_inspect_trace_evidence_returns_redacted_source_metadata(
    client,
    db_path: str,
    monkeypatch,
) -> None:
    from remnant_bridge.routes import evidence_api

    monkeypatch.setattr(evidence_api, "DEFAULT_DB_PATH", db_path)
    conn = init_db(db_path)
    try:
        _seed_trace_evidence(conn)
        trace_id = record_retrieval_trace(
            conn=conn,
            scope_id="scope-a",
            query_text="tea",
            fts_results=[],
            vector_results=[],
            reranked_results=[
                {
                    "id": "chunk-1",
                    "source": "keyword_fallback",
                    "combined_score": 0.35,
                }
            ],
        )
    finally:
        conn.close()

    response = client.get(f"/api/v1/evidence/trace/{trace_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"] == trace_id
    assert payload["evidence_count"] == 1
    evidence = payload["evidences"][0]
    assert evidence["chunk_id"] == "chunk-1"
    assert evidence["source_artifact"]["file_type"] == "universal_chat_json"
    assert evidence["source_artifact"]["source_path_status"] == "redacted"
    assert "file_path" not in evidence["source_artifact"]


def test_inspect_trace_evidence_returns_404_for_missing_trace(
    client,
    db_path: str,
    monkeypatch,
) -> None:
    from remnant_bridge.routes import evidence_api

    monkeypatch.setattr(evidence_api, "DEFAULT_DB_PATH", db_path)
    conn = init_db(db_path)
    conn.close()

    response = client.get("/api/v1/evidence/trace/missing-trace")

    assert response.status_code == 404


def _seed_trace_evidence(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO deceased_profile (id, name) VALUES ('dp-1', 'Test Person')")
    conn.execute(
        "INSERT INTO relationship_scope (id, deceased_profile_id, scope_name, relationship_type) "
        "VALUES ('scope-a', 'dp-1', 'As child', 'child')"
    )
    conn.execute(
        "INSERT INTO source_artifact (id, deceased_profile_id, file_path, file_hash, file_size, file_type) "
        "VALUES ('artifact-1', 'dp-1', '/Users/example/private-chat.json', 'hash-1', 100, 'universal_chat_json')"
    )
    conn.execute(
        "INSERT INTO memory_chunk "
        "(id, source_artifact_id, relationship_scope_id, chunk_hash, chunk_type, content, token_count) "
        "VALUES ('chunk-1', 'artifact-1', 'scope-a', 'chunk-hash-1', 'conversation_segment', ?, 5)",
        ("dad liked tea every afternoon",),
    )
    conn.commit()
