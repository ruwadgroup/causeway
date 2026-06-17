"""Plugin contracts.

Each contract is a ``typing.Protocol``. The lifecycle methods
(``startup``, ``shutdown``, ``ready``) live on :class:`Plugin`; concrete
contracts inherit and add their own. Every contract carries a
``contract_version`` that the registry checks against the loaded Causeway
version and warns on mismatch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

AsyncContextManager = AbstractAsyncContextManager


@runtime_checkable
class Plugin(Protocol):
    """The common lifecycle every plugin observes.

    Implementations may set ``contract_version`` to declare the contract
    version they target. The registry checks compatibility on boot.
    """

    contract_version: ClassVar[str]

    async def startup(self, settings: Any) -> None:
        """Open whatever the adapter needs (DB pools, broker connections)."""
        ...

    async def shutdown(self) -> None:
        """Close everything ``startup`` opened. Idempotent."""
        ...

    async def ready(self) -> bool:
        """Return True when the plugin is fully usable. ``/readyz`` aggregates this."""
        ...


class TaskRef(Protocol):
    """A handle to a registered ``@task`` function. Adapters call ``.module`` /
    ``.name`` to identify it on the wire."""

    module: str
    name: str


class TaskStatus(Protocol):
    state: str  # "pending" | "running" | "complete" | "failed" | "cancelled"
    result: Any | None


@runtime_checkable
class TaskAdapter(Plugin, Protocol):
    """Background-task broker contract.

    ``v1.1`` adds :meth:`cancel`. Plugin authors that haven't implemented it
    can raise :class:`NotImplementedError`; callers should treat a False
    return as "couldn't cancel" and fall through to status polling.
    """

    contract_version: ClassVar[str] = "v1.1"

    async def enqueue(self, task: TaskRef, payload: bytes) -> str: ...
    async def schedule(self, task: TaskRef, when: datetime, payload: bytes) -> str: ...
    async def cron(self, task: TaskRef, expr: str) -> None: ...
    def eager(self) -> AsyncContextManager[None]: ...
    async def status(self, task_id: str) -> TaskStatus: ...
    async def result(self, task_id: str) -> Any: ...

    async def cancel(self, task_id: str, *, grace: float = 5.0) -> bool:
        """Request cancellation of ``task_id``.

        Cooperative first: the task body polls
        :func:`causeway.tasks.cancel_requested` (or awaits
        :func:`causeway.tasks.raise_if_cancelled`) and exits cleanly. If the
        body is still running after ``grace`` seconds, the adapter hard-cancels
        the underlying runner. Returns True if a cancel was issued, False if
        the task is unknown or already terminal.
        """
        ...


@runtime_checkable
class Storage(Plugin, Protocol):
    """Object-storage adapter contract.

    ``v1.1`` adds :meth:`presigned_put` and :meth:`presigned_get` so clients
    can upload and download direct to the bucket without routing bytes through
    the ASGI process. ``signed_url`` is kept as an alias of ``presigned_get``
    for v0.1 callers; new code should use the explicit names.
    """

    contract_version: ClassVar[str] = "v1.1"

    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def signed_url(self, key: str, *, expires: int = 3600) -> str: ...
    async def list(self, prefix: str = "") -> AsyncIterator[str]: ...

    async def presigned_put(
        self,
        key: str,
        *,
        expires: int = 3600,
        content_type: str | None = None,
        max_size_bytes: int | None = None,
    ) -> str:
        """Return a URL the client can ``PUT`` directly to.

        ``content_type`` and ``max_size_bytes`` are policy hints for adapters
        that support them (S3 enforces both via signed policy fields). Adapters
        that can't enforce them should still honor the call as best-effort.
        """
        ...

    async def presigned_get(self, key: str, *, expires: int = 3600) -> str:
        """Return a URL the client can ``GET`` directly from.

        Same semantics as :meth:`signed_url`; the explicit name pairs with
        :meth:`presigned_put` so call sites read symmetrically.
        """
        ...


@runtime_checkable
class KV(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, *, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, by: int = 1) -> int: ...
    async def expire(self, key: str, ttl: int) -> None: ...


@runtime_checkable
class Mailer(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    async def send(self, to: str, subject: str, body: str) -> None: ...
    async def send_template(self, to: str, template: str, data: dict[str, Any]) -> None: ...
    async def verify_address(self, address: str) -> bool: ...


@runtime_checkable
class RateLimiter(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    async def acquire(self, key: str, cost: int = 1) -> bool: ...
    async def peek(self, key: str) -> int: ...
    async def reset(self, key: str) -> None: ...


@runtime_checkable
class FeatureFlags(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    async def is_on(self, flag: str, user: str | None = None) -> bool: ...
    async def variant(self, flag: str, user: str | None = None) -> str | None: ...
    async def refresh(self) -> None: ...


@runtime_checkable
class MetricsSink(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    def counter(self, name: str, value: float = 1.0, **tags: str) -> None: ...
    def gauge(self, name: str, value: float, **tags: str) -> None: ...
    def histogram(self, name: str, value: float, **tags: str) -> None: ...
    def timer(self, name: str, **tags: str) -> AsyncContextManager[None]: ...


@runtime_checkable
class DBSession(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    def session(self) -> AsyncContextManager[Any]: ...
    def transaction(self) -> AsyncContextManager[Any]: ...
    async def health(self) -> bool: ...


@runtime_checkable
class AuthProvider(Plugin, Protocol):
    """Identity and authorization adapter contract.

    ``v1.1`` adds :meth:`has_permission`. Plugin authors that don't have a
    custom hierarchy can delegate to :func:`causeway.auth.check_permission`
    for the default ``domain:read/write/manage`` + ``*`` expansion.
    """

    contract_version: ClassVar[str] = "v1.1"

    async def current_user(self, req: Any) -> Any | None: ...
    async def login(self, creds: dict[str, Any]) -> Any: ...
    async def logout(self, req: Any) -> None: ...
    async def verify(self, token: str) -> Any | None: ...

    async def has_permission(self, user: Any, perm: str) -> bool:
        """Return ``True`` if ``user`` carries the named permission.

        Plugin authors are free to map permissions however they want;
        :func:`causeway.auth.check_permission` is the reference behavior
        (``*`` is superuser; ``X:manage`` implies ``X:write`` implies
        ``X:read``).
        """
        ...


@runtime_checkable
class BlobScanner(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    async def scan(self, stream: AsyncIterator[bytes]) -> bool: ...


@runtime_checkable
class DeployTarget(Plugin, Protocol):
    contract_version: ClassVar[str] = "v1.0"

    def manifest(self) -> dict[str, Any]: ...
    def package(self) -> bytes: ...
    async def push(self, target: str) -> str: ...


@runtime_checkable
class Webhooks(Plugin, Protocol):
    """Outbound webhook + incoming verification surface (v2).

    This contract intentionally covers only the lifecycle and the
    sign/verify helpers. Outbound *delivery* rides the
    :class:`TaskAdapter` (delivery is a regular ``@task`` inside
    :mod:`causeway.webhooks`); subscription state is split out into
    :class:`WebhookStore` for the durable, runtime-managed case. Static
    subscribers come from file discovery (``app/subscribers/``) and live on
    the :class:`~causeway.events.Event` class itself.
    """

    contract_version: ClassVar[str] = "v2.0"


@runtime_checkable
class WebhookStore(Plugin, Protocol):
    """Durable storage for dynamic (runtime-created) webhook subscriptions.

    Implemented by sibling plugins (``causeway-webhooks-pg``,
    ``causeway-webhooks-redis``, …). The in-memory adapter ships a reference
    implementation in :class:`causeway.webhooks.InMemoryWebhookStore` for
    tests and single-process apps; production deployments install a durable
    backend.

    Subscriptions are identified by ``endpoint_id`` (returned from
    :meth:`subscribe`). Scoping (tenant, region, environment) is expressed
    entirely through ``where`` — implementations are free to index hot keys.
    """

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


__all__ = [
    "KV",
    "AuthProvider",
    "BlobScanner",
    "DBSession",
    "DeployTarget",
    "FeatureFlags",
    "Mailer",
    "MetricsSink",
    "Plugin",
    "RateLimiter",
    "Storage",
    "TaskAdapter",
    "TaskRef",
    "TaskStatus",
    "WebhookStore",
    "Webhooks",
]
