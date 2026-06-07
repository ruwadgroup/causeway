from __future__ import annotations

import types
from typing import Any

import pytest
from pydantic import SecretStr

import causeway.plugins as plugin_registry
from causeway.contrib.sentry import SentryObserver, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


@pytest.fixture
def fake_sentry(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"init_kwargs": None, "closed": False, "client": None}

    class _Client:
        def close(self) -> None:
            state["closed"] = True

    def fake_init(**kwargs: Any) -> None:
        state["init_kwargs"] = kwargs
        state["client"] = _Client()

    def fake_get_client() -> Any:
        return state["client"]

    monkeypatch.setattr("causeway.contrib.sentry.sentry_sdk.init", fake_init)
    monkeypatch.setattr("causeway.contrib.sentry.sentry_sdk.get_client", fake_get_client)
    return state


async def test_startup_calls_sentry_init(fake_sentry: dict[str, Any]) -> None:
    obs = SentryObserver(dsn="https://x@sentry/1", environment="staging", traces_sample_rate=0.5)
    await obs.startup(None)

    kw = fake_sentry["init_kwargs"]
    assert kw is not None
    assert kw["dsn"] == "https://x@sentry/1"
    assert kw["environment"] == "staging"
    assert kw["traces_sample_rate"] == 0.5
    integration_names = [type(i).__name__ for i in kw["integrations"]]
    assert "StarletteIntegration" in integration_names
    assert "AsyncioIntegration" in integration_names


async def test_ready_then_shutdown_closes_client(fake_sentry: dict[str, Any]) -> None:
    obs = SentryObserver(dsn="dsn")
    await obs.startup(None)
    assert await obs.ready() is True
    await obs.shutdown()
    assert fake_sentry["closed"] is True


async def test_ready_false_before_startup(fake_sentry: dict[str, Any]) -> None:
    obs = SentryObserver(dsn="dsn")
    assert await obs.ready() is False


def test_plugin_no_op_without_dsn() -> None:
    plugin(types.SimpleNamespace())
    assert plugin_registry.registered() == []


def test_plugin_unwraps_secret_dsn(fake_sentry: dict[str, Any]) -> None:
    plugin(types.SimpleNamespace(sentry_dsn=SecretStr("https://k@h/2")))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, SentryObserver)
    assert adapter.dsn == "https://k@h/2"


def test_plugin_pulls_env_from_environment(
    fake_sentry: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAUSEWAY_ENV", "prod")
    plugin(types.SimpleNamespace(sentry_dsn="dsn"))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, SentryObserver)
    assert adapter.environment == "prod"
