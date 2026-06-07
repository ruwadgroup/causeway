"""AOT freezer: turns the dynamic route tree into static imports Nuitka can follow."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from pathlib import Path, PurePosixPath

from causeway._methods import method_of
from causeway._paths import route_key_for, scope_groups_for, url_for
from causeway.routing import _import_path

MIRROR_PACKAGE = "_causeway_build"
ROUTES_SUBPACKAGE = "_routes"
MANIFEST_FILENAME = "manifest.json"

_NON_ID_RE = re.compile(r"[^A-Za-z0-9_]")


def mangle(name: str) -> str:
    """Map an arbitrary filesystem name to a valid Python identifier.

    >>> mangle("$id")
    '_x24id'
    >>> mangle("(admin)")
    '_x28admin_x29'
    >>> mangle("index")
    'index'
    """
    out = _NON_ID_RE.sub(lambda m: f"_x{ord(m.group()):02x}", name)
    if out and out[0].isdigit():
        out = "_" + out
    return out


def mangle_filename(filename: str) -> str:
    """Mangle the stem of a ``.py`` file, preserving the extension."""
    if filename.endswith(".py"):
        return mangle(filename[:-3]) + ".py"
    return mangle(filename)


@dataclass(slots=True, frozen=True)
class RouteSpec:
    method: str
    url: str
    route_key: str
    source_rel: str
    mirror_module: str
    handler_attr: str
    scope_chain: tuple[str, ...]
    mw_chain: tuple[str, ...]
    scopes: tuple[str, ...]
    refreshes: tuple[str, ...]


@dataclass(slots=True)
class FreezePlan:
    routes_root: Path
    out_dir: Path
    routes: list[RouteSpec] = field(default_factory=list)
    scope_modules: list[str] = field(default_factory=list)
    mw_modules: list[str] = field(default_factory=list)
    startup_modules: list[str] = field(default_factory=list)
    shutdown_modules: list[str] = field(default_factory=list)
    plugin_entry_points: list[tuple[str, str]] = field(default_factory=list)
    user_plugins_module: str | None = None
    settings_target: str | None = None


@dataclass(slots=True, frozen=True)
class FreezeManifest:
    frozen_at: str
    causeway_version: str
    routes_hash: str
    plugins_hash: str
    entry_hash: str
    route_count: int
    plugin_count: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def freeze(
    routes_root: Path,
    out_dir: Path,
    *,
    user_plugins_module: str | None = "app.plugins",
    settings_target: str | None = "app.config:Settings",
) -> FreezeManifest:
    """Mirror, plan, and emit the frozen build tree under ``out_dir``."""
    routes_root = routes_root.resolve()
    out_dir = out_dir.resolve()
    if not routes_root.is_dir():
        msg = f"routes root not found: {routes_root}"
        raise FileNotFoundError(msg)

    pkg_dir = out_dir / MIRROR_PACKAGE
    mirror_root = pkg_dir / ROUTES_SUBPACKAGE

    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text(_GEN_HEADER + "\n")
    _mirror_routes(routes_root, mirror_root)

    plan = FreezePlan(
        routes_root=routes_root,
        out_dir=out_dir,
        user_plugins_module=user_plugins_module,
        settings_target=settings_target,
    )
    _walk(routes_root, routes_root, (), (), plan)
    plan.plugin_entry_points = _collect_plugin_entry_points()

    routes_src = emit_frozen_routes(plan)
    plugins_src = emit_frozen_plugins(plan)
    entry_src = emit_frozen_entry(plan)

    (pkg_dir / "_frozen_routes.py").write_text(routes_src)
    (pkg_dir / "_frozen_plugins.py").write_text(plugins_src)
    (pkg_dir / "_frozen_entry.py").write_text(entry_src)

    manifest = FreezeManifest(
        # Sentinel, not a real timestamp — byte-deterministic output is required
        # for reproducible builds and cosign attestations.
        frozen_at="static",
        causeway_version=_causeway_version(),
        routes_hash=_sha256(routes_src),
        plugins_hash=_sha256(plugins_src),
        entry_hash=_sha256(entry_src),
        route_count=len(plan.routes),
        plugin_count=len(plan.plugin_entry_points),
    )
    (pkg_dir / MANIFEST_FILENAME).write_text(manifest.to_json())
    return manifest


def _mirror_routes(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` as a real package, mangling each filename to a Python identifier."""
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "__init__.py").write_text(_GEN_HEADER + "\n")
    for entry in sorted(src.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name.startswith("_"):
                continue
            _mirror_routes(entry, dst / mangle(entry.name))
        elif entry.suffix == ".py":
            shutil.copyfile(entry, dst / mangle_filename(entry.name))


def _walk(
    routes_root: Path,
    current: Path,
    scope_chain: tuple[str, ...],
    mw_chain: tuple[str, ...],
    plan: FreezePlan,
) -> None:
    new_scope = scope_chain
    new_mw = mw_chain

    scope_file = current / "_scope.py"
    if scope_file.is_file():
        dotted = _dotted_for(routes_root, scope_file)
        plan.scope_modules.append(dotted)
        new_scope = (*new_scope, dotted)
        mod = _import_path(scope_file)
        if callable(getattr(mod, "startup", None)):
            plan.startup_modules.append(dotted)
        if callable(getattr(mod, "shutdown", None)):
            plan.shutdown_modules.append(dotted)

    mw_file = current / "_middleware.py"
    if mw_file.is_file():
        dotted = _dotted_for(routes_root, mw_file)
        plan.mw_modules.append(dotted)
        new_mw = (*new_mw, dotted)

    for entry in sorted(current.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name.startswith("_"):
                continue
            _walk(routes_root, entry, new_scope, new_mw, plan)
            continue
        if entry.suffix != ".py" or entry.name.startswith("_"):
            continue
        _collect_routes(routes_root, entry, new_scope, new_mw, plan)


def _collect_routes(
    routes_root: Path,
    file: Path,
    scope_chain: tuple[str, ...],
    mw_chain: tuple[str, ...],
    plan: FreezePlan,
) -> None:
    rel = file.relative_to(routes_root)
    rel_posix = PurePosixPath(rel.as_posix())
    url = url_for(rel_posix)
    scopes = scope_groups_for(rel_posix)
    mod = _import_path(file)
    mirror_module = _dotted_for(routes_root, file)
    handlers: list[tuple[str, str]] = []
    for name in dir(mod):
        method = method_of(getattr(mod, name))
        if method is None:
            continue
        handlers.append((name, method))
    handlers.sort()
    for handler_attr, handler_method in handlers:
        handler = getattr(mod, handler_attr)
        contract = getattr(handler, "__causeway_contract__", {}) or {}
        plan.routes.append(
            RouteSpec(
                method=handler_method,
                url=url,
                route_key=route_key_for(handler_method, rel_posix),
                source_rel=str(rel),
                mirror_module=mirror_module,
                handler_attr=handler_attr,
                scope_chain=scope_chain,
                mw_chain=mw_chain,
                scopes=scopes,
                refreshes=tuple(contract.get("refreshes") or ()),
            ),
        )


def _dotted_for(routes_root: Path, file: Path) -> str:
    rel = file.relative_to(routes_root).with_suffix("")
    parts = [mangle(p) for p in rel.parts]
    return ".".join([MIRROR_PACKAGE, ROUTES_SUBPACKAGE, *parts])


_log = logging.getLogger("causeway.freeze")


def _collect_plugin_entry_points() -> list[tuple[str, str]]:
    try:
        eps = entry_points(group="causeway.plugins")
    except TypeError:  # pragma: no cover - py<3.10 fallback
        eps = entry_points().get("causeway.plugins", [])  # type: ignore[arg-type]
    # Only bake in plugins that actually import — mirrors the guarded loading in
    # plugins.discover(). Baking an unimportable entry point (e.g. an installed
    # plugin whose optional deps are missing) would emit a frozen build that
    # crashes on import.
    collected: list[tuple[str, str]] = []
    for ep in eps:
        try:
            ep.load()
        except Exception as exc:
            _log.warning("freeze: skipping plugin %r that failed to import: %s", ep.name, exc)
            continue
        collected.append((ep.name, ep.value))
    return sorted(collected)


_GEN_HEADER = (
    '"""AUTO-GENERATED by causeway._freeze. Do not edit by hand."""\n# ruff: noqa\n# type: ignore'
)


def emit_frozen_routes(plan: FreezePlan) -> str:
    lines: list[str] = [_GEN_HEADER, ""]
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from pathlib import Path")
    lines.append(
        "from causeway.routing import "
        "Discovered, DiscoveredRoute, _bind_providers, _collect_idempotency, "
        "_collect_requires, _compose_guards",
    )
    lines.append("")

    all_modules = sorted(
        set(plan.scope_modules) | set(plan.mw_modules) | {r.mirror_module for r in plan.routes},
    )
    for dotted in all_modules:
        lines.append(f"import {dotted} as {_alias(dotted)}")
    lines.append("")

    # Hoist provider/middleware lookups to module-load so build_discovered()
    # is a flat reference walk, not a dir() scan per call.
    for dotted in sorted(set(plan.scope_modules)):
        alias = _alias(dotted)
        lines.append(f"_P_{alias} = {{")
        lines.append(f"    getattr({alias}, _n).__causeway_provide__: getattr({alias}, _n)")
        lines.append(f"    for _n in dir({alias})")
        lines.append(
            f'    if getattr(getattr({alias}, _n, None), "__causeway_provide__", None)',
        )
        lines.append("}")
    for dotted in sorted(set(plan.mw_modules)):
        alias = _alias(dotted)
        lines.append(f'_MW_{alias} = list(getattr({alias}, "middleware", ()) or [])')
    lines.append("")

    lines.append("def build_discovered() -> Discovered:")
    lines.append("    routes: list[DiscoveredRoute] = []")
    for spec in plan.routes:
        lines.extend(_emit_route_block(spec))

    # Startup outer->inner, shutdown inner->outer — mirrors routing.discover.
    lines.append("    startup_hooks = [")
    for dotted in plan.startup_modules:
        lines.append(f"        {_alias(dotted)}.startup,")
    lines.append("    ]")
    lines.append("    shutdown_hooks = [")
    for dotted in reversed(plan.shutdown_modules):
        lines.append(f"        {_alias(dotted)}.shutdown,")
    lines.append("    ]")
    lines.append(
        "    return Discovered("
        "routes=routes, startup_hooks=startup_hooks, shutdown_hooks=shutdown_hooks)",
    )
    lines.append("")
    return "\n".join(lines)


def _emit_route_block(spec: RouteSpec) -> list[str]:
    lines: list[str] = [f"    # {spec.method} {spec.url}  <-  {spec.source_rel}"]
    providers_expr = (
        "{" + ", ".join(f"**_P_{_alias(m)}" for m in spec.scope_chain) + "}"
        if spec.scope_chain
        else "{}"
    )
    mw_expr = " + ".join(f"_MW_{_alias(m)}" for m in spec.mw_chain) if spec.mw_chain else "[]"
    handler_ref = f"{_alias(spec.mirror_module)}.{spec.handler_attr}"
    lines.append(f"    _p = {providers_expr}")
    lines.append(f"    _mw = {mw_expr}")
    lines.append(f"    _h = _compose_guards(_bind_providers({handler_ref}, _p), _mw)")
    lines.append(
        f"    routes.append(DiscoveredRoute("
        f"method={spec.method!r}, path={spec.url!r}, route_key={spec.route_key!r}, handler=_h, "
        f"middleware=_mw, providers=_p, "
        f"source=Path({spec.source_rel!r}), scopes={spec.scopes!r}, "
        f"refreshes={spec.refreshes!r}, requires=_collect_requires(_mw), "
        f"idempotency=_collect_idempotency(_mw, {spec.method!r})))",
    )
    return lines


def emit_frozen_plugins(plan: FreezePlan) -> str:
    lines: list[str] = [_GEN_HEADER, ""]
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from typing import Any")
    lines.append("")

    ep_aliases: list[str] = []
    for name, target in plan.plugin_entry_points:
        module, _, attr = target.partition(":")
        attr = attr or "plugin"
        alias = f"_EP_{mangle(name)}"
        ep_aliases.append(alias)
        lines.append(f"from {module} import {attr} as {alias}")
    lines.append("")

    if plan.user_plugins_module:
        # Imported for its top-level register() side effects.
        lines.append("try:")
        lines.append(f"    import {plan.user_plugins_module} as _USER_PLUGINS  # noqa: F401")
        lines.append("except ImportError:")
        lines.append("    _USER_PLUGINS = None  # type: ignore[assignment]")
        lines.append("")

    lines.append("_ENTRYPOINT_PLUGINS = [" + ", ".join(ep_aliases) + "]")
    lines.append("")
    lines.append("def load_all(settings: Any) -> None:")
    lines.append("    for fn in _ENTRYPOINT_PLUGINS:")
    lines.append("        fn(settings)")
    lines.append("")
    return "\n".join(lines)


def emit_frozen_entry(plan: FreezePlan) -> str:
    settings_module, _, settings_class = (plan.settings_target or "").partition(":")
    has_settings = bool(settings_module and settings_class)

    lines: list[str] = [_GEN_HEADER, ""]
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import os")
    lines.append("from pathlib import Path")
    lines.append("")
    # Must be set before any causeway.* import — the gates in causeway.app and
    # causeway.plugins are read at import time.
    lines.append('os.environ.setdefault("CAUSEWAY_BUILD_MODE", "binary")')
    lines.append("")
    lines.append("from causeway.app import create_app_frozen")
    lines.append("from causeway._frozen_runtime import verify_integrity")
    lines.append(f"from {MIRROR_PACKAGE} import _frozen_routes, _frozen_plugins")
    if has_settings:
        lines.append(f"from {settings_module} import {settings_class}")
    lines.append("")
    lines.append("def main() -> int:")
    lines.append(
        f"    verify_integrity(Path(__file__).parent / {MANIFEST_FILENAME!r}, "
        "_frozen_routes, _frozen_plugins)",
    )
    if has_settings:
        lines.append(f"    settings = {settings_class}()")
    else:
        lines.append("    settings = None")
    lines.append("    _frozen_plugins.load_all(settings)")
    lines.append(
        "    app = create_app_frozen(_frozen_routes.build_discovered(), settings=settings)"
    )
    lines.append("    import uvicorn")
    lines.append('    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104')
    lines.append('    port = int(os.environ.get("PORT", "8000"))')
    lines.append("    uvicorn.run(app, host=host, port=port)")
    lines.append("    return 0")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    raise SystemExit(main())")
    lines.append("")
    return "\n".join(lines)


def _alias(dotted: str) -> str:
    return dotted.replace(".", "__")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _causeway_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("causeway")
    except PackageNotFoundError:  # pragma: no cover - dev install edge
        return "0.0.0+dev"


__all__ = [
    "MANIFEST_FILENAME",
    "MIRROR_PACKAGE",
    "ROUTES_SUBPACKAGE",
    "FreezeManifest",
    "FreezePlan",
    "RouteSpec",
    "emit_frozen_entry",
    "emit_frozen_plugins",
    "emit_frozen_routes",
    "freeze",
    "mangle",
    "mangle_filename",
]
