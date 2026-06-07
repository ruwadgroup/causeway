from __future__ import annotations

import asyncio
import types
from typing import Any

import fakeredis.aioredis
import pytest
from pydantic import SecretStr

import causeway.contrib.redis
import causeway.plugins as plugin_registry
from causeway.contrib.redis import RedisKV, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


@pytest.fixture(autouse=True)
def fake_redis_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``aioredis.from_url`` so RedisKV.startup() backs onto fakeredis."""

    def from_url(url: str, **kwargs: Any) -> Any:
        del url, kwargs
        return fakeredis.aioredis.FakeRedis()

    monkeypatch.setattr(causeway.contrib.redis.aioredis, "from_url", from_url)


async def _booted() -> RedisKV:
    kv = RedisKV(url="redis://test")
    await kv.startup(None)
    return kv


async def test_ready_lifecycle() -> None:
    kv = RedisKV(url="redis://test")
    assert await kv.ready() is False
    await kv.startup(None)
    try:
        assert await kv.ready() is True
    finally:
        await kv.shutdown()
    assert await kv.ready() is False


async def test_get_returns_none_for_missing_key() -> None:
    kv = await _booted()
    try:
        assert await kv.get("nope") is None
    finally:
        await kv.shutdown()


async def test_set_get_delete_roundtrip() -> None:
    kv = await _booted()
    try:
        await kv.set("k", b"v")
        assert await kv.get("k") == b"v"
        await kv.delete("k")
        assert await kv.get("k") is None
    finally:
        await kv.shutdown()


async def test_set_with_ttl_uses_ex() -> None:
    kv = await _booted()
    try:
        await kv.set("k", b"v", ttl=60)
        # fakeredis tracks TTLs; the value is still readable while live.
        assert await kv.get("k") == b"v"
    finally:
        await kv.shutdown()


async def test_incr_creates_and_increments() -> None:
    kv = await _booted()
    try:
        assert await kv.incr("counter") == 1
        assert await kv.incr("counter", by=4) == 5
    finally:
        await kv.shutdown()


async def test_expire_then_get_after_ttl() -> None:
    kv = await _booted()
    try:
        await kv.set("k", b"v")
        await kv.expire("k", ttl=1)
        # fakeredis honors TTL on real time; settle for ttl=1 and a tiny wait.
        await asyncio.sleep(1.1)
        assert await kv.get("k") is None
    finally:
        await kv.shutdown()


async def test_usage_before_startup_raises() -> None:
    kv = RedisKV(url="redis://test")
    with pytest.raises(RuntimeError, match="used before startup"):
        await kv.get("x")


async def test_ready_false_when_ping_blows_up(monkeypatch: pytest.MonkeyPatch) -> None:
    kv = await _booted()
    try:

        async def boom() -> None:
            raise OSError("network down")

        monkeypatch.setattr(kv._c, "ping", boom)
        assert await kv.ready() is False
    finally:
        await kv.shutdown()


def test_plugin_defaults_to_localhost_when_unset() -> None:
    plugin(types.SimpleNamespace())
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, RedisKV)
    assert adapter.url == "redis://localhost"


def test_plugin_reads_redis_url() -> None:
    plugin(types.SimpleNamespace(redis_url="redis://h:6380/3"))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, RedisKV)
    assert adapter.url == "redis://h:6380/3"


def test_plugin_unwraps_secret_url() -> None:
    plugin(types.SimpleNamespace(redis_url=SecretStr("redis://h")))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, RedisKV)
    assert adapter.url == "redis://h"
