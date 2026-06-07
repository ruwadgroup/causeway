# Deploying to Modal

Via the `causeway[modal]` adapter.

## Install

```bash
uv add "causeway[modal]"
modal token new
```

## Register

```python
# src/app/plugins.py
from causeway import register
from causeway.contrib.modal import ModalDeploy

register(ModalDeploy(
    name="my-app",
    cpu=1.0,
    memory_mb=512,
))
```

## Deploy

```bash
causeway build
causeway deploy modal
```

What that does:

1. Reads the `ModalDeploy` adapter.
2. Generates a Modal stub that exposes the ASGI app via `@modal.asgi_app()`.
3. Calls `modal deploy stub.py`.

## When Modal makes sense

- Bursty workloads (occasional API hits, scheduled jobs).
- ML inference endpoints where you want GPU-on-demand.
- Anything where you'd rather not run a server 24/7.

## When it doesn't

- Steady-state traffic that fits in a single VM.
- Latency-critical workloads (cold starts in the hundreds of milliseconds).
- Long-lived WebSockets / SSE streams (Modal has a per-invocation timeout).

## Secrets

Modal has its own secrets store:

```bash
modal secret create my-secrets DATABASE_URL=postgres://... CAUSEWAY_ENV=prod
```

Mount in the stub:

```python
import modal
secrets = [modal.Secret.from_name("my-secrets")]
```

The plugin wires this for you when you list secret names in the adapter config.

## See also

- [Deploying overview](./index.md)
- [`causeway deploy`](../reference/cli/deploy.md)
- [Modal docs](https://modal.com/docs)
