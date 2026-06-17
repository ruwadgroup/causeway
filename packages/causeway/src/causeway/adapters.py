from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar


class _Ready:
    contract_version: ClassVar[str] = "v1.0"

    async def startup(self, settings: Any) -> None: ...

    async def ready(self) -> bool:
        return True


class LocalStorage(_Ready):
    """In-memory blob storage."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def shutdown(self) -> None:
        self._blobs.clear()

    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None:
        del content_type
        self._blobs[key] = body

    async def get(self, key: str) -> bytes:
        try:
            return self._blobs[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        self._blobs.pop(key, None)

    async def signed_url(self, key: str, *, expires: int = 3600) -> str:
        del expires
        return f"memory://{key}"

    async def list(self, prefix: str = "") -> AsyncIterator[str]:
        for k in sorted(self._blobs):
            if k.startswith(prefix):
                yield k


class MemoryKV(_Ready):
    """In-memory key-value store with TTL."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._exp: dict[str, float] = {}

    async def shutdown(self) -> None:
        self._data.clear()
        self._exp.clear()

    def _expired(self, key: str) -> bool:
        exp = self._exp.get(key)
        if exp is not None and exp <= time.monotonic():
            self._data.pop(key, None)
            self._exp.pop(key, None)
            return True
        return False

    async def get(self, key: str) -> bytes | None:
        if self._expired(key):
            return None
        return self._data.get(key)

    async def set(self, key: str, value: bytes, *, ttl: int | None = None) -> None:
        self._data[key] = value
        if ttl is not None:
            self._exp[key] = time.monotonic() + ttl
        else:
            self._exp.pop(key, None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._exp.pop(key, None)

    async def incr(self, key: str, by: int = 1) -> int:
        cur = int(self._data.get(key, b"0").decode() or "0")
        cur += by
        self._data[key] = str(cur).encode()
        return cur

    async def expire(self, key: str, ttl: int) -> None:
        if key in self._data:
            self._exp[key] = time.monotonic() + ttl


class MemoryLimiter(_Ready):
    """Token-bucket limiter."""

    def __init__(self, *, capacity: int = 100, refill_per_sec: float = 100 / 60) -> None:
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._buckets: dict[str, tuple[float, float]] = {}

    async def shutdown(self) -> None:
        self._buckets.clear()

    def _refill(self, key: str) -> float:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(self.capacity), now))
        tokens = min(float(self.capacity), tokens + (now - last) * self.refill_per_sec)
        self._buckets[key] = (tokens, now)
        return tokens

    async def acquire(self, key: str, cost: int = 1) -> bool:
        tokens = self._refill(key)
        if tokens < cost:
            return False
        self._buckets[key] = (tokens - cost, self._buckets[key][1])
        return True

    async def peek(self, key: str) -> int:
        return int(self._refill(key))

    async def reset(self, key: str) -> None:
        self._buckets.pop(key, None)


class StaticFlags(_Ready):
    """Static flag map loaded from ``Settings.feature_flags``."""

    def __init__(self, flags: dict[str, bool] | None = None) -> None:
        self._flags = dict(flags or {})

    async def startup(self, settings: Any) -> None:
        flags = getattr(settings, "feature_flags", None)
        if isinstance(flags, dict):
            self._flags.update({str(k): bool(v) for k, v in flags.items()})

    async def shutdown(self) -> None: ...

    async def is_on(self, flag: str, user: str | None = None) -> bool:
        del user
        return bool(self._flags.get(flag, False))

    async def variant(self, flag: str, user: str | None = None) -> str | None:
        del user
        return None

    async def refresh(self) -> None: ...


class NullSink(_Ready):
    """Discards metrics."""

    async def shutdown(self) -> None: ...

    def counter(self, name: str, value: float = 1.0, **tags: str) -> None:
        del name, value, tags

    def gauge(self, name: str, value: float, **tags: str) -> None:
        del name, value, tags

    def histogram(self, name: str, value: float, **tags: str) -> None:
        del name, value, tags

    @contextlib.asynccontextmanager
    async def timer(self, name: str, **tags: str) -> AsyncIterator[None]:
        del name, tags
        yield


class NullScanner(_Ready):
    """No-op blob scanner."""

    async def shutdown(self) -> None: ...

    async def scan(self, stream: AsyncIterator[bytes]) -> bool:
        async for _ in stream:
            pass
        return True


__all__ = [
    "LocalStorage",
    "MemoryKV",
    "MemoryLimiter",
    "NullScanner",
    "NullSink",
    "StaticFlags",
]
