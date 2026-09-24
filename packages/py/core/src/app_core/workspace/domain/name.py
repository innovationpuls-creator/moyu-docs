from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceName:
    """A display name and its sibling-collision comparison key."""

    display: str

    def __post_init__(self) -> None:
        if not isinstance(self.display, str):
            raise TypeError("name must be a string")
        if not self.display.strip():
            raise ValueError("name must not be blank")
        if len(self.display) > 120:
            raise ValueError("name must not exceed 120 Unicode code points")
        if any(unicodedata.category(character) == "Cc" for character in self.display):
            raise ValueError("name must not contain control characters")

    @property
    def collision_key(self) -> str:
        """Return the canonical key used for sibling-name comparisons."""
        return unicodedata.normalize("NFC", self.display.strip()).casefold()
