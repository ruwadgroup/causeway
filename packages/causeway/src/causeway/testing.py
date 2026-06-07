"""Testing kit.

:class:`TestApp` is the public surface — every other helper is built on top.
A test mounts the app, exercises it with httpx, and asserts on responses.
DI overrides go through the same scope machinery as production code, so
there is no separate "test injection" concept to learn.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from causeway._runtime import App

if TYPE_CHECKING:
    from causeway.errors import HttpErrorFormatter


class TestApp:
    """Wraps a Causeway app for in-process testing.

    Build one of these per test (or per fixture). The class exposes ``.get``
    / ``.post`` / ``.put`` / ``.patch`` / ``.delete`` that proxy to an
    ``httpx.AsyncClient`` over an ``ASGITransport`` — no network, no
    uvicorn, just direct ASGI dispatch.
    """

    # pytest's auto-discovery treats classes prefixed with "Test" as test
    # classes. Disable that so our public class doesn't trip the collector.
    __test__ = False

    def __init__(self, app: App) -> None:
        self._app = app
        self._overrides: dict[Callable[..., Any], Callable[..., Any]] = {}

    @classmethod
    def from_routes(
        cls,
        routes_root: str | Path,
        *,
        settings: Any = None,
        diagnostics: bool = False,
        request_id: bool = False,
        error_formatter: HttpErrorFormatter | None = None,
    ) -> TestApp:
        """Discover ``routes_root`` and wire a fresh app for in-process testing.

        Routes through :func:`causeway.app.create_app` so class middleware
        declared in ``_middleware.py`` files actually fires — without that
        wrap, inline scenarios silently skip permission guards, idempotency
        checks, and any other class-based ``Middleware`` the routes declare.

        ``diagnostics`` and ``request_id`` default off so scenarios don't
        accidentally test the dev surface; flip them on when exercising
        ``/__causeway`` or request-id flow directly.
        """
        from causeway.app import create_app

        app = create_app(
            routes_root,
            settings=settings,
            diagnostics=diagnostics,
            request_id=request_id,
            error_renderer_=True,
            error_formatter=error_formatter,
        )
        return cls(app)

    @classmethod
    def wrap(cls, app: App) -> TestApp:
        """Wrap an existing ``causeway.App`` — useful for app-factory patterns."""
        return cls(app)

    @asynccontextmanager
    async def override(
        self,
        provider: Callable[..., Any],
        replacement: Callable[..., Any],
    ) -> AsyncIterator[None]:
        """Swap a DI provider for the duration of a block.

        Replacements honor the same shape as the original (sync function,
        async function, sync generator, async generator). The original is
        restored on exit even if the block raises.
        """
        original_code = provider.__code__
        provider.__code__ = replacement.__code__
        try:
            yield
        finally:
            provider.__code__ = original_code

    @asynccontextmanager
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        async with self.client() as c:
            return await c.request(method, path, **kwargs)

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)


@asynccontextmanager
async def stub(provider: Callable[..., Any], value: Any) -> AsyncIterator[None]:
    """Replace a provider with one that returns ``value``.

    Convenience wrapper around :meth:`TestApp.override` for the common case
    of "I just want this dependency to be the literal ``value``".
    """

    async def constant() -> Any:
        return value

    original_code = provider.__code__
    provider.__code__ = constant.__code__
    try:
        yield
    finally:
        provider.__code__ = original_code


from dataclasses import dataclass as _dataclass  # noqa: E402

from causeway._testing import (  # noqa: E402 - inline-scenario surface
    Expectation,
    Response,
    ScenarioAssertionError,
    SnapshotValue,
    expect,
    scenario,
    snapshot,
)
from causeway.tasks import tasks_eager  # noqa: E402 - module re-export

if TYPE_CHECKING:
    from causeway.events import Event


@_dataclass(slots=True)
class CapturedDelivery:
    """One record from :func:`captured_webhooks`. Mirrors what would have
    been enqueued for outbound delivery."""

    subscriber_id: str
    url: str
    event_name: str
    event: Any
    where: dict[str, Any] | None


@asynccontextmanager
async def captured(*event_classes: type[Event]) -> AsyncIterator[list[Any]]:
    """Capture every instance of the given event classes emitted in the block.

    Short-circuits the event's in-process listeners — they don't fire while
    capture is active — so tests can assert on what would have been emitted
    without triggering side effects. Webhook fan-out is not suppressed
    here; pair with :func:`captured_webhooks` for the full short-circuit.

    Example::

        async with captured(CustomerCreated) as events:
            await client.post("/customers", json={...})
        assert events == [CustomerCreated(id=..., email="a@b")]
    """
    out: list[Any] = []
    saved: dict[Any, list[Any]] = {}
    for cls in event_classes:
        saved[cls] = list(cls._listeners)
        cls._listeners.clear()

        async def _capture(p: Any, _out: list[Any] = out) -> None:
            _out.append(p)

        cls._listeners.append(_capture)
    try:
        yield out
    finally:
        for cls, originals in saved.items():
            cls._listeners[:] = originals


@asynccontextmanager
async def captured_webhooks() -> AsyncIterator[list[CapturedDelivery]]:
    """Capture every webhook delivery that would have been enqueued.

    Short-circuits the task adapter — no ``_deliver.enqueue`` runs, no HTTP
    is attempted. Returned list is one :class:`CapturedDelivery` per
    matching subscriber per emit (static + dynamic, ``where`` filter applied).

    Example::

        async with captured_webhooks() as deliveries:
            await client.post("/customers", json={...})
        assert len(deliveries) == 1
        assert deliveries[0].url == "https://slack.example"
    """
    import causeway.events as _events
    import causeway.webhooks as _webhooks

    out: list[CapturedDelivery] = []
    saved = _events._fanout_impl

    async def _capture(event: Any) -> list[str]:
        cls = type(event)
        for sub in cls._subscribers:
            if not _webhooks._matches(event, sub.where):
                continue
            out.append(
                CapturedDelivery(
                    subscriber_id=sub.id,
                    url=sub.url,
                    event_name=cls.wire_name,
                    event=event,
                    where=sub.where,
                )
            )
        store = _webhooks.active_store()
        if store is not None:
            async for stored in store.subscribers_for(cls.wire_name):
                if not _webhooks._matches(event, stored.where):
                    continue
                out.append(
                    CapturedDelivery(
                        subscriber_id=stored.id,
                        url=stored.url,
                        event_name=cls.wire_name,
                        event=event,
                        where=stored.where,
                    )
                )
        # Return synthetic ids so callers that inspect ``EmitResult`` see
        # the same shape as a real fan-out.
        return [f"captured-{i}" for i in range(len(out))]

    _events._fanout_impl = _capture
    try:
        yield out
    finally:
        _events._fanout_impl = saved


__all__ = [
    "CapturedDelivery",
    "Expectation",
    "Response",
    "ScenarioAssertionError",
    "SnapshotValue",
    "TestApp",
    "captured",
    "captured_webhooks",
    "expect",
    "scenario",
    "snapshot",
    "stub",
    "tasks_eager",
]
