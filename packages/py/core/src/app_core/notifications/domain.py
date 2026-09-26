from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

_MENTION_TOKEN = re.compile(r"@([\w.+-]+@[\w.-]+)")


class NotificationError(Exception):
    pass


@dataclass(frozen=True)
class Notification:
    notification_id: UUID
    account_id: UUID
    kind: str
    payload: dict
    created_at: datetime | None = None
    read_at: datetime | None = None
    target_ref: dict | None = None
    source_event_id: UUID | None = None


def extract_mentioned_emails(body: str) -> list[str]:
    """@具体用户 (arch 17 §2): parse @email mention tokens, de-duplicated."""
    seen: list[str] = []
    for match in _MENTION_TOKEN.finditer(body):
        email = match.group(1).lower()
        if email not in seen:
            seen.append(email)
    return seen
