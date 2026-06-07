# `causeway plugins`

List currently-registered plugin adapters.

```bash
$ causeway plugins
                       Registered plugins
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Adapter          ┃ Contract version  ┃ Module               ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ DramatiqAdapter  │ v1.0              │ causeway.contrib.dramatiq  │
│ S3Storage        │ v1.0              │ causeway.contrib.s3      │
└──────────────────┴───────────────────┴──────────────────────┘
```

## Synopsis

```
causeway plugins
```

No arguments. Prints a table of adapters in registration order.

## When the registry is empty

```
no plugins registered
```

If `src/app/plugins.py` runs `register(...)` but you don't see entries here, check that:

- The import resolves (no error in `plugins.py`).
- The adapter satisfies the `Plugin` Protocol (has `startup`, `shutdown`, `ready`, `contract_version`).

## Live view

The same data is available at <http://127.0.0.1:8000/__causeway> while `causeway dev` is running.

## See also

- [Plugins overview](../../app/plugins.md)
- [`register`](../functions/register.md)
