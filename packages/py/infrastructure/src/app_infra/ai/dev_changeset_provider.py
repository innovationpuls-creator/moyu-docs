"""Dev AI adapter (arch 12 port): deterministic, log-delivered; a real model
provider replaces this behind the same port (never in production)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("dom.ai.dev")


class DevChangeProvider:
    async def propose(
        self,
        resource_id: UUID,
        instruction: str,
        *,
        snapshot: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        logger.info(
            "dev-ai propose resource=%s instruction=%s",
            resource_id,
            instruction,
        )
        return [
            {
                "op": "summary-insert",
                "value": f"AI（开发适配器）: {instruction}",
            }
        ]
