"""Local-disk asset provider (arch 10 provider abstraction)."""

from __future__ import annotations

from pathlib import Path


class LocalDiskAssetStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, storage_key: str) -> Path:
        target = (self._root / storage_key).resolve()
        if not str(target).startswith(str(self._root.resolve())):
            raise ValueError("asset key escapes store root")
        return target

    async def put(self, storage_key: str, data: bytes) -> None:
        target = self._path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    async def get(self, storage_key: str) -> bytes:
        return self._path(storage_key).read_bytes()

    async def delete(self, storage_key: str) -> None:
        self._path(storage_key).unlink(missing_ok=True)
