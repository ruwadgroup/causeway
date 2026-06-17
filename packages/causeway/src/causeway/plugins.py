"""Plugin registry.

Two discovery paths feed one registry: entry-point packages (``causeway.plugins``
in their ``pyproject.toml``) auto-load at startup, and ``src/app/plugins.py``
calls :func:`register` directly for adapters that need constructor args.
"""

from __future__ import annotations

import logging
import os
import warnings
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from importlib.metadata import entry_points
from typing import Any

from causeway.contracts import Plugin

_log = logging.getLogger("causeway.plugins")

# Ordered because shutdown runs in reverse-of-registration; keyed by a
# monotonic seq so two instances of the same class don't collide.
_registry: OrderedDict[int, Plugin] = OrderedDict()
_next_id = 0
_started = False
_discovered_groups: set[str] = set()
# Contract versions accepted without warning. Old versions stay on the list
# until ecosystem adapters have caught up.
_ACCEPTED_CONTRACT_VERSIONS = frozenset({"v1.0", "v1.1", "v2.0"})


def register(adapter: Plugin) -> None:
    """Register a plugin adapter. Order matters: shutdown is reverse-of-register.

    Re-registering a plugin instance is a no-op (the registry deduplicates by
    Python identity), so calling ``register(x)`` twice doesn't double-fire
    ``startup``.
    """
    global _next_id
    for existing in _registry.values():
        if existing is adapter:
            return
    _check_version(adapter)
    _registry[_next_id] = adapter
    _next_id += 1


def registered() -> list[Plugin]:
    """Snapshot of currently-registered adapters in registration order."""
    return list(_registry.values())


def clear() -> None:
    """Drop all registrations. For tests only — production code never calls this."""
    global _started
    _registry.clear()
    _discovered_groups.clear()
    _started = False


def discover(group: str = "causeway.plugins") -> list[str]:
    """Auto-load every installed package that ships a ``causeway.plugins`` entry point.

    Each entry point is expected to expose a ``plugin(settings)`` callable that
    itself calls :func:`register`. We swallow ``ImportError`` per-entry so one
    broken plugin doesn't take the whole app down — but we log loudly.
    """
    # Binary builds bake plugins in at codegen time; runtime lookup would
    # re-introduce the supply-chain surface we deliberately removed.
    if os.environ.get("CAUSEWAY_BUILD_MODE") == "binary":
        return []
    if group in _discovered_groups:
        return []
    _discovered_groups.add(group)
    discovered: list[str] = []
    try:
        eps = entry_points(group=group)
    except TypeError:  # Python < 3.10 fallback
        eps = entry_points().get(group, [])  # type: ignore[arg-type]

    for ep in eps:
        try:
            plugin_fn = ep.load()
        except Exception as exc:
            _log.warning("plugin %r failed to load: %s", ep.name, exc)
            continue
        discovered.append(ep.name)
        # Settings is None at discovery; the lifespan layer re-invokes
        # ``settings_fragment`` / ``startup`` once Settings is loaded.
        try:
            plugin_fn(None)
        except Exception as exc:
            _log.warning("plugin %r threw during registration: %s", ep.name, exc)
    return discovered


def env() -> str:
    """Read the current deployment environment.

    Checks ``CAUSEWAY_ENV`` first, falls back to ``ENV``, defaults to ``"dev"``.
    Plugins gate themselves on this for per-env activation::

        if env() == "prod":
            register(S3Storage(bucket=...))
    """
    return os.environ.get("CAUSEWAY_ENV") or os.environ.get("ENV") or "dev"


def check_required_contracts() -> None:
    """Raise if any registered plugin declares ``requires`` that aren't met.

    A plugin lists contract class names it depends on via the ``requires``
    attribute. The registry walks the list at boot, refuses to start if an
    expected contract has no registered adapter, and emits a clear error.
    """
    available: set[str] = set()
    for adapter in _registry.values():
        for cls in type(adapter).__mro__:
            available.add(cls.__name__)

    for adapter in _registry.values():
        required: list[str] = list(getattr(adapter, "requires", ()) or ())
        missing = [r for r in required if r not in available]
        if missing:
            msg = (
                f"plugin {type(adapter).__name__} requires {missing!r}; "
                "no adapter for those contracts is registered"
            )
            raise RuntimeError(msg)


def merge_settings_fragments(settings: Any) -> Any:
    """Apply each plugin's ``settings_fragment()`` to the live ``Settings``.

    A plugin may declare a method::

        def settings_fragment(self) -> dict[str, Any]:
            return {"resend_api_key": SecretStr(...)}

    The returned mapping is shallow-merged onto the settings instance via
    ``setattr``. This is the escape hatch for plugins that need typed config
    fields the app didn't declare.
    """
    if settings is None:
        return settings
    for adapter in _registry.values():
        fn = getattr(adapter, "settings_fragment", None)
        if not callable(fn):
            continue
        try:
            fragment = fn()
        except Exception as exc:
            _log.warning("plugin %s.settings_fragment failed: %s", type(adapter).__name__, exc)
            continue
        if not isinstance(fragment, dict):
            continue
        for key, value in fragment.items():
            if not hasattr(settings, key):
                setattr(settings, key, value)
    return settings


async def startup_all(settings: Any) -> None:
    """Fire every registered plugin's ``startup(settings)`` in registration order."""
    global _started
    if _started:
        return
    check_required_contracts()
    merge_settings_fragments(settings)
    for adapter in list(_registry.values()):
        await _safe_call(adapter, "startup", settings)
    _started = True


async def shutdown_all() -> None:
    """Fire shutdowns in reverse-of-registration order. Errors are logged, not raised."""
    global _started
    if not _started:
        return
    for adapter in reversed(list(_registry.values())):
        await _safe_call(adapter, "shutdown")
    _started = False


async def all_ready() -> dict[str, bool]:
    """Snapshot of each plugin's ``ready()`` state.

    Used by ``/readyz``. The map key is ``f"{type(adapter).__name__}"``; if two
    adapters share a class name we suffix with the registration sequence number.
    """
    out: dict[str, bool] = {}
    seen: dict[str, int] = {}
    for seq, adapter in _registry.items():
        base = type(adapter).__name__
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else f"{base}#{seq}"
        try:
            ready = adapter.ready()
            out[key] = bool(await ready) if _is_awaitable(ready) else bool(ready)
        except Exception:
            out[key] = False
    return out


def _check_version(adapter: Plugin) -> None:
    version = getattr(adapter, "contract_version", None)
    if version is None:
        warnings.warn(
            f"{type(adapter).__name__} registered without contract_version; "
            "future Causeway versions may refuse it",
            stacklevel=3,
        )
        return
    if version not in _ACCEPTED_CONTRACT_VERSIONS:
        warnings.warn(
            f"{type(adapter).__name__} targets contract {version!r}, "
            f"Causeway supports {sorted(_ACCEPTED_CONTRACT_VERSIONS)!r}",
            stacklevel=3,
        )


async def _safe_call(adapter: Plugin, method: str, *args: Any) -> None:
    fn: Callable[..., Any] | None = getattr(adapter, method, None)
    if fn is None:
        return
    try:
        result = fn(*args)
        if _is_awaitable(result):
            await result
    except Exception as exc:
        _log.warning("plugin %s.%s failed: %s", type(adapter).__name__, method, exc)


def _is_awaitable(obj: Any) -> bool:
    return hasattr(obj, "__await__") or isinstance(obj, Awaitable)


__all__ = [
    "all_ready",
    "check_required_contracts",
    "clear",
    "discover",
    "env",
    "merge_settings_fragments",
    "register",
    "registered",
    "shutdown_all",
    "startup_all",
]
