"""``App`` is both:

- A route registry that decorators append to (no metaclasses, no import-time magic).
- A callable ASGI application that delegates to Starlette.

Routes are declared eagerly, but reflection is lazy — the per-handler ``HandlerPlan``
is built on the first ASGI call. That keeps test ergonomics nice: you can build
an ``App``, inspect its routes, and never boot a server.
"""

from __future__ import annotations

import contextlib
import inspect
import sys
import typing
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Literal

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route as StarletteRoute
from starlette.routing import WebSocketRoute as StarletteWebSocketRoute

from causeway._paths import route_key_from_url
from causeway._runtime.runtime import ExceptionHandler, HandlerPlan, RouteRunner, build_plan
from causeway.errors import HttpErrorFormatter

# ``causeway._runtime.bidi`` is imported lazily inside the ``websocket`` decorator and the
# build path — it drags ``starlette.websockets`` which costs ~5 ms at import
# time and is irrelevant for the dominant HTTP-only case.

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

# Handlers are either ``async def`` (Awaitable[T]) or async generators
# (AsyncIterator[T]) for streams. We accept anything callable; the runtime
# inspects the return annotation to decide.
Handler = Callable[..., Any]

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


@dataclass(slots=True)
class Route:
    method: HttpMethod
    path: str
    handler: Handler
    name: str | None = None
    route_key: str | None = None
    source: str | None = None
    scopes: tuple[str, ...] = ()
    refreshes: tuple[str, ...] = ()
    middleware: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    idempotency: dict[str, Any] | None = None
    plan: HandlerPlan | None = None


@dataclass(slots=True)
class WebSocketRoute:
    """A bidirectional WebSocket route. Handler accepts a ``BidiChannel[S, R]``."""

    path: str
    handler: Handler
    name: str | None = None
    send_type: Any = None
    recv_type: Any = None


def _new_routes() -> list[Route]:
    return []


def _new_ws_routes() -> list[WebSocketRoute]:
    return []


@dataclass(slots=True)
class App:
    routes: list[Route] = field(default_factory=_new_routes)
    websocket_routes: list[WebSocketRoute] = field(default_factory=_new_ws_routes)
    exception_handler: ExceptionHandler | None = None
    error_formatter: HttpErrorFormatter | None = None
    graph: Any | None = None
    _starlette: Starlette | None = None

    def _register(self, method: HttpMethod, path: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            # Snapshot the caller's locals so ``typing.get_type_hints`` can resolve
            # types declared next to the handler. Without this, ``from __future__
            # import annotations`` leaves annotations as strings that
            # ``get_type_hints`` can't evaluate.
            with contextlib.suppress(AttributeError, ValueError):
                handler.__causeway_localns__ = dict(sys._getframe(1).f_locals)  # type: ignore[attr-defined]
            contract = getattr(handler, "__causeway_contract__", {}) or {}
            route_key = getattr(handler, "__causeway_route_key__", None)
            self.routes.append(
                Route(
                    method=method,
                    path=path,
                    handler=handler,
                    route_key=route_key
                    if isinstance(route_key, str)
                    else route_key_from_url(method, path),
                    source=getattr(handler, "__causeway_route_source__", None),
                    scopes=tuple(getattr(handler, "__causeway_route_scopes__", ()) or ()),
                    refreshes=tuple(
                        getattr(
                            handler,
                            "__causeway_route_refreshes__",
                            contract.get("refreshes", ()),
                        )
                        or (),
                    ),
                    middleware=tuple(getattr(handler, "__causeway_route_middleware__", ()) or ()),
                    providers=tuple(getattr(handler, "__causeway_route_providers__", ()) or ()),
                    requires=tuple(getattr(handler, "__causeway_route_requires__", ()) or ()),
                    idempotency=getattr(handler, "__causeway_route_idempotency__", None),
                ),
            )
            self.invalidate()
            return handler

        return decorator

    def get(self, path: str) -> Callable[[Handler], Handler]:
        return self._register("GET", path)

    def post(self, path: str) -> Callable[[Handler], Handler]:
        return self._register("POST", path)

    def put(self, path: str) -> Callable[[Handler], Handler]:
        return self._register("PUT", path)

    def patch(self, path: str) -> Callable[[Handler], Handler]:
        return self._register("PATCH", path)

    def delete(self, path: str) -> Callable[[Handler], Handler]:
        return self._register("DELETE", path)

    def websocket(self, path: str) -> Callable[[Handler], Handler]:
        """Register a bidirectional WebSocket route.

        The handler must take exactly one parameter annotated
        ``BidiChannel[S, R]``. The runtime accepts the WebSocket connection
        and calls the handler with the typed channel.
        """

        def decorator(handler: Handler) -> Handler:
            with contextlib.suppress(AttributeError, ValueError):
                handler.__causeway_localns__ = dict(sys._getframe(1).f_locals)  # type: ignore[attr-defined]
            send_t, recv_t = _extract_bidi_types(handler)
            self.websocket_routes.append(
                WebSocketRoute(
                    path=path,
                    handler=handler,
                    send_type=send_t,
                    recv_type=recv_t,
                ),
            )
            self.invalidate()
            return handler

        return decorator

    def invalidate(self) -> None:
        """Drop the cached Starlette app so it's rebuilt on the next request."""
        self._starlette = None

    def _build(self) -> Starlette:
        starlette_routes: list[StarletteRoute | StarletteWebSocketRoute] = []
        for r in self.routes:
            if r.plan is None:
                r.plan = build_plan(r.handler, r.path)
            runner = RouteRunner(
                handler=r.handler,
                plan=r.plan,
                exception_handler=self.exception_handler,
                error_formatter=self.error_formatter,
            )
            starlette_routes.append(
                StarletteRoute(
                    path=r.path,
                    endpoint=_endpoint_for(runner),
                    methods=[r.method],
                    name=r.name or r.handler.__name__,
                ),
            )
        for wr in self.websocket_routes:
            starlette_routes.append(
                StarletteWebSocketRoute(
                    path=wr.path,
                    endpoint=_ws_endpoint_for(wr),
                    name=wr.name or wr.handler.__name__,
                ),
            )
        return Starlette(routes=starlette_routes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = self._starlette
        if app is None:
            app = self._build()
            self._starlette = app
        await app(scope, receive, send)


def _endpoint_for(runner: RouteRunner) -> Callable[[Request], Awaitable[Response]]:
    async def endpoint(request: Request) -> Response:
        return await runner.handle(request)

    return endpoint


def _extract_bidi_types(handler: Handler) -> tuple[Any, Any]:
    """Pull ``S`` and ``R`` out of the handler's ``BidiChannel[S, R]`` param."""
    from causeway._runtime.bidi import bidi_types, is_bidi_annotation

    sig = inspect.signature(handler)
    localns: dict[str, Any] | None = getattr(handler, "__causeway_localns__", None)
    hints = typing.get_type_hints(handler, localns=localns, include_extras=True)
    for name in sig.parameters:
        annotation = hints.get(name, sig.parameters[name].annotation)
        if is_bidi_annotation(annotation):
            pair = bidi_types(annotation)
            if pair is not None:
                return pair
            return Any, Any
    msg = f"@app.websocket handler {handler.__name__!r} must accept a BidiChannel[S, R] parameter"
    raise TypeError(msg)


def _ws_endpoint_for(
    route: WebSocketRoute,
) -> Callable[[Any], Awaitable[None]]:
    from causeway._runtime.bidi import BidiChannel

    async def endpoint(websocket: Any) -> None:
        channel: BidiChannel[Any, Any] = BidiChannel(  # pyright: ignore[reportUnknownVariableType]
            websocket,
            send_type=route.send_type,
            recv_type=route.recv_type,
        )
        await route.handler(channel)

    return endpoint
