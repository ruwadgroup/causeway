# Configuration

Causeway's `Settings` is `pydantic_settings.BaseSettings` — typed, env-driven, secret-aware. Plus a `causeway.toml` manifest for things the framework needs to know (what to expose to the TS client).

## `Settings` — typed config

```python
# src/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    env: str = "dev"
    database_url: SecretStr
    redis_url: SecretStr | None = None
    feature_flags: dict[str, bool] = {}


settings = Settings()
```

Three rules:

1. Subclass `BaseSettings` and define an instance named `settings` in `src/app/config.py`.
2. Use `SecretStr` / `SecretBytes` for anything sensitive — the diagnostics page and TS client surface skip them.
3. Reads `.env` automatically; environment variables override the file.

## Reading config in handlers

Import the instance directly:

```python
from app.config import settings

@get
async def show(...) -> ...:
    db_url = settings.database_url.get_secret_value()
    ...
```

For request-scoped values that depend on settings (a DB pool, a Stripe client), build them once in a `_scope.py` startup and expose them via `@provide`. See [Scopes](../backend/scopes.md).

## Environment-aware config

```python
class Settings(BaseSettings):
    env: str = "dev"
    s3_bucket: str = "uploads-local"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"
```

Per-env activation in `plugins.py`:

```python
from causeway import register, env

if env() == "prod":
    register(S3Storage(bucket=settings.s3_bucket))
else:
    register(LocalStorage(path="./tmp/uploads"))
```

The `env()` helper reads `CAUSEWAY_ENV`, falls back to `ENV`, defaults to `"dev"`.

## `causeway.toml` — framework manifest

```toml
# causeway.toml
[app]
name = "my-app"
description = "Hello from Causeway"

[client]
expose_settings = ["env", "feature_flags"]   # non-secret config to surface to the TS client
```

What lives here:

- `[client] expose_settings` — allowlist of settings fields to bake into the generated client (for things like feature flags or the current env). **Secrets are never exposed**, even if you list them — `SecretStr` / `SecretBytes` are stripped as defense in depth.
- `[app]` — metadata used by the scaffolder and the diagnostics page.

## What ends up in the TS client

| Source                              | Shape on the client                                  |
| ----------------------------------- | ---------------------------------------------------- |
| Handler signatures                  | Typed function per route.                            |
| `causeway.toml`'s `expose_settings` | A `config` object with the listed non-secret fields. |
| `SecretStr` fields                  | Never. Filtered before codegen.                      |

## Loading order

1. Process starts.
2. `causeway.toml` is parsed (`Manifest`).
3. `app.config` is imported; `Settings()` instantiates and reads `.env` + env vars.
4. `app.plugins` is imported; `register(...)` calls run with the loaded `settings`.
5. Entry-point plugins auto-load and may contribute `settings_fragment()` fields.
6. Lifespan starts — every plugin's `startup(settings)` fires.

## Common patterns

**Nested env vars:**

```python
class DbSettings(BaseSettings):
    host: str
    port: int = 5432

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    db: DbSettings
```

Set with `DB__HOST=localhost DB__PORT=5432`.

**Validators:**

```python
from pydantic import field_validator

class Settings(BaseSettings):
    env: str = "dev"

    @field_validator("env")
    @classmethod
    def normalize(cls, v: str) -> str:
        if v not in {"dev", "staging", "prod"}:
            raise ValueError(f"invalid env: {v}")
        return v
```

**Per-feature settings (plugin fragments):**
A plugin can contribute typed fields to your `Settings`:

```python
class StripeAdapter:
    def settings_fragment(self) -> dict:
        return {"stripe_webhook_secret": SecretStr(...)}
```

After registration, `settings.stripe_webhook_secret` is defined.

## Next

- [Plugins](./plugins.md) — installing adapters with config.
- [Reference — `Settings`](../reference/classes/Settings.md)
- [Reference — `Manifest`](../reference/classes/Manifest.md)
