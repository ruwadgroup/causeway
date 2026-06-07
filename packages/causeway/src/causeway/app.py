from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import re

from starlette.applications import Starlette
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Mount, compile_path

import causeway.events as _events
import causeway.plugins as _plugins
import causeway.webhooks as _webhooks  # noqa: F401 — wires fan-out into Event.emit at import
from causeway._loader import import_path
from causeway._runtime import App
from causeway._traceback import ExceptionShield
from causeway.diagnostics import attach as attach_diagnostics
from causeway.errors import HttpErrorFormatter, make_error_renderer
from causeway.graph import build_graph
from causeway.health import attach as attach_health
from causeway.middleware import Middleware as CausewayMiddleware
from causeway.observability import RequestIdMiddleware
from causeway.routing import Discovered, discover, register


def create_app(
    routes_root: str | Path = "app/routes",
    *,
    events_root: str | Path = "app/events",
    listeners_root: str | Path = "app/listeners",
    subscribers_root: str | Path = "app/subscribers",
    settings: Any = None,
    diagnostics: bool = True,
    request_id: bool = True,
    health: bool = True,
    error_renderer_: bool = True,
    error_formatter: HttpErrorFormatter | None = None,
) -> Any:
    _discover_plugins(routes_root)
    found = discover(routes_root)
    events = _discover_events(events_root, listeners_root, subscribers_root)
    app_lifespan = _discover_app_lifespan(routes_root)
    return _assemble(
        found,
        events=events,
        app_lifespan=app_lifespan,
        settings=settings,
        diagnostics=diagnostics,
        request_id=request_id,
        health=health,
        error_renderer_=error_renderer_,
        error_formatter=error_formatter,
    )


def create_app_frozen(
    found: Discovered,
    *,
    events: _events.Discovered | None = None,
    settings: Any = None,
    diagnostics: bool = False,
    request_id: bool = True,
    health: bool = True,
    error_renderer_: bool = True,
    error_formatter: HttpErrorFormatter | None = None,
) -> Any:
    if _build_mode_is_binary() and diagnostics:
        diagnostics = False
    return _assemble(
        found,
        events=events,
        app_lifespan=None,
        settings=settings,
        diagnostics=diagnostics,
        request_id=request_id,
        health=health,
        error_renderer_=error_renderer_,
        error_formatter=error_formatter,
    )


def _assemble(
    found: Discovered,
    *,
    events: _events.Discovered | None,
    app_lifespan: Any,
    settings: Any,
    diagnostics: bool,
    request_id: bool,
    health: bool,
    error_renderer_: bool,
    error_formatter: HttpErrorFormatter | None,
) -> Any:
    renderer = make_error_renderer(error_formatter) if error_renderer_ else None
    inner = App(exception_handler=renderer, error_formatter=error_formatter)
    register(inner, found)
    inner.graph = build_graph(inner, events=events)
    if health:
        attach_health(inner)
    if diagnostics:
        attach_diagnostics(inner, settings=settings)

    middleware: list[StarletteMiddleware] = []
    if request_id:
        middleware.append(StarletteMiddleware(RequestIdMiddleware))
    middleware.extend(_collect_class_middleware(found))

    exception_handlers: dict[Any, Any] = {}
    if renderer is not None:
        exception_handlers[Exception] = renderer

    _ = events  # discovery already had its side effects; nothing to install

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        # Plugins/adapters (DB, cache, …) start first so the app's own
        # ``startup()`` hook can use them — otherwise an on_startup that touches
        # the DB hits the adapter before its engine exists. Shutdown mirrors
        # this: app shutdown runs while adapters are still alive, then plugins.
        await _plugins.startup_all(settings)
        if app_lifespan is not None:
            startup: Callable[[], Awaitable[object]] | None = getattr(app_lifespan, "startup", None)
            if callable(startup):
                await startup()
        for hook in found.startup_hooks:
            await hook()
        try:
            yield
        finally:
            for hook in found.shutdown_hooks:
                await hook()
            if app_lifespan is not None:
                shutdown: Callable[[], Awaitable[object]] | None = getattr(
                    app_lifespan, "shutdown", None
                )
                if callable(shutdown):
                    await shutdown()
            await _plugins.shutdown_all()

    starlette = Starlette(
        routes=[Mount("/", app=inner)],
        middleware=middleware,
        exception_handlers=exception_handlers,
        lifespan=lifespan,
    )
    # Starlette's ServerErrorMiddleware re-raises every unhandled exception
    # after the registered handler renders the 500 response. Without this
    # shield, that re-raise reaches the ASGI server and a giant Python
    # traceback gets printed on top of our compact one.
    return ExceptionShield(starlette)


def _discover_plugins(routes_root: str | Path) -> None:
    _plugins.discover()
    app_root = Path(routes_root).parent
    plugins_file = app_root / "plugins.py"
    if plugins_file.is_file():
        import_path(plugins_file, label_prefix="_causeway_plugins")


def _discover_app_lifespan(routes_root: str | Path) -> Any:
    app_root = Path(routes_root).parent
    lifespan_file = app_root / "lifespan.py"
    if not lifespan_file.is_file():
        return None
    return import_path(lifespan_file, label_prefix="_causeway_lifespan")


def _discover_events(
    events_root: str | Path,
    listeners_root: str | Path,
    subscribers_root: str | Path,
) -> _events.Discovered | None:
    if not Path(events_root).is_dir():
        return None
    snapshot = _events.discover(
        events_root,
        listeners_root=listeners_root if Path(listeners_root).is_dir() else None,
    )
    for entry in _visible_py_tree(Path(subscribers_root)):
        import_path(entry, label_prefix="_causeway_subscribers")
    return snapshot


def _build_mode_is_binary() -> bool:
    return os.environ.get("CAUSEWAY_BUILD_MODE") == "binary"


def _collect_class_middleware(found: Any) -> list[StarletteMiddleware]:
    """Chain every per-route class middleware into a single ``BaseHTTPMiddleware``.

    Each ``BaseHTTPMiddleware`` spawns an ``anyio.create_task_group()`` + a
    memory-object-stream pair per request — meaningful overhead. Collapsing
    N middlewares into one wrapper keeps the same outer→inner ordering and
    per-route path/method gating while paying that cost just once.
    """
    seen: dict[int, tuple[CausewayMiddleware, dict[str, list[re.Pattern[str]]]]] = {}
    order: list[int] = []
    path_cache: dict[str, re.Pattern[str]] = {}

    for route in found.routes:
        recorded = getattr(route.handler, "__causeway_class_middleware__", None)
        if not recorded:
            continue
        regex = path_cache.get(route.path)
        if regex is None:
            regex, _, _ = compile_path(route.path)
            path_cache[route.path] = regex
        method = route.method.upper()
        for mw in recorded:
            mid = id(mw)
            entry = seen.get(mid)
            if entry is None:
                entry = (mw, {})
                seen[mid] = entry
                order.append(mid)
            entry[1].setdefault(method, []).append(regex)

    if not order:
        return []
    chain = [seen[mid] for mid in order]
    return [StarletteMiddleware(BaseHTTPMiddleware, dispatch=_chained_dispatch(chain))]


def _chained_dispatch(
    chain: list[tuple[CausewayMiddleware, dict[str, list[re.Pattern[str]]]]],
) -> Any:
    async def dispatch(request: Any, call_next: Any) -> Any:
        path = request.url.path
        method = request.method
        matching = [
            mw
            for mw, by_method in chain
            if any((r.fullmatch(path) is not None) for r in (by_method.get(method) or ()))
        ]
        if not matching:
            return await call_next(request)

        async def step(i: int, req: Any) -> Any:
            if i == len(matching):
                return await call_next(req)
            return await matching[i](req, lambda r: step(i + 1, r))

        return await step(0, request)

    return dispatch


def _visible_py_tree(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    resolved = root.resolve()
    return [
        entry
        for entry in sorted(root.rglob("*.py"))
        if not any(p.startswith(("_", ".")) for p in entry.resolve().relative_to(resolved).parts)
    ]


__all__ = ["create_app", "create_app_frozen"]
