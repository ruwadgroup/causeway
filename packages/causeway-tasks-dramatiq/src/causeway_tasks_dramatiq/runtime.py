"""Runtime bootstrap used by Dramatiq and Periodiq worker processes."""

from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import Iterable

from dramatiq.broker import Broker

from causeway.config import load_settings
from causeway.plugins import register, registered, startup_all

from causeway_tasks_dramatiq import DramatiqAdapter

_DEFAULT_APP_TARGET = "app:app"
_DEFAULT_TASK_MODULES = ("app.tasks",)


def bootstrap(
    *,
    app_target: str | None = None,
    task_modules: Iterable[str] | None = None,
    import_modules: Iterable[str] | None = None,
) -> Broker:
    """Load a Causeway app and return the configured Dramatiq broker.

    Importing ``app_target`` discovers Causeway plugins by convention. We then
    import task modules so ``@task`` / ``@cron`` decorators run, start plugins
    with app settings, and return the broker that Dramatiq/Periodiq expect.
    """
    target = (
        app_target or os.environ.get("CAUSEWAY_DRAMATIQ_APP") or _DEFAULT_APP_TARGET
    )
    tasks = tuple(
        task_modules or _env_list("CAUSEWAY_DRAMATIQ_TASKS", _DEFAULT_TASK_MODULES)
    )
    imports = tuple(import_modules or _env_list("CAUSEWAY_DRAMATIQ_IMPORTS", ()))

    app_module, app_attr = _split_target(target)
    app_mod = importlib.import_module(app_module)
    getattr(app_mod, app_attr)
    for module in (*tasks, *imports):
        _import_optional_default(module)

    _ensure_adapter()
    settings = load_settings(app_module)
    asyncio.run(startup_all(settings))

    adapter = _dramatiq_adapter()
    broker = adapter.broker
    if broker is None:
        msg = "DramatiqAdapter did not start a broker; check plugin startup logs"
        raise RuntimeError(msg)
    return broker


def _env_list(name: str, default: Iterable[str]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return tuple(default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _split_target(target: str) -> tuple[str, str]:
    module, sep, attr = target.partition(":")
    if not sep or not module or not attr:
        msg = f"app target must be 'module:attr', got {target!r}"
        raise ValueError(msg)
    return module, attr


def _import_optional_default(module: str) -> None:
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if module in _DEFAULT_TASK_MODULES and exc.name == module:
            return
        raise


def _ensure_adapter() -> None:
    if any(isinstance(adapter, DramatiqAdapter) for adapter in registered()):
        return
    register(DramatiqAdapter())


def _dramatiq_adapter() -> DramatiqAdapter:
    for adapter in reversed(registered()):
        if isinstance(adapter, DramatiqAdapter):
            return adapter
    msg = "No DramatiqAdapter registered"
    raise RuntimeError(msg)


__all__ = ["bootstrap"]
