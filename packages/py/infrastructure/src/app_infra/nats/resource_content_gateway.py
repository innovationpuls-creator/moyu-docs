from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

from app_core.resource.domain import (
    JournalSequenceConflictError,
    ResourceContent,
    ResourceContentMutation,
)
from app_core.resource.ports import ResourceContentPort
from nats.aio.client import Client as NATS

READ_SUBJECT = "dom.resource.content.read.v1"
REPLACE_SUBJECT = "dom.resource.content.replace.v1"
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")


class ResourceContentGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class NatsResourceContentGateway(ResourceContentPort):
    """Python Core adapter for the Realtime-owned Resource content commands."""

    def __init__(self, client: NATS | None = None, *, nats_url: str = NATS_URL) -> None:
        self._client = client
        self._owns_client = client is None
        self._nats_url = nats_url
        self._lock = asyncio.Lock()

    async def read(
        self, resource_id: UUID, *, at_journal_seq: int | None = None
    ) -> ResourceContent:
        request: dict[str, Any] = {"resourceId": str(resource_id)}
        if at_journal_seq is not None:
            request["atJournalSeq"] = at_journal_seq
        response = await self._request(READ_SUBJECT, request)
        snapshot = response.get("snapshot")
        journal_seq = response.get("journalSeq")
        if not isinstance(snapshot, dict) or not isinstance(journal_seq, int):
            raise ResourceContentGatewayError(
                "RESOURCE_CONTENT_UNAVAILABLE",
                "Realtime returned an invalid content response",
            )
        return ResourceContent(snapshot=snapshot, journal_seq=journal_seq)

    async def replace(
        self,
        resource_id: UUID,
        snapshot: dict,
        *,
        operation_id: UUID,
        created_by: UUID | None,
        reason: str,
        expected_journal_seq: int | None = None,
        restore_target_seq: int | None = None,
    ) -> ResourceContentMutation:
        request: dict[str, Any] = {
            "resourceId": str(resource_id),
            "operationId": str(operation_id),
            "createdBy": str(created_by) if created_by is not None else None,
            "reason": reason,
            "snapshot": snapshot,
        }
        if expected_journal_seq is not None:
            request["expectedJournalSeq"] = expected_journal_seq
        if restore_target_seq is not None:
            request["restoreTargetSeq"] = restore_target_seq
        response = await self._request(REPLACE_SUBJECT, request)
        journal_seq = response.get("journalSeq")
        if not isinstance(journal_seq, int):
            raise ResourceContentGatewayError(
                "RESOURCE_CONTENT_UNAVAILABLE",
                "Realtime returned an invalid mutation receipt",
            )
        return ResourceContentMutation(journal_seq=journal_seq)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None

    async def _request(self, subject: str, body: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        try:
            message = await client.request(
                subject,
                json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
                timeout=10,
            )
        except Exception as exc:
            raise ResourceContentGatewayError(
                "RESOURCE_CONTENT_UNAVAILABLE",
                "Realtime content service is unavailable",
            ) from exc
        try:
            response = json.loads(message.data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResourceContentGatewayError(
                "RESOURCE_CONTENT_UNAVAILABLE", "Realtime returned an invalid response"
            ) from exc
        if not isinstance(response, dict):
            raise ResourceContentGatewayError(
                "RESOURCE_CONTENT_UNAVAILABLE", "Realtime returned an invalid response"
            )
        error = response.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            if code == "RESOURCE_JOURNAL_SEQUENCE_CONFLICT":
                next_seq = error.get("nextJournalSeq")
                raise JournalSequenceConflictError(
                    next_seq if isinstance(next_seq, int) else 0
                )
            if code == "RESOURCE_NOT_FOUND":
                raise LookupError("resource content not found")
            raise ResourceContentGatewayError(
                code if isinstance(code, str) else "RESOURCE_CONTENT_UNAVAILABLE",
                message
                if isinstance(message, str)
                else "Realtime content command failed",
            )
        return response

    async def _get_client(self) -> NATS:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                client = NATS()
                try:
                    await client.connect(self._nats_url, connect_timeout=2)
                except Exception as exc:
                    raise ResourceContentGatewayError(
                        "RESOURCE_CONTENT_UNAVAILABLE",
                        "Realtime content service is unavailable",
                    ) from exc
                self._client = client
        assert self._client is not None
        return self._client
