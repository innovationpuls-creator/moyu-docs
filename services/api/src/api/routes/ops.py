"""Operational surface (arch 15): health + process-local metrics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_db_session
from api.infra.metrics import get_metrics, get_shared_metrics

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _db_gauges(session: AsyncSession) -> dict[str, int]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT (SELECT COUNT(*) FROM auth.accounts) AS accounts_total, "
                    "(SELECT COUNT(*) FROM auth.sessions "
                    "WHERE expires_at > now()) AS sessions_active, "
                    "(SELECT COUNT(*) FROM core.resources WHERE lifecycle='Active') "
                    "AS resources_active"
                )
            )
        )
        .mappings()
        .first()
    )
    if rows is None:
        return {}
    return {
        "db.accounts.total": int(rows["accounts_total"]),
        "db.sessions.active": int(rows["sessions_active"]),
        "db.resources.active": int(rows["resources_active"]),
    }


@router.get("/ops/metrics", response_model=dict)
async def ops_metrics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Process counters + DB gauges (arch 14/15 observability baseline;
    cross-instance aggregation is a deployment concern)."""
    snapshot = get_metrics().snapshot()
    snapshot.update(await _db_gauges(session))
    shared = get_shared_metrics()
    if shared is not None:
        snapshot.update(await shared.summarize())
    return snapshot
