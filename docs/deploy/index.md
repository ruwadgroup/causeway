# Deploying

A Causeway app is **an ASGI app + a manifest**. It runs anywhere ASGI runs — Docker, Fly, Modal, Lambda (via Mangum), bare uvicorn behind nginx, your own Kubernetes cluster.

The framework doesn't own deploys. The official adapter wraps the common case so you don't have to write Dockerfiles by hand:

- **[Docker](./docker.md)** — `causeway[docker]`. Builds an image from your project.
- **[Binary export](./binary.md)** — `causeway build --binary`. Single AOT-compiled executable for self-hosting; pairs with `FROM scratch` containers.

Every deploy adapter implements the [`DeployTarget`](../reference/classes/contracts.md#deploytarget) contract — `manifest()`, `package()`, `push(target)`.

## Generic process

For any target:

```bash
causeway build                            # emit dist/ir.json + client/ + wheel
causeway deploy <target>                  # plugin reads dist/ and pushes
```

The adapter produces the target-specific artifact (Dockerfile + image) from the project shape. You don't write target-specific glue.

## What gets deployed

```
dist/
├── ir.json
├── client/                              # ship to your frontend deploy
└── my_app-0.0.1-py3-none-any.whl        # ship to your backend runtime
```

## Manual deployment

Without a deploy adapter:

```bash
causeway build
docker build -t my-app -f deploy/Dockerfile .
docker push my-registry/my-app
```

Run with:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

You're done. Causeway emits an ASGI app — it's not Docker-aware in any way.

## Health checks

`GET /healthz` (liveness) and `GET /readyz` (readiness) ship by default. Wire your load balancer / orchestrator to those endpoints.

- `/healthz` — process is up. Returns 200 unconditionally.
- `/readyz` — all registered plugins' `ready()` returned true. Returns 503 with a per-plugin status JSON until everything is ready.

## Production checklist

- [ ] Set `CAUSEWAY_ENV=prod` (or `ENV=prod`).
- [ ] Disable the diagnostics endpoint: `create_app(..., diagnostics=False)`.
- [ ] Use `configure_logging(json=True)` for structured logs.
- [ ] Wire OTel: `configure_otel(service_name=..., endpoint=...)`.
- [ ] Ensure `/healthz` and `/readyz` are reachable by your LB.
- [ ] Don't commit `client/` if your frontend deploy rebuilds it.
- [ ] Don't commit `.env`; the production env wires settings via env vars.

## Per-target guides

- **[Docker](./docker.md)**
