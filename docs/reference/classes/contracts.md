# Plugin contracts

Every plugin contract in `causeway.contracts`. All are `typing.Protocol`s — duck-typed, no inheritance required.

```python
from causeway.contracts import (
    Plugin,
    TaskAdapter,
    Webhooks,
    WebhookStore,
    Storage,
    KV,
    SessionStore,
    Mailer,
    PubSub,
    RateLimiter,
    FeatureFlags,
    MetricsSink,
    LogSink,
    Searchable,
    DBSession,
    AuthProvider,
    BlobScanner,
    DeployTarget,
)
```

> **Note.** `EventBus` and the old `Webhooks` (with `register_endpoint`/`send`) are gone in 0.2+. Events are class-based (see `causeway.events.Event`); webhook delivery is a `@task` inside `causeway.webhooks`; subscription storage is split out into `WebhookStore`.

Every contract carries a `contract_version: ClassVar[str] = "v1.0"` so the registry can warn when a plugin targets an older protocol.

---

## `Plugin` (base)

Every contract inherits this.

```python
class Plugin(Protocol):
    contract_version: ClassVar[str]
    async def startup(self, settings: Any) -> None: ...
    async def shutdown(self) -> None: ...
    async def ready(self) -> bool: ...
```

---

## `TaskAdapter`

```python
class TaskAdapter(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.1"

    async def enqueue(self, task: TaskRef, payload: bytes) -> str: ...
    async def schedule(self, task: TaskRef, when: datetime, payload: bytes) -> str: ...
    async def cron(self, task: TaskRef, expr: str) -> None: ...
    def eager(self) -> AsyncContextManager[None]: ...
    async def status(self, task_id: str) -> TaskStatus: ...
    async def result(self, task_id: str) -> Any: ...
    async def cancel(self, task_id: str, *, grace: float = 5.0) -> bool: ...
```

`v1.1` adds `cancel(task_id, *, grace)`. Cooperative first — the task body polls [`cancel_requested`](../functions/cancel-requested.md) (or awaits [`raise_if_cancelled`](../functions/raise-if-cancelled.md)) and exits. After `grace` seconds, the adapter hard-cancels the underlying runner. Returns `True` if a cancel was issued, `False` if the task is unknown or already terminal. Adapters that can't honestly cancel (e.g. Dramatiq without a coordinated worker protocol) raise `NotImplementedError`.

Reference: `causeway.tasks.InMemoryAdapter`. Real adapters: `causeway[dramatiq]`.

---

## `Webhooks`

```python
class Webhooks(Plugin, Protocol):
    contract_version: ClassVar[str] = "v2.0"
```

Lifecycle adapter for the outbound webhook surface. Holds no subscription state — static subscribers live on the `Event` class itself; dynamic ones live in a `WebhookStore`. Delivery is a `@task` inside `causeway.webhooks`, not a method on this contract.

Reference: `causeway.webhooks.InMemoryWebhooks`.

See [Webhooks](../../app/webhooks.md) for the model and [Subscribers](../../app/subscribers.md) for the registration surface.

---

## `WebhookStore`

```python
class WebhookStore(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    async def subscribe(
        self,
        *,
        url: str,
        secret: str,
        events: list[str],
        where: dict[str, Any] | None = None,
    ) -> str: ...
    async def unsubscribe(self, endpoint_id: str) -> None: ...
    async def disable(self, endpoint_id: str) -> None: ...
    def subscribers_for(self, wire_name: str) -> AsyncIterator[Any]: ...
```

Durable storage for runtime-managed webhook subscriptions (multi-tenant apps, customer-managed integrations). `subscribers_for(wire_name)` yields rows for one event; `Event.emit()` calls it during fan-out and applies each row's `where` filter.

Reference: `causeway.webhooks.InMemoryWebhookStore` (process-local, for tests and single-process apps). Production deployments install a durable plugin (`causeway-webhooks-pg`, etc.).

`InMemoryWebhooks` does **not** implement `WebhookStore` — `subscribe()` raises `NotImplementedError`. The in-memory adapter can't honestly persist subscriptions across restarts.

---

## `Storage`

```python
class Storage(Plugin, Protocol):
    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def signed_url(self, key: str, *, expires: int = 3600) -> str: ...
    async def list(self, prefix: str = "") -> AsyncIterator[str]: ...
```

Reference: `causeway.adapters.LocalStorage`. Real adapters: `causeway[fs]`, `causeway[s3]`.

---

## `KV`

```python
class KV(Plugin, Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, *, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, by: int = 1) -> int: ...
    async def expire(self, key: str, ttl: int) -> None: ...
```

Reference: `causeway.adapters.MemoryKV`. Real adapters: `causeway[redis]`.

---

## `SessionStore`

```python
class SessionStore(Plugin, Protocol):
    async def read(self, session_id: str) -> dict[str, Any] | None: ...
    async def write(self, session_id: str, data: dict[str, Any]) -> None: ...
    async def destroy(self, session_id: str) -> None: ...
    async def rotate(self, session_id: str) -> str: ...
```

Reference: `causeway.adapters.CookieStore`.

---

## `Mailer`

```python
class Mailer(Plugin, Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...
    async def send_template(self, to: str, template: str, data: dict[str, Any]) -> None: ...
    async def verify_address(self, address: str) -> bool: ...
```

Real adapters: `causeway[smtp]`. No in-core reference.

---

## `PubSub`

```python
class PubSub(Plugin, Protocol):
    async def publish(self, topic: str, payload: bytes) -> None: ...
    async def subscribe(self, topic: str, handler: Callable[[bytes], Awaitable[None]]) -> None: ...
```

---

## `RateLimiter`

```python
class RateLimiter(Plugin, Protocol):
    async def acquire(self, key: str, cost: int = 1) -> bool: ...
    async def peek(self, key: str) -> int: ...
    async def reset(self, key: str) -> None: ...
```

Reference: `causeway.adapters.MemoryLimiter` (token bucket).

---

## `FeatureFlags`

```python
class FeatureFlags(Plugin, Protocol):
    async def is_on(self, flag: str, user: str | None = None) -> bool: ...
    async def variant(self, flag: str, user: str | None = None) -> str | None: ...
    async def refresh(self) -> None: ...
```

Reference: `causeway.adapters.StaticFlags` (reads `Settings.feature_flags`). Real adapters: `causeway[growthbook]`.

---

## `MetricsSink`

```python
class MetricsSink(Plugin, Protocol):
    def counter(self, name: str, value: float = 1.0, **tags: str) -> None: ...
    def gauge(self, name: str, value: float, **tags: str) -> None: ...
    def histogram(self, name: str, value: float, **tags: str) -> None: ...
    def timer(self, name: str, **tags: str) -> AsyncContextManager[None]: ...
```

---

## `LogSink`

```python
class LogSink(Plugin, Protocol):
    def emit(self, record: dict[str, Any]) -> None: ...
```

Reference: stdout via `structlog`.

---

## `Searchable`

```python
class Searchable(Plugin, Protocol):
    async def index(self, doc_id: str, doc: dict[str, Any]) -> None: ...
    async def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]: ...
    async def delete(self, doc_id: str) -> None: ...
    async def bulk_index(self, docs: list[tuple[str, dict[str, Any]]]) -> None: ...
```

---

## `DBSession`

```python
class DBSession(Plugin, Protocol):
    def session(self) -> AsyncContextManager[Any]: ...
    def transaction(self) -> AsyncContextManager[Any]: ...
    async def health(self) -> bool: ...
```

Real adapters: `causeway[sqlmodel]`.

---

## `AuthProvider`

```python
class AuthProvider(Plugin, Protocol):
    async def current_user(self, req: Any) -> Any | None: ...
    async def login(self, creds: dict[str, Any]) -> Any: ...
    async def logout(self, req: Any) -> None: ...
    async def verify(self, token: str) -> Any | None: ...
```

Real adapters: `causeway[jwt]`.

---

## `BlobScanner`

```python
class BlobScanner(Plugin, Protocol):
    async def scan(self, stream: AsyncIterator[bytes]) -> bool: ...
```

---

## `DeployTarget`

```python
class DeployTarget(Plugin, Protocol):
    def manifest(self) -> dict[str, Any]: ...
    def package(self) -> bytes: ...
    async def push(self, target: str) -> str: ...
```

Real adapters: `causeway[docker]`, `causeway[fly]`, `causeway[modal]`.

---

## Contract versioning

Each contract carries `contract_version: ClassVar[str]`. The registry warns when a plugin targets a version other than the loaded one.

After 1.0:

- Adding optional methods → non-breaking.
- Removing or renaming a method → breaking; follows the deprecation cycle in [`semver`](../../stability/semver.md).

## See also

- [Plugins overview](../../app/plugins.md)
- [Writing a plugin](../../app/plugin-authoring.md)
- [`register`](../functions/register.md)
