# `env`

Return the current deployment environment as a string.

```python
from causeway import env

env()   # "dev" | "staging" | "prod" | ...
```

## Signature

```python
env() -> str
```

## Resolution order

1. `$CAUSEWAY_ENV`
2. `$ENV`
3. `"dev"` (default)

## Common use

```python
# src/app/plugins.py
from causeway import register, env

if env() == "prod":
    register(S3Storage(bucket=...))
```

> **Good to know.** Causeway doesn't validate the value — anything in the env var goes. If you want to constrain it (`dev` / `staging` / `prod`), add a `field_validator` to your `Settings` class.

## See also

- [Configuration](../../app/configuration.md)
- [Plugins — per-env activation](../../app/plugins.md#per-environment-activation)
