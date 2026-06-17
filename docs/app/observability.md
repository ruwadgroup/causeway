# Observability

Causeway wires the correlation; you pick the exporter. Three layers ship:

1. **`RequestIdMiddleware`** — stamps every request with a stable id, threaded through logs and into the response header.
2. **`configure_logging`** — sets up structured (JSON or console) logs via `structlog`, with the request id bound to every log line in the request.
3. **`configure_otel`** — wires OpenTelemetry tracing if the OTel SDK is installed.

## Request IDs

Installed by default in `create_app(..., request_id=True)`. Every request:

- gets a UUID stamped on `request.state.request_id` (or uses the inbound `X-Request-Id` header if present),
- the same id is set as a `structlog` contextvar so every `log.info(...)` in the handler carries it,
- the response gets an `X-Request-Id` header on the way out.

```python
import structlog

log = structlog.get_logger()

@get
async def show(id: UUID) -> User:
    log.info("loading user", user_id=str(id))
    # logs: {"event": "loading user", "user_id": "...", "request_id": "..."}
```

Downstream services should echo `X-Request-Id` to thread one id through a request fan-out.

## Structured logging

```python
# src/app/lifespan.py
from causeway import configure_logging

configure_logging(level="INFO", json=True)
```

- `json=True` (default in prod) — one JSON object per line, ready for log shipping.
- `json=False` — pretty console renderer for local dev.

Every log line gets:

- the request id (if inside a request),
- the timestamp (ISO 8601, UTC),
- the log level,
- any keyword fields you pass.

The setup uses `structlog`'s standard processors — for custom processors (e.g. PII scrubbing), call `structlog.configure(...)` yourself after `configure_logging`.

## OpenTelemetry

```python
# src/app/lifespan.py
from causeway import configure_otel

configure_otel(
    service_name="my-app",
    endpoint="http://otel-collector:4318/v1/traces",
)
```

Returns `True` if the SDK is installed (`causeway[otel]` extra), `False` otherwise — calling it without the extra is a no-op, not an error.

Pick your exporter via standard OTel env vars or by composing your own `TracerProvider`. Causeway's helper is the simple path; for advanced setups, build the provider yourself and call `trace.set_tracer_provider(...)`.

## Health endpoints

`GET /healthz` — process is up. Returns 200 unconditionally.

`GET /readyz` — every registered plugin's `ready()` returned true. Returns 200 or 503 with a per-plugin status JSON. Both are attached automatically; override by adding `routes/healthz.py` / `routes/readyz.py`.

```json
{
  "status": "ready",
  "plugins": {
    "DramatiqAdapter": true,
    "S3Storage": true,
    "RedisCache": true
  }
}
```

## Diagnostics page

`GET /__causeway` (dev only). Shows:

- the full route tree with handler source paths,
- registered plugins and their contract versions,
- current settings (secrets redacted),
- recent traces (when OTel is wired),
- recent log lines.

Disable in production via `create_app(..., diagnostics=False)`.

## What Causeway doesn't do

- **Metrics export.** Use the `MetricsSink` contract with a plugin (`causeway-metrics-statsd`, `causeway-metrics-prometheus`).
- **Log shipping.** Point your container runtime at stdout.
- **APM dashboards.** SigNoz, Honeycomb, Datadog, Tempo — pick one, point OTel at it.

The framework wires correlation. The transport and storage are the user's choice.

## Common patterns

**Per-handler timing:**

```python
import time
import structlog

log = structlog.get_logger()

@guard
async def time_request(req):
    req.state.t0 = time.perf_counter()

# in middleware, log on the way out
```

For app-wide timing, install a class `Middleware` at the root.

**OTel with auto-instrumentation:**

```python
# src/app/lifespan.py
from causeway import configure_otel
from causeway.observability import instrument_asgi

configure_otel(service_name="my-app", endpoint=settings.otel_endpoint)
# wrap the ASGI app — Causeway exposes the helper for users who construct app manually
```

## Next

- [Reference — `RequestIdMiddleware`](../reference/classes/RequestIdMiddleware.md)
- [Reference — `configure_logging`](../reference/functions/configure-logging.md)
- [Reference — `configure_otel`](../reference/functions/configure-otel.md)
