"""Op-replay reducers (arch 08 §restore): journal ops -> snapshot state.

The full CRDT merge stays Yjs-deferred; this slice's reducer is the bounded
document model: JSON payloads carrying "text" replace the document text, and
every op contributes its journal_seq so restored states stay traceable.
"""

from __future__ import annotations

import json
from typing import Any

from app_core.resource.domain import JournalOp

MAX_OP_BYTES = 512 * 1024


def decode_op_payload(op: JournalOp) -> dict[str, Any]:
    data = op.update_bytes[:MAX_OP_BYTES]
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    try:
        parsed = json.loads(decoded)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def reduce_ops(state: dict[str, Any], ops: list[JournalOp]) -> dict[str, Any]:
    """Apply journal ops to a snapshot; ops that carry 'text' replace it."""
    for op in ops:
        payload = decode_op_payload(op)
        if "text" in payload and isinstance(payload["text"], str):
            state = {**state, "text": payload["text"]}
        state = {**state, "replayedSeq": op.journal_seq}
    return state
