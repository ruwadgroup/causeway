"""``create_app`` integration tests — class middleware, error renderer, hooks."""

from __future__ import annotations

from pathlib import Path

import httpx
from starlette.testclient import TestClient

from causeway import create_app
from causeway.plugins import clear


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


async def test_create_app_wires_handler(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {'ok': True}\n",
    )
    app = create_app(routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_create_app_includes_health_and_diagnostics(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {}\n",
    )
    app = create_app(routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/__causeway")).status_code == 200


async def test_create_app_health_false_omits_probes(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {}\n",
    )
    app = create_app(routes, health=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/healthz")).status_code == 404
        assert (await client.get("/")).status_code == 200


async def test_create_app_exposes_dev_graph(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "(org)/customers/$id/screen.py",
        "from causeway import post\n"
        "@post(refreshes=('GET /customers/$id', 'GET /customers'))\n"
        "async def screen(id: str) -> dict: return {'id': id}\n",
    )
    app = create_app(routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/__causeway/graph")

    assert resp.status_code == 200
    route = resp.json()["routes"][0]
    assert route["route_key"] == "POST /customers/$id/screen"
    assert route["http_path"] == "/customers/{id}/screen"
    assert route["scopes"] == ["org"]
    assert route["refreshes"] == ["GET /customers/$id", "GET /customers"]


def test_create_app_result_exposes_starlette_app_methods(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {}\n",
    )
    app = create_app(routes)

    assert app.router is app.app.router
    assert callable(app.add_middleware)


async def test_class_middleware_wraps_responses(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "_middleware.py",
        """from causeway import Middleware

class StampHeader(Middleware):
    async def __call__(self, req, call_next):
        resp = await call_next(req)
        resp.headers['x-stamped'] = 'yes'
        return resp

middleware = [StampHeader()]
""",
    )
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {}\n",
    )
    app = create_app(routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/")
    assert resp.headers.get("x-stamped") == "yes"


async def test_error_renderer_emits_problem_json(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        """from causeway import get, raises
from causeway.errors import NotFound

@get
@raises(NotFound)
async def r() -> dict:
    raise NotFound('nope')
""",
    )
    app = create_app(routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/")
    # Causeway serializes @raises into its typed Result envelope.
    assert resp.status_code == 404
    assert resp.json()["error"]["kind"] == "NotFound"


async def test_create_app_renders_undeclared_http_error_as_problem_json(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        """from causeway import get
from causeway.errors import Unauthorized

@get
async def r() -> dict:
    raise Unauthorized('sign in')
""",
    )
    app = create_app(routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert {k: body[k] for k in ("type", "title", "status", "detail")} == {
        "type": "about:blank#unauthorized",
        "title": "unauthorized",
        "status": 401,
        "detail": "sign in",
    }
    assert isinstance(body["request_id"], str)


async def test_create_app_error_formatter_applies_to_result_and_problem_json(
    tmp_path: Path,
) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "declared.py",
        """from causeway import get, raises
from causeway.errors import BadRequest

@get
@raises(BadRequest)
async def r() -> dict:
    raise BadRequest('invalid_phone', detail={'field': 'phone'})
""",
    )
    _write(
        routes,
        "undeclared.py",
        """from causeway import get
from causeway.errors import BadRequest

@get
async def r() -> dict:
    raise BadRequest('invalid_phone', detail={'field': 'phone'})
""",
    )

    def formatter(exc, request):
        return {
            "message": f"{request.url.path}: {exc.message}",
            "detail": {**exc.detail, "formatted": True},
        }

    app = create_app(routes, error_formatter=formatter)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        declared = await client.get("/declared")
        problem = await client.get("/undeclared")

    declared_error = declared.json()["error"]
    assert declared.status_code == 400
    assert {k: declared_error[k] for k in ("kind", "status", "code", "message", "detail")} == {
        "kind": "BadRequest",
        "status": 400,
        "code": "bad_request",
        "message": "/declared: invalid_phone",
        "detail": {"field": "phone", "formatted": True},
    }
    assert isinstance(declared_error["request_id"], str)
    assert problem.status_code == 400
    assert problem.headers["content-type"].startswith("application/problem+json")
    assert problem.json()["detail"] == "/undeclared: invalid_phone"
    assert problem.json()["params"] == {"field": "phone", "formatted": True}


def test_create_app_loads_app_plugins_and_runs_lifecycle(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    routes = app_root / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {}\n",
    )
    _write(
        app_root,
        "plugins.py",
        f"""from pathlib import Path
from typing import ClassVar
from causeway import register

LOG = Path({str(tmp_path / "plugin.log")!r})

class Recorder:
    contract_version: ClassVar[str] = "v1.0"

    async def startup(self, settings):
        LOG.write_text(LOG.read_text() + "startup\\n" if LOG.exists() else "startup\\n")

    async def shutdown(self):
        LOG.write_text(LOG.read_text() + "shutdown\\n")

register(Recorder())
""",
    )

    clear()
    app = create_app(routes)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
    assert (tmp_path / "plugin.log").read_text().splitlines() == ["startup", "shutdown"]
    clear()


def test_create_app_runs_app_lifespan_around_route_hooks(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    routes = app_root / "routes"
    log = tmp_path / "lifespan.log"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def r() -> dict: return {}\n",
    )
    _write(
        app_root,
        "lifespan.py",
        f"""from pathlib import Path

LOG = Path({str(log)!r})

async def startup():
    LOG.write_text(LOG.read_text() + "app-startup\\n" if LOG.exists() else "app-startup\\n")

async def shutdown():
    LOG.write_text(LOG.read_text() + "app-shutdown\\n")
""",
    )
    _write(
        routes,
        "_scope.py",
        f"""from pathlib import Path

LOG = Path({str(log)!r})

async def startup():
    LOG.write_text(LOG.read_text() + "route-startup\\n")

async def shutdown():
    LOG.write_text(LOG.read_text() + "route-shutdown\\n")
""",
    )

    app = create_app(routes)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
    assert log.read_text().splitlines() == [
        "app-startup",
        "route-startup",
        "route-shutdown",
        "app-shutdown",
    ]
