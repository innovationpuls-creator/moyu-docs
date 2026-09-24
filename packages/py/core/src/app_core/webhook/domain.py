from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app_core.integrations.domain import sign


class WebhookNotFound(Exception):
    pass


@dataclass(frozen=True)
class WebhookEvent:
    kind: str
    workspace_id: str
    occurred_at: datetime

    def payload_bytes(self) -> bytes:
        body = {
            "event": self.kind,
            "workspaceId": self.workspace_id,
            "occurredAt": self.occurred_at.isoformat(),
        }
        return json.dumps(body, separators=(",", ":")).encode()


@dataclass(frozen=True)
class WebhookDelivery:
    delivered: bool
    status_code: int


def signed_headers(
    event: WebhookEvent, secret_key_hex: str
) -> tuple[bytes, dict[str, str]]:
    payload = event.payload_bytes()
    now = datetime.now(timezone.utc)
    signature = sign(payload, now, bytes.fromhex(secret_key_hex))
    return payload, {
        "X-Dom-Signature": signature,
        "X-Dom-Timestamp": str(int(now.timestamp())),
        "Content-Type": "application/json",
    }
