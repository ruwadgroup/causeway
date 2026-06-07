# Deploying to Fly.io

Via the `causeway[fly]` adapter.

## Install

```bash
uv add "causeway[fly]"
brew install flyctl
fly auth login
```

## Register

```python
# src/app/plugins.py
from causeway import register
from causeway.contrib.fly import FlyDeploy

register(FlyDeploy(
    app_name="my-app",
    region="iad",
    primary_region="iad",
))
```

## Deploy

```bash
fly apps create my-app           # one-time
causeway build
causeway deploy fly
```

What that does:

1. Generates `fly.toml` from the adapter config.
2. Generates a Dockerfile (or reuses an existing one).
3. Calls `fly deploy --remote-only`.

## Secrets

Set per-app secrets via `flyctl`:

```bash
fly secrets set DATABASE_URL=postgres://... CAUSEWAY_ENV=prod
```

The app reads these like any other env var; your `Settings` picks them up.

## Health checks

`fly.toml` is wired with:

```toml
[[services.http_checks]]
  path = "/healthz"
  interval = "10s"
  timeout = "2s"
```

Override `/readyz` if your readiness depends on more than the default plugin aggregation.

## See also

- [Deploying overview](./index.md)
- [`causeway deploy`](../reference/cli/deploy.md)
- [Fly docs](https://fly.io/docs/)
