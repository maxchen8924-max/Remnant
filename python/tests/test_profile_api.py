"""Profile API tests for user-facing deceased profile names."""

from __future__ import annotations

import sqlite3


def test_resolve_profile_creates_named_profile(client, db_path, monkeypatch) -> None:
    from remnant_bridge.routes import profile_api

    monkeypatch.setattr(profile_api, "DEFAULT_DB_PATH", db_path)

    response = client.post(
        "/api/v1/profile/resolve",
        json={"profile_name": "李雷"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_name"] == "李雷"
    assert payload["created"] is True
    assert payload["deceased_profile_id"]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, name FROM deceased_profile WHERE id = ?",
            (payload["deceased_profile_id"],),
        ).fetchone()

    assert row == (payload["deceased_profile_id"], "李雷")


def test_resolve_profile_reuses_existing_name(client, db_path, monkeypatch) -> None:
    from remnant_bridge.routes import profile_api

    monkeypatch.setattr(profile_api, "DEFAULT_DB_PATH", db_path)

    first = client.post(
        "/api/v1/profile/resolve",
        json={"profile_name": "Alice Chen"},
    )
    second = client.post(
        "/api/v1/profile/resolve",
        json={"profile_name": "Alice Chen"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["deceased_profile_id"] == first.json()["deceased_profile_id"]

    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM deceased_profile WHERE name = 'Alice Chen'",
        ).fetchone()[0]

    assert count == 1
