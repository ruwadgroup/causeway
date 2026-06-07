# Idempotency keys

The `Idempotency-Key` request header lets clients retry unsafe operations without double-charging, double-mailing, or double-creating. Causeway ships an ASGI middleware that replays the cached response on retry, scoped per (method, path, key).

## Setup

```python
# src/app/plugins.py
from causeway import register
from causeway.contrib.redis import RedisKV   # or any KV plugin
register(RedisKV(url=settings.redis_url))
```

```python
# src/app/routes/_middleware.py
from causeway import IdempotencyMiddleware
middleware = [IdempotencyMiddleware(ttl_seconds=86400)]
```

That's the whole surface. The middleware looks up the registered `KV` plugin at request time; you don't have to thread it.

## Behavior

- Reads `Idempotency-Key` on `POST` / `PUT` / `PATCH` / `DELETE` (configurable via `methods=`).
- Hashes `(method, path, body)` and stores `(key, body_hash, response)` under the active `KV`.
- Second request with same key + same body → replays the stored status/headers/body.
- Second request with same key + **different** body → `422` with a clear `idempotency_key_conflict` message.
- Request without `Idempotency-Key` → passes through unchanged.

Successful responses (2xx) are cached; errors are not. A 500 should re-attempt on retry, not poison the key.

## What gets cached

The middleware records the full response: status, headers, body. `Location` headers on `201 Created` replay correctly. `content-length` is recomputed on replay so the rehydrated response always matches its body.

Streaming responses are not cached. If a handler returns SSE, the middleware passes the response through but doesn't store it.

## Graph metadata

`IdempotencyMiddleware(...)` exposes its method set and TTL to the App Graph. The runtime behavior still lives in middleware; the graph only records enough metadata for generated clients, inspectors, and agents to understand that unsafe retries are expected on those routes.

## Edge cases

- **Concurrent duplicates with the same key**: both run, last write wins. Mid-flight dedup needs an atomic `KV.set_nx` primitive; that belongs in a future KV contract revision.
- **TTL refresh on read**: no. Once cached, the entry sticks for `ttl_seconds` from the _first_ request.
- **Key scope**: `(method, path, key)`. The same `Idempotency-Key` against two different endpoints does not collide.

## Tests

```python
from causeway import IdempotencyMiddleware
from causeway.middleware.idempotency import IdempotencyMiddleware  # explicit module path also works

# Inject a fake KV in tests so the middleware doesn't need a registry.
mw = IdempotencyMiddleware(kv=MemoryKV())
```
