from __future__ import annotations

import types
from collections import deque
from typing import Any, Self

import pytest

import causeway.contrib.s3
import causeway.plugins as plugin_registry
from causeway.contrib.s3 import S3Storage, plugin


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    """Async-context-manager S3 double captures calls + serves stubbed responses."""

    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.presign_calls: list[dict[str, Any]] = []
        self.get_payload = b"hello"
        self.list_pages: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        return {}

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        return {"Body": _FakeBody(self.get_payload)}

    async def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.delete_calls.append(kwargs)
        return {}

    async def generate_presigned_url(
        self, operation: str, *, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        self.presign_calls.append(
            {"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn}
        )
        return f"https://signed/{Params['Bucket']}/{Params['Key']}"

    def get_paginator(self, name: str) -> _FakePaginator:
        return _FakePaginator(self.list_pages)


class _FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages

    def paginate(self, **kwargs: Any) -> _FakePaginator:
        return self

    def __aiter__(self) -> _FakePaginator:
        self._queue = deque(self.pages)
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._queue:
            raise StopAsyncIteration
        return self._queue.popleft()


class _FakeSession:
    def __init__(self, fake_client: _FakeS3Client, **kwargs: Any) -> None:
        self.fake_client = fake_client
        self.kwargs = kwargs

    def client(self, service: str, *, endpoint_url: str | None = None) -> _FakeS3Client:
        assert service == "s3"
        self.fake_client.endpoint_url = endpoint_url
        return self.fake_client


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeS3Client:
    client = _FakeS3Client()

    def factory(**kwargs: Any) -> _FakeSession:
        return _FakeSession(client, **kwargs)

    monkeypatch.setattr(causeway.contrib.s3.aioboto3, "Session", factory)
    return client


async def test_lifecycle_states() -> None:
    s = S3Storage(bucket="b")
    assert await s.ready() is False
    await s.startup(None)
    assert await s.ready() is True
    await s.shutdown()
    assert await s.ready() is False


async def test_put_passes_bucket_key_body(fake_client: _FakeS3Client) -> None:
    s = S3Storage(bucket="my-bucket", region="us-east-1")
    await s.startup(None)
    await s.put("a.txt", b"hi", content_type="text/plain")
    assert fake_client.put_calls == [
        {"Bucket": "my-bucket", "Key": "a.txt", "Body": b"hi", "ContentType": "text/plain"}
    ]


async def test_put_omits_content_type_when_not_provided(fake_client: _FakeS3Client) -> None:
    s = S3Storage(bucket="b")
    await s.startup(None)
    await s.put("a.txt", b"hi")
    assert "ContentType" not in fake_client.put_calls[0]


async def test_get_reads_body(fake_client: _FakeS3Client) -> None:
    fake_client.get_payload = b"payload"
    s = S3Storage(bucket="b")
    await s.startup(None)
    assert await s.get("a.txt") == b"payload"
    assert fake_client.get_calls[0]["Key"] == "a.txt"


async def test_delete_passes_bucket_key(fake_client: _FakeS3Client) -> None:
    s = S3Storage(bucket="b")
    await s.startup(None)
    await s.delete("gone.txt")
    assert fake_client.delete_calls == [{"Bucket": "b", "Key": "gone.txt"}]


async def test_signed_url_uses_presign(fake_client: _FakeS3Client) -> None:
    s = S3Storage(bucket="b")
    await s.startup(None)
    url = await s.signed_url("file", expires=120)
    assert url == "https://signed/b/file"
    assert fake_client.presign_calls[0]["ExpiresIn"] == 120


async def test_list_streams_paginator_keys(fake_client: _FakeS3Client) -> None:
    fake_client.list_pages = [
        {"Contents": [{"Key": "a"}, {"Key": "b"}]},
        {"Contents": [{"Key": "c"}]},
        {},
    ]
    s = S3Storage(bucket="b")
    await s.startup(None)
    keys = [k async for k in s.list(prefix="anything")]
    assert keys == ["a", "b", "c"]


async def test_client_before_startup_raises() -> None:
    s = S3Storage(bucket="b")
    with pytest.raises(RuntimeError, match="used before startup"):
        await s.get("x")


def test_plugin_no_op_without_bucket() -> None:
    plugin(types.SimpleNamespace())
    assert plugin_registry.registered() == []
    plugin(None)
    assert plugin_registry.registered() == []


def test_plugin_registers_with_bucket() -> None:
    plugin(
        types.SimpleNamespace(
            s3_bucket="b",
            s3_region="us-west-2",
            s3_endpoint_url="https://r2",
        ),
    )
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, S3Storage)
    assert adapter.bucket == "b"
    assert adapter.region == "us-west-2"
    assert adapter.endpoint_url == "https://r2"
