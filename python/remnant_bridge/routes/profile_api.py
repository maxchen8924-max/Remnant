"""Profile API — user-facing deceased profile name resolution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from remnant_bridge.config import DEFAULT_DB_PATH
from remnant_core.models import ProfileResolveRequest, ProfileResolveResponse
from remnant_store.schema import init_db

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.post("/resolve", response_model=ProfileResolveResponse)
async def resolve_profile(request: ProfileResolveRequest) -> ProfileResolveResponse:
    """Resolve a user-facing profile name to the internal deceased_profile ID."""
    profile_name = request.profile_name.strip()
    if not profile_name:
        raise HTTPException(status_code=400, detail="profile_name is required")

    conn = init_db(DEFAULT_DB_PATH)
    try:
        existing = conn.execute(
            """
            SELECT id, name, display_name
            FROM deceased_profile
            WHERE lower(name) = lower(?) AND deleted_at IS NULL
            ORDER BY created_at
            LIMIT 1
            """,
            (profile_name,),
        ).fetchone()

        if existing is not None:
            return ProfileResolveResponse(
                deceased_profile_id=existing["id"],
                profile_name=existing["name"],
                display_name=existing["display_name"],
                created=False,
            )

        profile_id = str(uuid.uuid4())
        now = _utcnow_iso()
        conn.execute(
            """
            INSERT INTO deceased_profile
            (id, name, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (profile_id, profile_name, profile_name, now, now),
        )
        conn.commit()

        return ProfileResolveResponse(
            deceased_profile_id=profile_id,
            profile_name=profile_name,
            display_name=profile_name,
            created=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
