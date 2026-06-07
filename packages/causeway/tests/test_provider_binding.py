"""Annotated[T, provider] auto-rewrite as documented in getting-started.md."""

from __future__ import annotations

from pathlib import Path

import httpx

from causeway._runtime import App
from causeway.routing import discover, register


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


async def test_annotated_provider_is_rewritten(tmp_path: Path) -> None:
    """When a route handler references a scope provider via
    ``Annotated[T, provider]``, the file router rewrites it to
    ``Annotated[T, Depends(provider)]`` so Causeway can resolve the dep.
    """
    routes = tmp_path / "routes"
    _write(
        routes,
        "_scope.py",
        """from causeway import provide

@provide('db')
async def get_session():
    yield {'name': 'ada'}
""",
    )
    # Route file pulls the provider through Python's sys.modules — the file
    # router loads ``_scope.py`` first and stamps it with a stable label, so
    # the route file resolves the symbol via importlib's spec dance.
    _write(
        routes,
        "users.py",
        """import importlib.util as _ilu
import sys as _sys
from pathlib import Path as _Path
from typing import Annotated

from causeway import get

_scope_path = _Path(__file__).parent / "_scope.py"
_spec = _ilu.spec_from_file_location("_test_scope", _scope_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
get_session = _mod.get_session


@get
async def show(db: Annotated[dict, get_session]) -> dict:
    return db
""",
    )

    app = App()
    register(app, discover(routes))

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/users")
    assert resp.status_code == 200
    assert resp.json() == {"name": "ada"}


async def test_handlers_without_provider_annotations_pass_through(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "_scope.py",
        "from causeway import provide\n@provide('db')\nasync def get_session(): yield 'x'\n",
    )
    _write(
        routes,
        "ping.py",
        "from causeway import get\n@get\nasync def show() -> dict: return {'ok': True}\n",
    )

    app = App()
    register(app, discover(routes))
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/ping")
    assert resp.json() == {"ok": True}
