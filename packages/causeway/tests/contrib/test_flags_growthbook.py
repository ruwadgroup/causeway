from __future__ import annotations

import json
import types

import httpx
import pytest

import causeway.plugins as plugin_registry
from causeway.contrib.growthbook import GrowthBookFlags, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


def _features_transport(features: dict[str, dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/features/CK")
        return httpx.Response(200, json={"features": features})

    return httpx.MockTransport(handler)


@pytest.fixture
def patch_httpx_client(monkeypatch: pytest.MonkeyPatch):
    """Yield a function that swaps ``httpx.AsyncClient`` with a transport-backed double."""

    def _patch(features: dict[str, dict[str, object]]) -> None:
        original = httpx.AsyncClient

        def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
            return original(transport=_features_transport(features))

        monkeypatch.setattr("causeway.contrib.growthbook.httpx.AsyncClient", factory)

    return _patch


async def test_refresh_pulls_features_and_marks_ready(patch_httpx_client) -> None:
    patch_httpx_client({"hello": {"defaultValue": True}})
    flags = GrowthBookFlags(api_host="https://gb", client_key="CK")

    assert await flags.ready() is False
    await flags.startup(None)
    assert await flags.ready() is True
    assert await flags.is_on("hello") is True


async def test_is_on_falls_back_to_false_for_unknown(patch_httpx_client) -> None:
    patch_httpx_client({"hello": {"defaultValue": True}})
    flags = GrowthBookFlags(api_host="https://gb/", client_key="CK")
    await flags.startup(None)
    assert await flags.is_on("missing") is False


async def test_variant_returns_str_or_none(patch_httpx_client) -> None:
    patch_httpx_client(
        {
            "color": {"defaultValue": "blue"},
            "off": {"defaultValue": None},
        }
    )
    flags = GrowthBookFlags(api_host="https://gb", client_key="CK")
    await flags.startup(None)
    assert await flags.variant("color", user="u1") == "blue"
    assert await flags.variant("off") is None


async def test_shutdown_clears_features(patch_httpx_client) -> None:
    patch_httpx_client({"x": {"defaultValue": True}})
    flags = GrowthBookFlags(api_host="https://gb", client_key="CK")
    await flags.startup(None)
    await flags.shutdown()
    assert await flags.ready() is False


async def test_refresh_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(lambda req: httpx.Response(500, text="bad")))

    monkeypatch.setattr("causeway.contrib.growthbook.httpx.AsyncClient", factory)
    flags = GrowthBookFlags(api_host="https://gb", client_key="CK")
    with pytest.raises(httpx.HTTPStatusError):
        await flags.refresh()


def test_plugin_no_op_when_settings_missing() -> None:
    plugin(types.SimpleNamespace())
    assert plugin_registry.registered() == []
    plugin(types.SimpleNamespace(growthbook_api_host="https://x"))
    assert plugin_registry.registered() == []


def test_plugin_registers_when_both_present() -> None:
    plugin(
        types.SimpleNamespace(
            growthbook_api_host="https://x",
            growthbook_client_key="CK",
        ),
    )
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, GrowthBookFlags)
    assert adapter.api_host == "https://x"
    assert adapter.client_key == "CK"


def test_features_serializable() -> None:
    """Sanity-check on test fixture shape — keeps the transport handler honest."""
    body = json.dumps({"features": {"x": {"defaultValue": True}}})
    assert "features" in json.loads(body)
