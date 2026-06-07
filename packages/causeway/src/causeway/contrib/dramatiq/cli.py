"""CLI helpers for running Causeway tasks on Dramatiq."""

from __future__ import annotations

import os
from typing import Annotated

import typer

_BROKER_TARGET = "causeway.contrib.dramatiq.worker:broker"
_DEFAULT_APP_TARGET = "app:app"
_DEFAULT_TASK_MODULES = ("app.tasks",)

cli = typer.Typer(
    name="causeway-dramatiq",
    help="Run Causeway background workers and cron schedulers on Dramatiq.",
    no_args_is_help=True,
    add_completion=False,
)


@cli.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def worker(
    ctx: typer.Context,
    app_target: Annotated[
        str,
        typer.Option("--app", help="Causeway ASGI app target, e.g. app:app."),
    ] = _DEFAULT_APP_TARGET,
    tasks: Annotated[
        list[str] | None,
        typer.Option("--tasks", "-t", help="Task module/package to import."),
    ] = None,
    import_modules: Annotated[
        list[str] | None,
        typer.Option("--import", help="Additional module/package to import."),
    ] = None,
    processes: Annotated[
        int | None,
        typer.Option("--processes", "-p", help="Dramatiq worker process count."),
    ] = None,
    threads: Annotated[
        int | None,
        typer.Option("--threads", help="Dramatiq threads per process."),
    ] = None,
    queues: Annotated[
        list[str] | None,
        typer.Option("--queue", "-Q", help="Queue to consume; repeatable."),
    ] = None,
    watch: Annotated[
        list[str] | None,
        typer.Option("--watch", help="Directory to watch with Dramatiq reload."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose Dramatiq logs."),
    ] = False,
) -> None:
    """Run a Dramatiq worker after bootstrapping the Causeway app."""
    _configure_env(app_target=app_target, tasks=tasks, import_modules=import_modules)
    args: list[str] = []
    if processes is not None:
        args.extend(["--processes", str(processes)])
    if threads is not None:
        args.extend(["--threads", str(threads)])
    if queues:
        args.append("--queues")
        args.extend(queues)
    for path in watch or ():
        args.extend(["--watch", path])
    if verbose:
        args.append("--verbose")
    args.extend(ctx.args)
    args.append(_BROKER_TARGET)
    _run_dramatiq(args)


@cli.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def scheduler(
    ctx: typer.Context,
    app_target: Annotated[
        str,
        typer.Option("--app", help="Causeway ASGI app target, e.g. app:app."),
    ] = _DEFAULT_APP_TARGET,
    tasks: Annotated[
        list[str] | None,
        typer.Option("--tasks", "-t", help="Task module/package to import."),
    ] = None,
    import_modules: Annotated[
        list[str] | None,
        typer.Option("--import", help="Additional module/package to import."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose Periodiq logs."),
    ] = False,
) -> None:
    """Run the Periodiq scheduler for Causeway ``@cron`` tasks."""
    _configure_env(app_target=app_target, tasks=tasks, import_modules=import_modules)
    args: list[str] = []
    if verbose:
        args.append("--verbose")
    args.extend(ctx.args)
    args.append(_BROKER_TARGET)
    _run_periodiq(args)


def _configure_env(
    *,
    app_target: str,
    tasks: list[str] | None,
    import_modules: list[str] | None,
) -> None:
    os.environ.setdefault("CAUSEWAY_ENV", "dev")
    os.environ["CAUSEWAY_DRAMATIQ_APP"] = app_target
    os.environ["CAUSEWAY_DRAMATIQ_TASKS"] = ",".join(
        _normalize_modules(tasks, default=_DEFAULT_TASK_MODULES),
    )
    os.environ["CAUSEWAY_DRAMATIQ_IMPORTS"] = ",".join(
        _normalize_modules(import_modules, default=()),
    )


def _normalize_modules(values: list[str] | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = values if values else list(default)
    modules: list[str] = []
    for value in raw:
        modules.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(modules)


def _run_dramatiq(args: list[str]) -> None:
    from dramatiq.cli import main, make_argument_parser

    parsed = make_argument_parser().parse_args(args)  # type: ignore[no-untyped-call]
    raise typer.Exit(code=main(parsed) or 0)  # type: ignore[no-untyped-call]


def _run_periodiq(args: list[str]) -> None:
    import periodiq  # type: ignore[import-untyped]

    parsed = periodiq.make_argument_parser().parse_args(args)
    raise typer.Exit(code=periodiq.main(parsed) or 0)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
