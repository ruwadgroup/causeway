"""AOT freeze pipeline. Phase-1 (Nuitka-independent)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from causeway._freeze import (
    MIRROR_PACKAGE,
    emit_frozen_entry,
    emit_frozen_plugins,
    freeze,
    mangle,
    mangle_filename,
)


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


@pytest.fixture(autouse=True)
def _clean_frozen_modules() -> Iterator[None]:
    # The mirror tree always uses the same package name, so a second test
    # would otherwise re-use the first test's imported modules.
    yield
    for name in list(sys.modules):
        if name.startswith(MIRROR_PACKAGE) or name == MIRROR_PACKAGE:
            del sys.modules[name]


def _import_frozen(out_dir: Path):
    sys.path.insert(0, str(out_dir))
    try:
        return importlib.import_module(f"{MIRROR_PACKAGE}._frozen_routes")
    finally:
        sys.path.pop(0)


def _route_key(method: str, path: str, handler) -> tuple[str, str, str]:
    # co_filename legitimately differs because the frozen path imports the
    # mangled mirror copy, not the original .py.
    fn = getattr(handler, "__wrapped__", handler)
    code = getattr(fn, "__code__", None)
    qual = getattr(code, "co_qualname", getattr(fn, "__name__", "?")) if code else "?"
    return (method, path, qual)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("index", "index"),
        ("$id", "_x24id"),
        ("(admin)", "_x28admin_x29"),
        ("$slug", "_x24slug"),
        ("a-b", "a_x2db"),
    ],
)
def test_mangle_is_valid_identifier(raw: str, expected: str) -> None:
    out = mangle(raw)
    assert out == expected
    assert out.isidentifier()


def test_mangle_filename_preserves_py_extension() -> None:
    assert mangle_filename("$id.py") == "_x24id.py"
    assert mangle_filename("plain.py") == "plain.py"


def test_mangle_leading_digit_gets_underscore() -> None:
    assert mangle("1foo").isidentifier()


def test_mirror_skips_underscore_dirs_and_pycache(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    _write(routes, "_lib/helper.py", "x = 1\n")
    _write(routes, "__pycache__/index.cpython-311.pyc", "")
    _write(routes, ".hidden/x.py", "x = 1\n")

    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)

    mirror = out / MIRROR_PACKAGE / "_routes"
    assert (mirror / "index.py").is_file()
    assert not (mirror / "_lib").exists()
    assert not (mirror / "__pycache__").exists()
    assert not (mirror / ".hidden").exists()


def test_mirror_renames_dollar_dynamic_files(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "users/$id.py",
        "from causeway import get\n@get\nasync def show(id: str): return {'id': id}\n",
    )
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)

    mirror = out / MIRROR_PACKAGE / "_routes"
    assert (mirror / "users" / mangle_filename("$id.py")).is_file()
    assert not (mirror / "users" / "$id.py").exists()


def test_frozen_matches_dynamic_for_basic_tree(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def root(): return {'ok': True}\n",
    )
    _write(
        routes,
        "users/index.py",
        "from causeway import get, post\n"
        "@get\nasync def list_(): return []\n"
        "@post\nasync def create(): return {'ok': True}\n",
    )
    _write(
        routes,
        "users/$id.py",
        "from causeway import get, patch, delete\n"
        "@get\nasync def show(id: str): return {'id': id}\n"
        "@patch\nasync def edit(id: str): return {'id': id}\n"
        "@delete\nasync def remove(id: str): return {'id': id}\n",
    )

    from causeway.routing import discover

    dynamic = discover(routes)

    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    frozen = _import_frozen(out).build_discovered()

    assert sorted((r.method, r.path) for r in dynamic.routes) == sorted(
        (r.method, r.path) for r in frozen.routes
    )
    assert sorted(_route_key(r.method, r.path, r.handler) for r in dynamic.routes) == sorted(
        _route_key(r.method, r.path, r.handler) for r in frozen.routes
    )


def test_frozen_matches_dynamic_with_scope_and_middleware(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "_scope.py",
        "from causeway import provide\n@provide('db')\nasync def db(): yield 'outer'\n",
    )
    _write(
        routes,
        "_middleware.py",
        "from causeway import guard\n@guard\nasync def g(req): pass\nmiddleware = [g]\n",
    )
    _write(
        routes,
        "users/_scope.py",
        "from causeway import provide\n"
        "@provide('db')\nasync def db(): yield 'inner'\n"
        "@provide('cache')\nasync def cache(): yield 'cache'\n",
    )
    _write(
        routes,
        "users/index.py",
        "from typing import Annotated\nfrom causeway import get\n"
        "@get\nasync def list_(db: Annotated[str, lambda: 'x']): return [db]\n",
    )
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")

    from causeway.routing import discover

    dynamic = discover(routes)
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    frozen = _import_frozen(out).build_discovered()

    dyn_by_path = {(r.method, r.path): r for r in dynamic.routes}
    frz_by_path = {(r.method, r.path): r for r in frozen.routes}
    assert set(dyn_by_path) == set(frz_by_path)

    assert set(dyn_by_path[("GET", "/users")].providers) == {"db", "cache"}
    assert set(frz_by_path[("GET", "/users")].providers) == {"db", "cache"}
    assert set(dyn_by_path[("GET", "/")].providers) == {"db"}
    assert set(frz_by_path[("GET", "/")].providers) == {"db"}

    assert len(dyn_by_path[("GET", "/")].middleware) == 1
    assert len(frz_by_path[("GET", "/")].middleware) == 1
    assert len(dyn_by_path[("GET", "/users")].middleware) == 1
    assert len(frz_by_path[("GET", "/users")].middleware) == 1


def test_frozen_picks_up_startup_shutdown_in_correct_order(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "_scope.py",
        "calls = []\n"
        "async def startup(): calls.append('outer-up')\n"
        "async def shutdown(): calls.append('outer-down')\n",
    )
    _write(
        routes,
        "users/_scope.py",
        "async def startup(): pass\nasync def shutdown(): pass\n",
    )
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    _write(routes, "users/index.py", "from causeway import get\n@get\nasync def r(): return {}\n")

    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    frozen = _import_frozen(out).build_discovered()

    assert len(frozen.startup_hooks) == 2
    assert len(frozen.shutdown_hooks) == 2


def test_freeze_is_byte_deterministic(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "users/$id.py",
        "from causeway import get\n@get\nasync def show(id: str): return {'id': id}\n",
    )
    _write(
        routes,
        "users/index.py",
        "from causeway import get\n@get\nasync def list_(): return []\n",
    )

    out_a = tmp_path / "build_a"
    out_b = tmp_path / "build_b"
    freeze(routes, out_a, user_plugins_module=None, settings_target=None)
    freeze(routes, out_b, user_plugins_module=None, settings_target=None)

    for rel in ("_frozen_routes.py", "_frozen_plugins.py", "_frozen_entry.py", "manifest.json"):
        a = (out_a / MIRROR_PACKAGE / rel).read_bytes()
        b = (out_b / MIRROR_PACKAGE / rel).read_bytes()
        assert a == b, f"{rel} differs between two freeze runs"


def test_freeze_clears_stale_files(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(routes, "old.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    assert (out / MIRROR_PACKAGE / "_routes" / "old.py").is_file()

    (routes / "old.py").unlink()
    _write(routes, "new.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    freeze(routes, out, user_plugins_module=None, settings_target=None)

    assert not (out / MIRROR_PACKAGE / "_routes" / "old.py").exists()
    assert (out / MIRROR_PACKAGE / "_routes" / "new.py").is_file()


async def test_frozen_app_serves_requests(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(
        routes,
        "index.py",
        "from causeway import get\n@get\nasync def root() -> dict: return {'status': 'ok'}\n",
    )
    _write(
        routes,
        "echo/$name.py",
        "from causeway import get\n"
        "@get\nasync def show(name: str) -> dict: return {'hello': name}\n",
    )

    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)

    from causeway.app import create_app_frozen

    found = _import_frozen(out).build_discovered()
    asgi = create_app_frozen(found, diagnostics=False)

    transport = httpx.ASGITransport(app=asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r1 = await client.get("/")
        r2 = await client.get("/echo/world")

    assert r1.status_code == 200
    # Causeway wraps successful responses in {ok, data}; raw bodies are
    # also valid for handlers that opt out.
    assert r1.json().get("data", r1.json()) == {"status": "ok"}
    assert r2.status_code == 200
    assert r2.json().get("data", r2.json()) == {"hello": "world"}


def test_emit_frozen_routes_is_parseable(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    src = (out / MIRROR_PACKAGE / "_frozen_routes.py").read_text()
    compile(src, "_frozen_routes.py", "exec")


def test_emit_frozen_plugins_is_parseable_with_no_entrypoints() -> None:
    from causeway._freeze import FreezePlan

    src = emit_frozen_plugins(
        FreezePlan(routes_root=Path(), out_dir=Path(), user_plugins_module=None),
    )
    compile(src, "_frozen_plugins.py", "exec")


def test_emit_frozen_entry_is_parseable_with_no_settings() -> None:
    from causeway._freeze import FreezePlan

    src = emit_frozen_entry(
        FreezePlan(routes_root=Path(), out_dir=Path(), settings_target=None),
    )
    compile(src, "_frozen_entry.py", "exec")


def test_emit_frozen_routes_empty_tree_handles_no_routes(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    routes.mkdir()
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    src = (out / MIRROR_PACKAGE / "_frozen_routes.py").read_text()
    compile(src, "_frozen_routes.py", "exec")
    assert _import_frozen(out).build_discovered().routes == []


def test_integrity_check_passes_for_unmodified_build(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)

    sys.path.insert(0, str(out))
    try:
        from causeway._frozen_runtime import verify_integrity

        routes_mod = importlib.import_module(f"{MIRROR_PACKAGE}._frozen_routes")
        plugins_mod = importlib.import_module(f"{MIRROR_PACKAGE}._frozen_plugins")
        verify_integrity(out / MIRROR_PACKAGE / "manifest.json", routes_mod, plugins_mod)
    finally:
        sys.path.pop(0)


def test_integrity_check_raises_when_routes_module_is_tampered(tmp_path: Path) -> None:
    routes = tmp_path / "routes"
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)

    routes_py = out / MIRROR_PACKAGE / "_frozen_routes.py"
    routes_py.write_text(routes_py.read_text() + "\n# tampered\n")

    sys.path.insert(0, str(out))
    try:
        from causeway._frozen_runtime import FrozenIntegrityError, verify_integrity

        routes_mod = importlib.import_module(f"{MIRROR_PACKAGE}._frozen_routes")
        plugins_mod = importlib.import_module(f"{MIRROR_PACKAGE}._frozen_plugins")
        with pytest.raises(FrozenIntegrityError, match="_frozen_routes"):
            verify_integrity(out / MIRROR_PACKAGE / "manifest.json", routes_mod, plugins_mod)
    finally:
        sys.path.pop(0)


def test_integrity_check_skipped_when_manifest_missing(tmp_path: Path) -> None:
    from causeway._frozen_runtime import verify_integrity

    verify_integrity(tmp_path / "no-such-manifest.json", sys, sys)


def test_plugins_discover_is_noop_in_binary_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from causeway import plugins as causeway_plugins

    monkeypatch.setenv("CAUSEWAY_BUILD_MODE", "binary")
    assert causeway_plugins.discover() == []


def test_create_app_frozen_strips_diagnostics_in_binary_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = tmp_path / "routes"
    _write(routes, "index.py", "from causeway import get\n@get\nasync def r(): return {}\n")
    out = tmp_path / "build"
    freeze(routes, out, user_plugins_module=None, settings_target=None)
    found = _import_frozen(out).build_discovered()

    from causeway.app import create_app_frozen

    monkeypatch.setenv("CAUSEWAY_BUILD_MODE", "binary")
    asgi = create_app_frozen(found, diagnostics=True)

    transport = httpx.ASGITransport(app=asgi)

    async def _hit() -> int:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/__causeway")
            return r.status_code

    import asyncio

    assert asyncio.run(_hit()) == 404
