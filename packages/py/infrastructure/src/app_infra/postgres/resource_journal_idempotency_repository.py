from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from app_core.common.exceptions import IdempotencyConflictError
from app_core.resource.domain import JournalOp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresResourceJournalIdempotencyRepository:
    """Fingerprint-bound replay for durable Resource journal appends.

    The compact response stores only the journal receipt, never the Yjs update
    bytes. Claim, journal insert and completion must use the same transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        key: str,
        fingerprint: str,
        operation: Callable[[], Awaitable[JournalOp]],
    ) -> JournalOp:
        storage_key = f"resource-journal:{key}"
        claimed = await self._session.scalar(
            text(
                "INSERT INTO integration.idempotency_records "
                "(idempotency_key,response) VALUES (:key,:response) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {
                "key": storage_key,
                "response": json.dumps(
                    {"fingerprint": fingerprint, "phase": "in_progress"},
                    separators=(",", ":"),
                ),
            },
        )
        if claimed is not None:
            result = await operation()
            payload = {
                "resourceId": str(result.resource_id),
                "journalSeq": result.journal_seq,
                "ownershipEpoch": result.ownership_epoch,
                "updateHash": result.update_hash,
                "acceptedAt": _isoformat(result.accepted_at),
                "durableAt": _isoformat(result.durable_at),
            }
            await self._session.execute(
                text(
                    "UPDATE integration.idempotency_records SET response=:response "
                    "WHERE idempotency_key=:key"
                ),
                {
                    "key": storage_key,
                    "response": json.dumps(
                        {
                            "fingerprint": fingerprint,
                            "phase": "completed",
                            "result": payload,
                        },
                        separators=(",", ":"),
                    ),
                },
            )
            return result

        stored = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": storage_key},
        )
        envelope = json.loads(stored) if stored else None
        if (
            not isinstance(envelope, dict)
            or envelope.get("fingerprint") != fingerprint
            or envelope.get("phase") != "completed"
            or not isinstance(envelope.get("result"), dict)
        ):
            raise IdempotencyConflictError(
                "Idempotency key was used for a different Resource journal update."
            )
        result = envelope["result"]
        return JournalOp(
            resource_id=UUID(result["resourceId"]),
            journal_seq=int(result["journalSeq"]),
            ownership_epoch=int(result["ownershipEpoch"]),
            update_bytes=b"",
            update_hash=str(result["updateHash"]),
            accepted_at=_from_isoformat(result.get("acceptedAt")),
            durable_at=_from_isoformat(result.get("durableAt")),
        )


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_isoformat(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None
