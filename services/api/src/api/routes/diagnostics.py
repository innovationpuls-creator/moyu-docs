"""Readiness diagnostics (arch 14 §2): dependency checks for DB / Valkey /
NATS. Liveness stays on /healthz; this is the readiness surface (booleans
only — no internal detail leaks)."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from app_infra.postgres.engine import engine
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from redis.asyncio import Redis

from api.dependencies.auth import get_valkey

router = APIRouter()


class DependencyCheck(BaseModel):
    name: str
    ok: bool
    latencyMs: float | None = None


class DiagnosticsResponse(BaseModel):
    status: str
    checks: list[DependencyCheck]


async def _check_postgres() -> DependencyCheck:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(3):
            connection = await engine.connect()
            try:
                await connection.execute(__import__("sqlalchemy").text("SELECT 1"))
            finally:
                await connection.close()
        return DependencyCheck(
            name="postgres",
            ok=True,
            latencyMs=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception:
        return DependencyCheck(name="postgres", ok=False)


async def _check_valkey(valkey: Redis) -> DependencyCheck:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(3):
            pong = await valkey.ping()
        return DependencyCheck(
            name="valkey",
            ok=bool(pong),
            latencyMs=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception:
        return DependencyCheck(name="valkey", ok=False)


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics(
    request: Request,
    valkey: Annotated[Redis, Depends(get_valkey)],
) -> DiagnosticsResponse:
    checks = [
        await _check_postgres(),
        await _check_valkey(valkey),
    ]
    status = "ok" if all(c.ok for c in checks) else "degraded"
    return DiagnosticsResponse(status=status, checks=checks)
