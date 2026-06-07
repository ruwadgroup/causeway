"""``scenario(...)`` context manager and the ``it`` fluent client.

A scenario block runs under one of two modes set by the pytest plugin
via :func:`set_registry`:

- ``collect``: ``__enter__`` records the scenario into the registry and
  immediately raises :class:`_CollectionSkip`, which ``__exit__``
  swallows. Bodies never execute during collection. Static labels are
  the norm; dynamic labels (e.g. inside a ``for`` loop) work too,
  although duplicate labels are disambiguated by position.
- ``execute``: scenarios run only when the registry's
  ``target_index`` matches; others register themselves but otherwise
  short-circuit. The one matching scenario builds a fresh event loop +
  :class:`TestApp`, yields an :class:`_It`, and tears down on exit.

Outside the plugin (``current_registry()`` returns ``None``)
``scenario`` is a no-op so a route module remains importable in
production with zero cost.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, suppress
from types import TracebackType
from typing import TYPE_CHECKING, Any

from causeway._testing.errors import ScenarioAssertionError
from causeway._testing.registry import (
    RegisteredScenario,
    current_registry,
)
from causeway._testing.response import Response

if TYPE_CHECKING:
    from causeway.testing import TestApp

ScenarioBody = Callable[[], None]


class _It:
    """Per-scenario fluent client over a fresh :class:`TestApp`.

    The class is **synchronous to the user** — every HTTP method drives
    the underlying async ``TestApp.request`` through the scenario's
    private event loop. Method chaining keeps the call site terse:

    .. code-block:: python

        with scenario("creates and reads") as it:
            new = it.post("/users", json={...}).data
            expect(it.get(f"/users/{new.id}")).body.data.email == "a@x"
    """

    __slots__ = (
        "_active_loop",
        "_cleanups",
        "_collecting",
        "_last",
        "_loop",
        "_test_app",
    )

    def __init__(
        self,
        test_app: TestApp | None,
        loop: asyncio.AbstractEventLoop | None,
        *,
        collecting: bool,
    ) -> None:
        self._test_app = test_app
        self._loop = loop
        self._active_loop = loop
        self._collecting = collecting
        self._cleanups: list[Callable[[], None]] = []
        self._last: Response | None = None

    @property
    def collecting(self) -> bool:
        """True during pytest's collection phase. Use to guard heavy setup."""
        return self._collecting

    @property
    def last(self) -> Response | None:
        return self._last

    @property
    def app(self) -> Any:
        """Underlying causeway App. Escape hatch for advanced usage."""
        return None if self._test_app is None else self._test_app._app

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        if self._collecting or self._test_app is None or self._loop is None:
            return _NULL_RESPONSE
        raw = self._loop.run_until_complete(self._test_app.request(method, path, **kwargs))
        resp = Response(raw)
        self._last = resp
        return resp

    def get(self, path: str, **kwargs: Any) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Response:
        return self.request("DELETE", path, **kwargs)

    def override(self, provider: Callable[..., Any], replacement: Callable[..., Any]) -> _It:
        """Swap a DI provider for the rest of this scenario."""
        if self._collecting or self._test_app is None or self._loop is None:
            return self
        cm = self._test_app.override(provider, replacement)
        loop = self._loop
        loop.run_until_complete(cm.__aenter__())

        def _close_override() -> None:
            loop.run_until_complete(cm.__aexit__(None, None, None))

        self._cleanups.append(_close_override)
        return self

    def tasks_eager(self) -> _It:
        """Run background tasks inline for the rest of this scenario."""
        if self._collecting or self._loop is None:
            return self
        from causeway.tasks import tasks_eager as _eager

        cm = _eager()
        loop = self._loop
        loop.run_until_complete(cm.__aenter__())

        def _close_eager() -> None:
            loop.run_until_complete(cm.__aexit__(None, None, None))

        self._cleanups.append(_close_eager)
        return self

    def skip(self, reason: str = "") -> None:
        """Skip this scenario at runtime (raises pytest's skip exception)."""
        if self._collecting:
            return
        import pytest

        pytest.skip(reason or "skipped")

    def xfail(self, reason: str = "") -> None:
        """Mark this scenario as expected to fail."""
        if self._collecting:
            return
        import pytest

        pytest.xfail(reason or "expected failure")

    def _close(self) -> None:
        for cleanup in reversed(self._cleanups):
            with suppress(Exception):
                cleanup()
        self._cleanups.clear()


class _NullResponse(Response):
    """Returned by ``_It.*`` during collection. Every attribute is benign."""

    def __init__(self) -> None:
        self._raw = None  # type: ignore[assignment]
        self._body_cache = None

    @property
    def status_code(self) -> int:
        return 0

    @property
    def status(self) -> int:
        return 0

    @property
    def headers(self) -> Any:
        return {}

    @property
    def text(self) -> str:
        return ""

    def json(self) -> Any:
        return None


_NULL_RESPONSE: Response = _NullResponse()


class _ScenarioContextManager(AbstractContextManager["_It"]):
    """Implements the ``with scenario("...") as it:`` block."""

    __slots__ = (
        "_active_token",
        "_index",
        "_it",
        "_label",
        "_lineno",
        "_owns_loop",
        "_token",
    )

    def __init__(self, label: str) -> None:
        self._label = label
        self._lineno = _caller_lineno()
        self._index = -1
        self._it: _It | None = None
        self._owns_loop = False
        self._token: contextvars.Token[Any] | None = None
        self._active_token: contextvars.Token[bool] | None = None

    def __enter__(self) -> _It:
        reg = current_registry()
        if reg is None:
            # Production import — guard never matched. Yield a no-op proxy
            # so a stray scenario block doesn't crash.
            return _It(None, None, collecting=True)

        index = len(reg.scenarios)

        if reg.mode == "collect":
            reg.scenarios.append(
                RegisteredScenario(label=self._label, body=_NOOP, lineno=self._lineno)
            )
            self._index = index
            self._it = _It(None, None, collecting=True)
            return self._it

        reg.scenarios.append(RegisteredScenario(label=self._label, body=_NOOP, lineno=self._lineno))
        self._index = index
        target = reg.target_index
        # Either index match, or label match if target_index unset.
        active = (target is not None and target == index) or (
            target is None and reg.target_label == self._label
        )

        if not active:
            self._it = _It(None, None, collecting=True)
            return self._it

        from causeway.testing import TestApp

        app = TestApp.from_routes(reg.routes_root)
        loop = asyncio.new_event_loop()
        self._owns_loop = True
        # Detach any ambient loop so pytest-asyncio doesn't claim ours.
        try:
            self._token = _LOOP_VAR.set(loop)
        except Exception:
            self._token = None
        asyncio.set_event_loop(loop)

        self._it = _It(app, loop, collecting=False)
        self._active_token = _ACTIVE_VAR.set(True)
        return self._it

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if self._active_token is not None:
            _ACTIVE_VAR.reset(self._active_token)
            self._active_token = None
        try:
            if self._it is not None:
                self._it._close()
        finally:
            if self._owns_loop and self._it is not None and self._it._loop is not None:
                _shutdown_loop(self._it._loop)
                asyncio.set_event_loop(None)
        # Augment failures with the scenario label / file so reporters
        # surface the location even when raised from deep inside helpers.
        if isinstance(exc, ScenarioAssertionError):
            reg = current_registry()
            if exc.scenario_label is None:
                exc.scenario_label = self._label
            if exc.route_file is None and reg is not None:
                exc.route_file = reg.route_file


def _noop() -> None:  # pragma: no cover - placeholder
    pass


_NOOP: ScenarioBody = _noop
_LOOP_VAR: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "_causeway_scenario_loop", default=None
)

_ACTIVE_VAR: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_causeway_scenario_active", default=False
)


def is_active_scenario() -> bool:
    """True when execution is inside a scenario currently making real calls.

    Used by ``expect`` to no-op during collection and inside scenarios
    that aren't the pytest target.
    """
    return _ACTIVE_VAR.get()


def scenario(label: str) -> AbstractContextManager[_It]:
    """Declare an inline route-test scenario.

    See module docstring for the full collect/execute contract. Outside
    the pytest plugin this returns a no-op context that yields a stub
    ``it``, so route files remain importable in production.
    """
    return _ScenarioContextManager(label)


def _shutdown_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Drain pending tasks, shut down async generators, then close.

    Mirrors what ``asyncio.run`` does after the entrypoint returns —
    keeps test runs from leaking ``ResourceWarning`` for sockets and
    transports that finalize lazily.
    """
    try:
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
        if pending:
            with suppress(Exception):
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        with suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())
        with suppress(Exception):
            loop.run_until_complete(loop.shutdown_default_executor())
    finally:
        loop.close()


def _caller_lineno() -> int:
    frame = inspect.currentframe()
    if frame is None or frame.f_back is None or frame.f_back.f_back is None:
        return 0
    return frame.f_back.f_back.f_lineno


def iter_scenarios(module: Any) -> Iterator[RegisteredScenario]:
    """Yield scenarios registered against ``module``'s registry (if any)."""
    reg = getattr(module, "__causeway_registry__", None)
    if reg is None:
        return iter(())
    return iter(reg.scenarios)
