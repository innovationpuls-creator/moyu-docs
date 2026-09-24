"""Snapshot diff (arch 08 §diff): structural key diff + text-value summaries.

Pure functions over snapshot dicts; text values are compared with difflib's
SequenceMatcher and summarized as insert/delete counts plus the first few hunks
so the API stays bounded.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

MAX_OPERATIONS = 8
MAX_PREVIEW_CHARS = 480


def snapshot_diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    before = before or {}
    after = after or {}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed: list[dict[str, Any]] = []
    for key in sorted(set(before) & set(after)):
        b, a = before[key], after[key]
        if b != a:
            changed.append(
                {
                    "key": key,
                    "kind": (
                        "text" if isinstance(b, str) and isinstance(a, str) else "value"
                    ),
                    "summary": _summarize(b, a),
                }
            )
    return {
        "addedKeys": added,
        "removedKeys": removed,
        "changed": changed,
    }


def _summarize(before: Any, after: Any) -> dict[str, Any]:
    if isinstance(before, str) and isinstance(after, str):
        matcher = SequenceMatcher(None, before, after, autojunk=False)
        operations = [op for op in matcher.get_opcodes() if op[0] != "equal"]
        inserts = sum(j2 - j1 for tag, _, _, j1, j2 in operations if tag == "insert")
        deletes = sum(i2 - i1 for tag, i1, i2, _, _ in operations if tag == "delete")
        replaces = sum(
            max(i2 - i1, j2 - j1)
            for tag, i1, i2, j1, j2 in operations
            if tag == "replace"
        )
        hunks = [
            {
                "tag": tag,
                "from": before[i1:i2][:MAX_PREVIEW_CHARS],
                "to": after[j1:j2][:MAX_PREVIEW_CHARS],
            }
            for tag, i1, i2, j1, j2 in operations[:MAX_OPERATIONS]
        ]
        return {
            "inserts": inserts,
            "deletes": deletes,
            "replaces": replaces,
            "hunks": hunks,
        }
    return {
        "before": str(before)[:MAX_PREVIEW_CHARS],
        "after": str(after)[:MAX_PREVIEW_CHARS],
    }
