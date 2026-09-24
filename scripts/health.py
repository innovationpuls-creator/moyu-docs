#!/usr/bin/env python3
"""Cross-service health probe (arch 15 §readiness): PostgreSQL, Valkey, NATS,
the API, and the Realtime gateway. Prints component status as JSON and exits
non-zero when any required component is unreachable.

Required components come from env: DATABASE_URL, VALKEY_URL, NATS_URL,
API_PORT (optional), REALTIME_PORT (optional).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import redis.asyncio as aioredis
import sqlalchemy as sa


async def _postgres(url: str) -> tuple[bool, str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - failure path
        return False, str(exc)[:200]
    finally:
        engine.dispose()


async def _valkey(url: str) -> tuple[bool, str]:
    client = aioredis.from_url(url)
    try:
        pong = await client.ping()
        return bool(pong), "ok"
    except Exception as exc:  # pragma: no cover - failure path
        return False, str(exc)[:200]
    finally:
        await client.aclose()


async def _http(url: str, path: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url + path)
        return response.status_code == 200, f"http {response.status_code}"
    except Exception as exc:  # pragma: no cover - failure path
        return False, str(exc)[:200]


async def _nats(url: str) -> tuple[bool, str]:
    try:
        import nats

        nc = await nats.connect(url, connect_timeout=2)
        await nc.flush()
        await nc.close()
        return True, "ok"
    except Exception as exc:  # pragma: no cover - failure path
        return False, str(exc)[:200]


async def check() -> dict[str, object]:
    components: dict[str, tuple[bool, str]] = {}
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        components["postgres"] = (False, "DATABASE_URL not set")
    else:
        components["postgres"] = await _postgres(database_url)
    valkey_url = os.environ.get("VALKEY_URL", "")
    if not valkey_url:
        components["valkey"] = (False, "VALKEY_URL not set")
    else:
        components["valkey"] = await _valkey(valkey_url)
    nats_url = os.environ.get("NATS_URL", "")
    components["nats"] = (
        await _nats(nats_url)
        if nats_url
        else (False, "NATS_URL not set; set NATS_SKIP=1 to skip")
    )
    if os.environ.get("NATS_SKIP"):
        components["nats"] = (True, "skipped")
    api_port = os.environ.get("API_PORT", "")
    if api_port:
        components["api"] = await _http(f"http://127.0.0.1:{api_port}", "/healthz")
    realtime_port = os.environ.get("REALTIME_PORT", "")
    if realtime_port:
        components["realtime"] = await _http(
            f"http://127.0.0.1:{realtime_port}", "/healthz"
        )
    report = {
        name: {"ok": ok, "detail": detail} for name, (ok, detail) in components.items()
    }
    all_ok = all(ok for ok, _ in components.values())
    return {"allOk": all_ok, "components": report}


async def _main() -> None:
    report = await check()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["allOk"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
