"""End-to-end: discovered routes register onto a Causeway runtime app and respond."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from causeway._runtime import App
from causeway.routing import discover, register


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


@pytest.mark.asyncio
async def test_full_path_get_request_lands(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "users/$id.py",
        """from causeway import get
from msgspec import Struct

class User(Struct):
    id: str
    name: str

@get
async def show(id: str) -> User:
    return User(id=id, name="ada")
""",
    )

    app = App()
    register(app, discover(routes))

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/users/u123")
    assert resp.status_code == 200
    assert resp.json() == {"id": "u123", "name": "ada"}


def test_route_module_is_registered_while_executing(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        """from __future__ import annotations

from dataclasses import dataclass

from causeway import get

@dataclass(frozen=True)
class User:
    name: str

@get
async def r() -> User:
    return User(name="ada")
""",
    )

    found = discover(routes)
    module_name = found.routes[0].handler.__module__
    assert module_name in sys.modules


@pytest.mark.asyncio
async def test_guard_short_circuits(tmp_path: Path) -> None:
    """The guard raises; the handler body must not run.

    The HTTP-status mapping for guard-raised exceptions belongs to the error
    renderer slice — here we verify the short-circuit semantics directly by
    invoking the discovered route's wrapped handler. A passing test proves:
    (a) guards are composed onto the handler, (b) a guard raise propagates
    out, (c) the body is never reached.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "_middleware.py",
        """from causeway import guard

@guard
async def deny(req):
    raise PermissionError("nope")

middleware = [deny]
""",
    )
    _write(
        routes,
        "index.py",
        """from causeway import get

@get
async def r() -> dict:
    raise AssertionError("handler body must not run when a guard denies")
""",
    )

    found = discover(routes)
    assert len(found.routes) == 1
    route = found.routes[0]

    # The wrapped handler reads the active Request from the runtime's contextvar
    # when one isn't present in the handler signature. Simulate that here.
    from dataclasses import dataclass

    from causeway._runtime.context import Context, current_context_var

    @dataclass
    class _FakeReq:
        headers: dict[str, str]
        url: str

    token = current_context_var.set(Context(request=_FakeReq(headers={}, url="http://t/")))  # type: ignore[arg-type]
    try:
        with pytest.raises(PermissionError, match="nope"):
            await route.handler()
    finally:
        current_context_var.reset(token)


@pytest.mark.asyncio
async def test_use_decorator_attaches_guard_per_handler(tmp_path: Path) -> None:
    """``@use(guard_fn)`` attaches a guard to a single handler.

    The guard runs before the body; raising short-circuits, exactly like a
    guard declared in ``_middleware.py`` would, but scoped to this route.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        """from causeway import get, guard, use

@guard
async def deny(req):
    raise PermissionError("scoped nope")

@get
@use(deny)
async def r() -> dict:
    raise AssertionError("body must not run when @use guard denies")
""",
    )

    found = discover(routes)
    assert len(found.routes) == 1
    route = found.routes[0]

    from dataclasses import dataclass

    from causeway._runtime.context import Context, current_context_var

    @dataclass
    class _FakeReq:
        headers: dict[str, str]
        url: str

    token = current_context_var.set(Context(request=_FakeReq(headers={}, url="http://t/")))  # type: ignore[arg-type]
    try:
        with pytest.raises(PermissionError, match="scoped nope"):
            await route.handler()
    finally:
        current_context_var.reset(token)


def test_use_decorator_validates_entry_types() -> None:
    """``@use(...)`` rejects entries that aren't a Middleware or guard.

    The runtime-checkable ``Middleware`` Protocol only inspects for
    ``__call__``, so bare callables sneak through here — matching the
    behaviour of ``_middleware.py`` validation. Non-callable values are
    the case we can catch.
    """
    from causeway import use

    with pytest.raises(TypeError, match="Middleware instance or a @guard"):
        use("not-a-middleware")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dependency_binds_resolver_into_handler(tmp_path: Path) -> None:
    """``@dependency`` resolvers are wired into the handler as ``Depends``.

    The handler param ``me: CurrentUser`` resolves to whatever the dependency
    function returns — no ``_scope.py`` needed.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "me.py",
        """from causeway import dependency, get
from starlette.requests import Request

@dependency
async def CurrentUser(req: Request) -> str:
    return "ada"

@get
async def show(me: CurrentUser) -> dict:
    return {"who": me}
""",
    )

    app = App()
    register(app, discover(routes))

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/me")
    assert resp.status_code == 200
    assert resp.json() == {"who": "ada"}


@pytest.mark.asyncio
async def test_dependency_raise_reaches_error_renderer(tmp_path: Path) -> None:
    """A ``@dependency`` resolver that raises short-circuits the handler.

    The body must not run; the exception reaches Causeway's error renderer
    even though Dyadpy now owns compact uncaught-exception rendering.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "me.py",
        """from causeway import dependency, get
from causeway.errors import Unauthorized
from starlette.requests import Request

@dependency
async def CurrentUser(req: Request) -> str:
    raise Unauthorized("sign in")

@get
async def show(me: CurrentUser) -> dict:
    raise AssertionError("body must not run when dependency raises")
""",
    )

    from causeway.errors import error_renderer

    app = App(exception_handler=error_renderer)
    register(app, discover(routes))

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/me")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json() == {
        "type": "about:blank#unauthorized",
        "title": "unauthorized",
        "status": 401,
        "detail": "sign in",
    }


def test_guard_does_not_leak_into_class_middleware(tmp_path: Path) -> None:
    """A guard listed alone in ``_middleware.py`` must not become class middleware.

    Regression: ``Middleware`` is a runtime-checkable Protocol matching any
    async callable with ``__call__``, so ``@guard`` functions used to land in
    both partitions — the ASGI layer would then invoke them with
    ``(req, call_next)`` and crash with ``TypeError: takes 1 positional
    argument but 2 were given``. Asserted at the partition layer so the test
    doesn't drag in Starlette/anyio (which leak ResourceWarnings under the
    bare ``ASGITransport`` we use elsewhere).
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "_middleware.py",
        """from causeway import guard

@guard
async def allow(req):
    return None

middleware = [allow]
""",
    )
    _write(
        routes,
        "index.py",
        """from causeway import get

@get
async def r() -> dict:
    return {"ok": True}
""",
    )

    found = discover(routes)
    assert len(found.routes) == 1
    handler = found.routes[0].handler
    recorded = getattr(handler, "__causeway_class_middleware__", None)
    assert not recorded, f"guard leaked into class-middleware partition: {recorded!r}"


@pytest.mark.asyncio
async def test_class_middleware_is_path_gated(tmp_path: Path) -> None:
    """A ``Middleware`` attached via ``@use`` runs only for its handler.

    Regression for the prior global-ASGI-chain limitation: the gated dispatch
    must invoke the wrapped middleware for the route that declared it and
    fall through to ``call_next`` for any other path or method. Exercised at
    the dispatch level rather than through Starlette+httpx, both because we
    only need to test the gating behaviour and because ``BaseHTTPMiddleware``
    under ``ASGITransport`` leaks task-group resources that fail under
    ``filterwarnings = error``.
    """
    from causeway.app import _collect_class_middleware

    routes = tmp_path / "routes"
    _write(
        routes,
        "tagged.py",
        """from causeway import get, use

class StampHeader:
    async def __call__(self, req, call_next):
        return ("stamped", req.url.path)

@get
@use(StampHeader())
async def r() -> dict:
    return {"ok": True}
""",
    )
    _write(
        routes,
        "plain.py",
        """from causeway import get

@get
async def r() -> dict:
    return {"ok": True}
""",
    )

    found = discover(routes)
    entries = _collect_class_middleware(found)
    assert len(entries) == 1, "exactly one Middleware instance was registered"
    dispatch: Any = entries[0].kwargs["dispatch"]

    class _FakeURL:
        def __init__(self, path: str) -> None:
            self.path = path

    class _FakeReq:
        def __init__(self, method: str, path: str) -> None:
            self.method = method
            self.url = _FakeURL(path)

    async def _call_next(_req: object) -> tuple[str, str]:
        return ("passthrough", _req.url.path)  # type: ignore[attr-defined]

    matched = await dispatch(_FakeReq("GET", "/tagged"), _call_next)
    bypassed_path = await dispatch(_FakeReq("GET", "/plain"), _call_next)
    bypassed_method = await dispatch(_FakeReq("POST", "/tagged"), _call_next)

    assert matched == ("stamped", "/tagged")
    assert bypassed_path == ("passthrough", "/plain")
    assert bypassed_method == ("passthrough", "/tagged")


def test_dependency_requires_return_annotation() -> None:
    """``@dependency`` cannot infer its user-visible type without one."""
    from causeway import dependency

    async def resolver(req):  # type: ignore[no-untyped-def]
        del req
        return "x"

    with pytest.raises(TypeError, match="must declare a return type"):
        dependency(resolver)


@pytest.mark.asyncio
async def test_pep563_route_binds_providers(tmp_path: Path) -> None:
    """A route file using ``from __future__ import annotations`` must still
    have its ``Annotated[T, dep]`` providers bound.

    Regression: ``_bind_providers`` used ``inspect.signature`` without
    ``eval_str=True``, so the annotation came back as the string
    ``'Annotated[...]'`` and ``get_origin`` returned ``None`` — every
    provider was silently skipped and the request 422'd as "missing
    required parameter 'me'".
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "items.py",
        """from __future__ import annotations

from causeway import dependency, get
from starlette.requests import Request


@dependency
async def CurrentUser(req: Request) -> str:
    return "ada"


@get
async def show(me: CurrentUser) -> dict:
    return {"me": me}
""",
    )

    app = App()
    register(app, discover(routes))

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/items")
    assert resp.status_code == 200
    assert resp.json() == {"me": "ada"}


@pytest.mark.asyncio
async def test_provider_param_followed_by_path_param(tmp_path: Path) -> None:
    """Handler signature ``(me: CurrentUser, id: str)`` must not raise.

    Regression: ``param.replace(...)`` rewrote the provider param in place,
    giving it a ``Depends(...)`` default while the following ``id`` param
    still had no default — ``Signature(...)`` then refused to build the
    rewritten signature with "non-default argument follows default
    argument" at app boot.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "items/$id.py",
        """from causeway import dependency, get
from starlette.requests import Request


@dependency
async def CurrentUser(req: Request) -> str:
    return "ada"


@get
async def show(me: CurrentUser, id: str) -> dict:
    return {"me": me, "id": id}
""",
    )

    app = App()
    register(app, discover(routes))

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/items/abc")
    assert resp.status_code == 200
    assert resp.json() == {"me": "ada", "id": "abc"}


def test_literal_sibling_outranks_parametric(tmp_path: Path) -> None:
    """``/things/risk-overrides`` must register before ``/things/{id}``.

    Regression: parametric siblings were registered before literal siblings,
    so Starlette matched the parametric route first and shadowed the literal.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "things/$id.py",
        "from causeway import get\n@get\nasync def show(id: str) -> dict: return {'id': id}\n",
    )
    _write(
        routes,
        "things/risk-overrides/index.py",
        "from causeway import get\n@get\nasync def show() -> dict: return {'literal': True}\n",
    )
    found = discover(routes)
    paths = [r.path for r in found.routes]
    # Literal must come before the parametric sibling.
    assert paths.index("/things/risk-overrides") < paths.index("/things/{id}"), paths
