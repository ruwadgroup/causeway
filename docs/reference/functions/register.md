# `register`

Register a plugin adapter with the framework.

```python
# src/app/plugins.py
from causeway import register
from causeway.contrib.dramatiq import DramatiqAdapter

register(DramatiqAdapter(broker_url="redis://localhost"))
```

## Signature

```python
register(adapter: Plugin) -> None
```

`adapter` is any object that satisfies the `causeway.contracts.Plugin` Protocol — i.e. has `startup`, `shutdown`, `ready` (all async) and a `contract_version` class attribute.

## Behavior

- Order is preserved. Shutdown runs in reverse-of-registration order.
- Re-registering the same instance is a no-op (deduplication by Python identity).
- The adapter's `contract_version` is checked against the loaded Causeway version; a warning fires on mismatch.
- The actual lifecycle (`startup`, `ready`, `shutdown`) is driven later by the framework — `register()` just inserts into the registry.

## Where to call it

In `src/app/plugins.py`. Causeway loads this module once at boot, after `src/app/config.py`.

Bundled adapters under `causeway.contrib` are usually registered here directly.
For third-party entry-point plugins, the package's own `plugin(settings)`
function calls `register()` for you — see [Plugin authoring](../../app/plugin-authoring.md).

## Common patterns

**Per-environment activation:**

```python
from causeway import register, env

if env() == "prod":
    register(S3Storage(bucket="..."))
else:
    register(LocalStorage(path="./tmp/uploads"))
```

**Overriding an entry-point plugin:**

Register your own adapter for the same contract after the entry-point scan — later registrations override earlier ones for the same contract slot.

## See also

- [Plugins overview](../../app/plugins.md)
- [`env`](./env.md)
- [Contracts](../classes/contracts.md)
