# Writing a new official adapter

The on-ramp for adding a bundled adapter under `causeway.contrib`. Aimed at
maintainers, not external authors — external plugin authors should read
[Plugins](../app/plugins.md).

## Decide on the name

Naming convention is the shortest clear backend name:

- Extra: `causeway[s3]`, `causeway[redis]`, `causeway[dramatiq]`.
- Module: `causeway.contrib.s3`, `causeway.contrib.redis`, `causeway.contrib.dramatiq`.
- Class: explicit CamelCase (`S3Storage`, `RedisKV`, `DramatiqAdapter`).

If your role is new, open a Discussion first. Adding a contract family is a
bigger decision than adding an implementation.

## Add the module

Add the implementation under `packages/causeway/src/causeway/contrib/`:

```
packages/causeway/
├── src/causeway/contrib/<name>.py
└── tests/contrib/test_<name>.py
```

If the adapter needs multiple files, use a subpackage:

```
src/causeway/contrib/dramatiq/
├── __init__.py
├── cli.py
└── runtime.py
```

## Implement the contract

Pick the protocol from `causeway.contracts` and implement it. Minimum surface:

```python
# packages/causeway/src/causeway/contrib/<name>.py
from typing import Any, ClassVar
from causeway.contracts import <Role>   # e.g. TaskAdapter, Storage, Mailer


class <Impl><Role>Adapter:
    """One sentence on what backend this wraps."""

    contract_version: ClassVar[str] = "v1.0"

    def __init__(self, *args, **kwargs) -> None: ...

    async def startup(self, settings: Any) -> None: ...
    async def shutdown(self) -> None: ...
    async def ready(self) -> bool:
        return True

    # contract-specific methods …


def plugin(settings: Any) -> None:
    """Settings-aware helper. Reads settings, calls register()."""
    from causeway import register

    field = getattr(settings, "<your_setting>", None)
    if not field:
        return   # not configured for this app; skip silently

    register(<Impl><Role>Adapter(<field>=field))
```

Notes:

- `startup(settings)` runs after Settings is loaded — that's where you open connection pools, create clients, etc.
- `shutdown()` runs in reverse-of-registration order.
- `ready()` is polled by `/readyz`. Return `False` while the connection isn't established yet; return `True` once it is.
- Don't raise from `startup` for missing config. Skip silently and let `/readyz` reflect the unready state, **or** raise with a message that points at the missing setting.

## Add a `settings_fragment` (optional)

If your plugin needs settings fields the app didn't declare:

```python
class <Impl><Role>Adapter:
    def settings_fragment(self) -> dict[str, Any]:
        return {"<your_setting>": SecretStr(...)}
```

The registry merges these into `Settings` at startup. Use `SecretStr` / `SecretBytes` for anything secret — those fields are stripped from `/__causeway` and the generated TS client automatically.

## Test the adapter

Minimum test coverage:

1. **Smoke test** — `adapter = <Adapter>(...); await adapter.startup(None); assert await adapter.ready()`.
2. **Contract round-trip** — implement the protocol's main verbs and assert against the in-memory reference where possible.
3. **`plugin(settings)` helper** — pass a minimal Settings-like object and assert `register` was called.

If the adapter wraps a network service (Redis, S3, Postgres), use a stub or a `testcontainers` integration test. Don't require live credentials in CI.

## Add dependencies

Add runtime dependencies under `[project.optional-dependencies]` in
`packages/causeway/pyproject.toml`. Add test-only dependencies under
`[dependency-groups] dev`.

## Document it

In the relevant docs page:

- One paragraph on what backend this wraps and why someone would pick it over alternatives.
- The settings fields it reads.
- A minimal `register(...)` example for the explicit-registration path.

If your adapter has noteworthy contract behavior (cron not supported, eager mode uses stub broker, ready check is best-effort, etc.), say so explicitly.

## Promote in the main docs

If the adapter is meant to be official:

1. Add it to the built-in extras list in [Plugins](../app/plugins.md).
2. Mention the extra in the relevant user docs.
3. Update [`ROADMAP.md`](../../ROADMAP.md) — move the adapter from "planned" to "shipped".

If it's a third-party plugin (not part of the official set), the right place is the curated registry on the docs site (forthcoming) — not the in-repo lists.

## Ship it

Bundled adapters ship with `causeway` and follow the core release flow.
Conventional Commits scope the bump, release-please opens the release PR, and
the publish workflow ships one PyPI package.
