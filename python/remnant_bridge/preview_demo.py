"""Runnable preview demo for the Remnant architecture preview."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from remnant_bridge.runtime import destroy_scope_data, run_import_pipeline, run_query_retrieval
from remnant_store.schema import init_db
from remnant_store.scope_deletion import verify_raw_data_integrity


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_dataset"


def run_preview_demo(
    db_path: str | Path,
    fixture_dir: str | Path = DEFAULT_FIXTURE_DIR,
    query: str = "西湖",
) -> dict[str, Any]:
    """Run the local preview flow: seed, import, query, soft-delete, verify."""
    db_path = Path(db_path)
    fixture_dir = Path(fixture_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = init_db(db_path)
    try:
        profile = _seed_profile_and_scope(conn, fixture_dir / "sample_profile.json")
        import_result = run_import_pipeline(
            db_path=str(db_path),
            request=SimpleNamespace(
                deceased_profile_id=profile["profile_id"],
                file_path=str(fixture_dir / "wechat_sample.txt"),
                file_type="wechat_txt",
                scope_id=profile["scope_id"],
                metadata={},
            ),
        )
        query_result = run_query_retrieval(
            conn=conn,
            scope_id=profile["scope_id"],
            query=query,
            top_k=5,
        )
        delete_result = destroy_scope_data(
            conn=conn,
            scope_id=profile["scope_id"],
            deletion_type="scope_soft_delete",
            confirm=True,
            actor="preview_demo",
        )
        integrity = verify_raw_data_integrity(conn, profile["profile_id"])

        return {
            "profile": {
                "id": profile["profile_id"],
                "name": profile["name"],
            },
            "scope": {
                "id": profile["scope_id"],
                "name": profile["scope_name"],
            },
            "import": import_result,
            "query": query_result,
            "delete": delete_result,
            "raw_data_integrity": integrity,
            "db_path": str(db_path),
        }
    finally:
        conn.close()


def format_preview_summary(result: dict[str, Any]) -> str:
    """Format preview demo output for terminal users."""
    return "\n".join(
        [
            "Remnant preview demo",
            f"Profile: {result['profile']['name']} ({result['profile']['id']})",
            f"Scope: {result['scope']['name']} ({result['scope']['id']})",
            (
                "Import: "
                f"{result['import']['parse_status']}, "
                f"messages={result['import']['message_count']}, "
                f"chunks={result['import']['chunk_count']}"
            ),
            f"Query: trace={result['query'].get('retrieval_trace_id')}",
            _indent(str(result["query"].get("content", ""))),
            (
                "Soft delete: "
                f"{result['delete']['status']}, "
                f"raw_messages={result['raw_data_integrity']['raw_message_count']}"
            ),
            f"Database: {result['db_path']}",
        ]
    )


def _seed_profile_and_scope(
    conn: sqlite3.Connection,
    profile_path: Path,
) -> dict[str, str]:
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_id = str(uuid.uuid4())
    scope_id = str(uuid.uuid4())
    name = str(data["name"])
    scope_name = "preview: child scope"

    conn.execute(
        """INSERT INTO deceased_profile
        (id, name, birth_date, death_date, bio)
        VALUES (?, ?, ?, ?, ?)""",
        (
            profile_id,
            name,
            data.get("birth_date"),
            data.get("death_date"),
            data.get("description"),
        ),
    )
    conn.execute(
        """INSERT INTO relationship_scope
        (id, deceased_profile_id, scope_name, relationship_type, scope_description)
        VALUES (?, ?, ?, ?, ?)""",
        (
            scope_id,
            profile_id,
            scope_name,
            "child",
            "Preview relationship scope for the open-source runnable demo.",
        ),
    )
    conn.commit()

    return {
        "profile_id": profile_id,
        "scope_id": scope_id,
        "name": name,
        "scope_name": scope_name,
    }


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in text.splitlines())
