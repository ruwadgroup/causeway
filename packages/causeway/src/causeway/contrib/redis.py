"""Redis KV adapter for :class:`causeway.contracts.KV`."""

from __future__ import annotations

import inspect
from typing import Any, ClassVar, cast

import redis.asyncio as aioredis


class RedisKV:
    """Async Redis client wrapped to match Causeway's KV protocol."""

    contract_version: ClassVar[str] = "v1.0"

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: aioredis.Redis | None = None

    async def startup(self, settings: Any) -> None:
        self._client = aioredis.from_url(self.url, decode_responses=False)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def ready(self) -> bool:
        if self._client is None:
            return False
        try:
            pinged = self._client.ping()
            if inspect.isawaitable(pinged):
                await pinged
        except Exception:
            return False
        return True

    @property
    def _c(self) -> aioredis.Redis:
        if self._client is None:
            msg = "RedisKV used before startup()"
            raise RuntimeError(msg)
        return self._client

    async def get(self, key: str) -> bytes | None:
        return cast(bytes | None, await self._c.get(key))

    async def set(self, key: str, value: bytes, *, ttl: int | None = None) -> None:
        if ttl is None:
            await self._c.set(key, value)
        else:
            await self._c.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._c.delete(key)

    async def incr(self, key: str, by: int = 1) -> int:
        return int(await self._c.incrby(key, by))

    async def expire(self, key: str, ttl: int) -> None:
        await self._c.expire(key, ttl)


def plugin(settings: Any) -> None:
    from causeway import register

    url = getattr(settings, "redis_url", None) or "redis://localhost"
    if hasattr(url, "get_secret_value"):
        url = url.get_secret_value()
    register(RedisKV(url=str(url)))


__all__ = ["RedisKV", "plugin"]
