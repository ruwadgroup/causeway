"""Causeway CLI.

- ``causeway new <name>``        — scaffold a project from the template tree.
- ``causeway dev``               — owned uvicorn dev server + smart route hot-swap.
- ``causeway codegen``           — emit the typed TypeScript client directory.
- ``causeway build``             — IR + generated client directory + wheel. ``--binary`` AOT-compiles via Nuitka.
- ``causeway freeze``            — emit the AOT build tree without compiling.
- ``causeway plugins``           — list registered adapters.
- ``causeway diff``              — compare two IR snapshots; non-zero exit on breaking changes.
- ``causeway ir``                — dump the route IR as JSON for diffing / external tooling.
- ``causeway inspect``           — dump the Causeway App Graph.
- ``causeway deploy <target>``   — invoke the matching ``DeployTarget`` adapter.
- ``causeway plugin new <name>`` — scaffold a sibling plugin package.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="causeway",
    help="A lean backend framework for type-safe Python APIs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def version() -> None:
    """Print the installed version."""
    try:
        v = metadata.version("causeway")
    except metadata.PackageNotFoundError:  # pragma: no cover - dev install edge
        v = "unknown"
    console.print(v)


@app.command(name="new")
def new(
    name: Annotated[str, typer.Argument(help="Project directory name.")],
    target: Annotated[
        Path | None,
        typer.Option("--target", "-t", help="Parent directory; defaults to the cwd."),
    ] = None,
) -> None:
    """Scaffold a new Causeway app.

    Creates ``<name>/`` with ``pyproject.toml``, ``causeway.toml``, an ``.env``
    template, and the canonical ``src/app/`` tree: ``config.py``,
    ``plugins.py``, ``lifespan.py``, ``routes/_middleware.py``,
    ``routes/index.py``, ``tests/test_smoke.py``.
    """
    parent = target or Path.cwd()
    root = parent / name
    if root.exists():
        console.print(f"[red]error[/red]: {root} already exists")
        raise typer.Exit(code=1)

    from causeway._scaffold import scaffold

    scaffold(root, name)
    console.print(f"[green]created[/green] {root}")
    console.print("\nNext steps:")
    console.print(f"  cd {name}")
    console.print("  uv sync")
    console.print("  causeway dev")


@app.command()
def dev(
    module: Annotated[str, typer.Option(help="ASGI app module path.")] = "app:app",
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
) -> None:
    """Run the owned dev server with smart route hot swapping."""
    from causeway.dev import run_causeway_dev

    os.environ.setdefault("CAUSEWAY_ENV", "dev")
    project = Path.cwd()
    run_causeway_dev(
        module=module,
        host=host,
        port=port,
        project=project,
        routes_root=_discover_routes(project),
    )


@app.command()
def build(
    target: Annotated[
        Path,
        typer.Option("--target", "-o", help="Output directory."),
    ] = Path("dist"),
    module: Annotated[
        str,
        typer.Option(
            "--module",
            "-m",
            help="``module:attr`` of your ASGI app to introspect for codegen.",
        ),
    ] = "app:app",
    binary: Annotated[
        bool,
        typer.Option(
            "--binary",
            help="Build a self-contained AOT-compiled binary instead of a wheel. "
            "Requires `causeway[binary]`.",
        ),
    ] = False,
    sign: Annotated[
        bool,
        typer.Option("--sign", help="Sign the binary with cosign sign-blob (--binary only)."),
    ] = False,
    sbom: Annotated[
        bool,
        typer.Option("--sbom", help="Emit a CycloneDX SBOM via syft (--binary only)."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Run freeze + plan but skip the Nuitka build (--binary only).",
        ),
    ] = False,
) -> None:
    """Produce the deployable artifact.

    Default build emits three outputs into ``<target>/``: the IR snapshot
    (``ir.json``), the generated TypeScript client directory (``client/``), and
    a Python wheel.

    ``--binary`` switches to a self-contained, AOT-compiled binary
    (single-file, standalone). Requires ``pip install causeway[binary]``.

    Routes, plugins, and settings paths are discovered by convention
    (``app/routes``, ``app/plugins.py``, ``app/config.py:Settings``).
    """
    if binary:
        _build_binary(target=target, sign=sign, sbom=sbom, dry_run=dry_run)
        return

    target.mkdir(parents=True, exist_ok=True)
    routes = _write_client(module, target / "client")
    console.print(f"[green]codegen[/green] -> {target / 'client'} ({routes} routes)")
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(target)],
        check=False,
    )
    console.print(f"[green]built[/green] -> {target}")


def _build_binary(*, target: Path, sign: bool, sbom: bool, dry_run: bool) -> None:
    from causeway._binary import build_binary

    project = Path.cwd()
    artifact = build_binary(
        project_root=project,
        out=target,
        routes_root=_discover_routes(project),
        user_plugins_module=_discover_user_plugins(project),
        settings_target=_discover_settings(project),
        sign=sign,
        sbom=sbom,
        dry_run=dry_run,
    )
    if dry_run:
        console.print("[yellow]dry run[/yellow] — freeze complete, Nuitka skipped")
        return
    console.print(
        f"[green]built[/green] {artifact.path} ({artifact.size_mb:.1f} MB)",
    )
    if artifact.signature_path:
        console.print(f"  signature: {artifact.signature_path}")
    if artifact.sbom_path:
        console.print(f"  sbom: {artifact.sbom_path}")


def _discover_routes(project: Path) -> Path:
    """Convention: ``app/routes`` under cwd or ``src/``."""
    for candidate in (project / "app" / "routes", project / "src" / "app" / "routes"):
        if candidate.is_dir():
            return candidate
    console.print("[red]error[/red]: no routes directory found (looked for app/routes)")
    raise typer.Exit(code=1)


def _discover_user_plugins(project: Path) -> str | None:
    """Convention: ``app/plugins.py``. None for minimal apps."""
    for candidate in (project / "app" / "plugins.py", project / "src" / "app" / "plugins.py"):
        if candidate.is_file():
            return "app.plugins"
    return None


def _discover_settings(project: Path) -> str | None:
    """Convention: ``app/config.py`` exporting ``Settings``. None for minimal apps."""
    for candidate in (project / "app" / "config.py", project / "src" / "app" / "config.py"):
        if candidate.is_file():
            return "app.config:Settings"
    return None


@app.command()
def freeze(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output directory for the frozen build tree."),
    ] = Path(".causeway/build"),
) -> None:
    """Generate the AOT-frozen build tree. Standalone of ``causeway build --binary``.

    Routes, plugins, and settings paths are discovered by convention
    (``app/routes``, ``app/plugins.py``, ``app/config.py:Settings``).
    """
    from causeway._freeze import freeze as _freeze

    project = Path.cwd()
    manifest = _freeze(
        routes_root=_discover_routes(project),
        out_dir=out,
        user_plugins_module=_discover_user_plugins(project),
        settings_target=_discover_settings(project),
    )
    console.print(
        f"[green]frozen[/green] {manifest.route_count} route(s), "
        f"{manifest.plugin_count} plugin(s) -> {out}/_causeway_build/",
    )


@app.command()
def plugins() -> None:
    """List currently-registered plugin adapters."""
    from causeway.plugins import registered

    table = Table(title="Registered plugins")
    table.add_column("Adapter")
    table.add_column("Contract version")
    table.add_column("Module")

    items = registered()
    if not items:
        console.print("[dim]no plugins registered[/dim]")
        return
    for adapter in items:
        cls = type(adapter)
        table.add_row(
            cls.__name__,
            getattr(adapter, "contract_version", "?"),
            cls.__module__,
        )
    console.print(table)


@app.command()
def codegen(
    module: Annotated[
        str,
        typer.Argument(help="``module:attr`` of your ASGI app."),
    ] = "app:app",
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where to write the generated client directory."),
    ] = Path("src/lib/causeway/client"),
) -> None:
    """Emit the typed TypeScript client directory and exit."""
    routes = _write_client(module, out)
    console.print(f"[green]wrote[/green] {out} ({routes} routes)")


@app.command()
def ir(
    module: Annotated[
        str,
        typer.Argument(help="``module:attr`` of your ASGI app."),
    ] = "app:app",
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where to write the IR snapshot."),
    ] = Path("causeway-ir.json"),
) -> None:
    """Emit the route IR as a JSON snapshot for diffing / external tooling."""
    from causeway._runtime.ir import build_ir

    app_obj = _load_runtime_app(module)
    ir_value = build_ir(app_obj)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(ir_value), indent=2), encoding="utf-8")
    console.print(f"[green]wrote[/green] {out} ({len(ir_value.routes)} routes)")


@app.command(name="inspect")
def inspect_graph(
    module: Annotated[
        str,
        typer.Argument(help="``module:attr`` of your ASGI app."),
    ] = "app:app",
    json_: Annotated[bool, typer.Option("--json", help="Print raw graph JSON.")] = False,
) -> None:
    """Inspect the Causeway App Graph."""
    from causeway.graph import build_graph

    app_obj = _load_runtime_app(module)
    graph = app_obj.graph or build_graph(app_obj)
    data = graph.to_dict()
    if json_:
        print(json.dumps(data, indent=2))
        return

    table = Table(title="Causeway App Graph")
    table.add_column("Method")
    table.add_column("Route Key")
    table.add_column("HTTP Path")
    table.add_column("Refreshes")
    for route in data["routes"]:
        table.add_row(
            str(route["method"]),
            str(route["route_key"]),
            str(route["http_path"]),
            ", ".join(str(value) for value in route["refreshes"]),
        )
    console.print(table)


@app.command()
def openapi(
    module: Annotated[
        str,
        typer.Argument(help="``module:attr`` of your ASGI app."),
    ] = "app:app",
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where to write the OpenAPI document."),
    ] = Path("openapi.json"),
    title: Annotated[str, typer.Option(help="OpenAPI document title.")] = "Causeway API",
    api_version: Annotated[
        str, typer.Option("--api-version", help="OpenAPI document version.")
    ] = "0.0.0",
) -> None:
    """Emit an OpenAPI 3.1 document alongside the TS client — for non-Causeway consumers."""
    from causeway._runtime.ir import build_ir
    from causeway._runtime.openapi import write as write_openapi

    app_obj = _load_runtime_app(module)
    ir_value = build_ir(app_obj)
    write_openapi(ir_value, out, title=title, version=api_version)
    console.print(f"[green]wrote[/green] {out} ({len(ir_value.routes)} routes)")


@app.command()
def swift(
    module: Annotated[
        str,
        typer.Argument(help="``module:attr`` of your ASGI app."),
    ] = "app:app",
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where to write the Swift client."),
    ] = Path("Causeway.swift"),
) -> None:
    """Generate a Swift client off the same IR."""
    from causeway._runtime.ir import build_ir
    from causeway._runtime.polyglot import write_swift

    app_obj = _load_runtime_app(module)
    ir_value = build_ir(app_obj)
    write_swift(ir_value, out)
    console.print(f"[green]wrote[/green] {out} ({len(ir_value.routes)} routes)")


@app.command()
def kotlin(
    module: Annotated[
        str,
        typer.Argument(help="``module:attr`` of your ASGI app."),
    ] = "app:app",
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where to write the Kotlin client."),
    ] = Path("Causeway.kt"),
    package: Annotated[
        str, typer.Option(help="Kotlin package name for the generated code.")
    ] = "com.causeway.generated",
) -> None:
    """Generate a Kotlin client off the same IR."""
    from causeway._runtime.ir import build_ir
    from causeway._runtime.polyglot import write_kotlin

    app_obj = _load_runtime_app(module)
    ir_value = build_ir(app_obj)
    write_kotlin(ir_value, out, package=package)
    console.print(f"[green]wrote[/green] {out} ({len(ir_value.routes)} routes)")


@app.command()
def diff(
    baseline: Annotated[Path, typer.Argument(help="Baseline IR snapshot.")],
    candidate: Annotated[Path, typer.Argument(help="Candidate IR snapshot.")],
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output format: human | json | github"),
    ] = "human",
) -> None:
    """Compare two IR snapshots and exit non-zero on breaking changes."""
    from causeway._runtime.diff import (
        diff_ir,
        format_github,
        format_human,
        format_json,
        load_ir,
    )

    result = diff_ir(load_ir(baseline), load_ir(candidate))
    if fmt == "json":
        console.print(format_json(result))
    elif fmt == "github":
        # GitHub annotation commands go to stdout exactly as-is.
        print(format_github(result))
    else:
        console.print(format_human(result))
    if result.breaking:
        raise typer.Exit(code=1)


def _load_runtime_app(target: str) -> Any:
    """Resolve ``module:attr`` to the inner runtime App.

    Accepts either a raw runtime ``App`` or the wrapped object returned by
    ``causeway.create_app`` — ExceptionShield → Starlette → Mount → App.
    """
    from causeway._runtime import App as RuntimeApp

    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise typer.BadParameter("Target must be 'module:attr', e.g. 'app:app'.")
    obj = getattr(importlib.import_module(module_name), attr)
    cursor: Any = obj
    for _ in range(8):  # bounded — guards against ASGI shapes we don't recognize
        if isinstance(cursor, RuntimeApp):
            return cursor
        inner = getattr(cursor, "app", None)
        if inner is not None:
            cursor = inner
            continue
        for route in getattr(cursor, "routes", ()) or ():
            mounted = getattr(route, "app", None)
            if isinstance(mounted, RuntimeApp):
                return mounted
        break
    raise typer.BadParameter(
        f"{target} resolved to {type(obj).__name__}, not a causeway.App or a "
        "create_app() result. Point at the module:attr that exports either.",
    )


def _write_client(target: str, out: Path) -> int:
    from causeway._runtime.codegen import write as write_client
    from causeway._runtime.ir import build_ir

    app_obj = _load_runtime_app(target)
    ir_value = build_ir(app_obj)
    write_client(ir_value, out)
    return len(ir_value.routes)


@app.command()
def deploy(
    target: Annotated[str, typer.Argument(help="Deploy target name (e.g. docker, fly, modal).")],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("dist"),
) -> None:
    """Invoke the registered ``DeployTarget`` adapter matching ``target``.

    Discovery: scan registered plugins for one whose class name matches
    ``<Target>Deploy`` (case-insensitive). The adapter writes its manifest
    files into ``output`` and pushes via its ``push()`` if available.
    """
    from causeway.plugins import registered

    wanted = f"{target.lower()}deploy"
    adapter = next(
        (p for p in registered() if type(p).__name__.lower() == wanted),
        None,
    )
    if adapter is None:
        console.print(
            f"[red]no DeployTarget registered for {target!r}[/red]. "
            f"Install the matching ``causeway[{target}]`` extra and register it in ``plugins.py``.",
        )
        raise typer.Exit(code=1)

    package = getattr(adapter, "package", None)
    if callable(package):
        package(target_dir=output)
    console.print(f"[green]packaged[/green] -> {output}")


@app.command(name="plugin")
def plugin_new(
    action: Annotated[str, typer.Argument(help="Subcommand; only 'new' is supported.")],
    name: Annotated[
        str,
        typer.Argument(help="Plugin package name (e.g. causeway-contrib-search)."),
    ],
    target: Annotated[Path | None, typer.Option("--target", "-t")] = None,
) -> None:
    """Scaffold a new Causeway plugin package.

    ``causeway plugin new causeway-contrib-search`` creates a sibling package with
    a ``pyproject.toml``, entry-point wiring, and a smoke test placeholder.
    """
    if action != "new":
        console.print(f"[red]unknown plugin subcommand:[/red] {action!r}")
        raise typer.Exit(code=1)

    parent = target or Path.cwd()
    root = parent / name
    if root.exists():
        console.print(f"[red]error[/red]: {root} already exists")
        raise typer.Exit(code=1)

    from causeway._scaffold import scaffold_plugin

    scaffold_plugin(root, name)
    console.print(f"[green]created[/green] plugin {name} at {root}")


def main() -> None:
    """Entry point for the ``causeway`` console script."""
    app()


if __name__ == "__main__":
    main()
