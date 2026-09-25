from __future__ import annotations

from uuid import RFC_4122

from app_core.common.ids import new_uuid7


def test_new_uuid7_uses_canonical_version_and_variant() -> None:
    value = new_uuid7()

    assert value.version == 7
    assert value.variant == RFC_4122
