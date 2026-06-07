"""Disk-backed Storage adapter — dev loop + tests, not for production.

Keys map onto file paths under ``root``. The adapter sanitizes keys to
keep blob writes inside the configured root: dot-segments are rejected,
absolute paths flattened.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar


class FsStorage:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    async def startup(self, settings: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def shutdown(self) -> None: ...
    async def ready(self) -> bool:
        return self.root.is_dir()

    def _path(self, key: str) -> Path:
        if ".." in key.split("/") or key.startswith("/"):
            msg = f"unsafe key for FsStorage: {key!r}"
            raise ValueError(msg)
        return self.root / key

    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    async def signed_url(self, key: str, *, expires: int = 3600) -> str:
        del expires
        return self._path(key).resolve().as_uri()

    async def list(self, prefix: str = "") -> AsyncIterator[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return
        roots = [base] if base.is_dir() else [base.parent]
        for root in roots:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    yield str(path.relative_to(self.root))


def plugin(settings: Any) -> None:
    from causeway import register

    root = getattr(settings, "fs_storage_root", None)
    if not root:
        return
    register(FsStorage(root=str(root)))


__all__ = ["FsStorage", "plugin"]
