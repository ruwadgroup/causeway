"""Causeway — a lean backend framework for type-safe Python APIs.

Public API surface. Anything not listed in ``__all__`` (or imported from a
private underscore module like ``causeway._methods`` / ``causeway._runtime``)
is implementation detail and may change in any release. See
``docs/stability/semver.md`` and ``CHANGELOG.md``.

The RPC runtime (the type-safe Python↔TypeScript substrate) lives in
``causeway._runtime`` — app code only needs the re-exports here:

- :class:`App` — ASGI app + route registry (used internally by :func:`create_app`).
- :class:`Context` — per-request controls (response headers/cookies/status, after-callbacks).
- :func:`Depends` — DI marker for handler parameters.
- :func:`raises` — declare exception types the handler may raise (flows to
  the generated TS client's ``Result<T, E>`` union).
- :func:`stream` — SSE return type marker.
- :func:`bidi`, :class:`BidiChannel` — WebSocket bidirectional channels.
- :func:`after` — register a callback to run after the response is sent.
- :class:`Form` — multipart/form body marker.
- :data:`Bytes` — raw-body sentinel.
- :class:`SsePayload` — server-sent event payload helper.
"""

from __future__ import annotations

from causeway import errors
from causeway._methods import delete, get, patch, post, put
from causeway._runtime import (
    App,
    BidiChannel,
    Bytes,
    Context,
    Depends,
    Form,
    SsePayload,
    after,
    bidi,
    raises,
    stream,
)
from causeway.app import create_app
from causeway.auth import check_permission, expand_permissions, require_permission
from causeway.batch import BatchFailure, BatchResult, batch
from causeway.config import Manifest, Settings
from causeway.contracts import Webhooks, WebhookStore
from causeway.events import Event
from causeway.middleware import IdempotencyMiddleware, Middleware, MiddlewareItem, guard, use
from causeway.observability import RequestIdMiddleware, configure_logging, configure_otel
from causeway.pagination import Cursor, Paginated
from causeway.plugins import env, register
from causeway.scope import dependency, provide
from causeway.tasks import cron, task, tasks_eager
from causeway.webhooks import (
    IncomingWebhook,
    InMemoryWebhooks,
    InMemoryWebhookStore,
    Subscriber,
    WebhookDeliveryFailed,
    new_secret,
    sign_payload,
    verify,
    verify_signature,
)

__version__ = "1.0.0a0"

__all__ = [
    "App",
    "BatchFailure",
    "BatchResult",
    "BidiChannel",
    "Bytes",
    "Context",
    "Cursor",
    "Depends",
    "Event",
    "Form",
    "IdempotencyMiddleware",
    "InMemoryWebhookStore",
    "InMemoryWebhooks",
    "IncomingWebhook",
    "Manifest",
    "Middleware",
    "MiddlewareItem",
    "Paginated",
    "RequestIdMiddleware",
    "Settings",
    "SsePayload",
    "Subscriber",
    "WebhookDeliveryFailed",
    "WebhookStore",
    "Webhooks",
    "__version__",
    "after",
    "batch",
    "bidi",
    "check_permission",
    "configure_logging",
    "configure_otel",
    "create_app",
    "cron",
    "delete",
    "dependency",
    "env",
    "errors",
    "expand_permissions",
    "get",
    "guard",
    "new_secret",
    "patch",
    "post",
    "provide",
    "put",
    "raises",
    "register",
    "require_permission",
    "sign_payload",
    "stream",
    "task",
    "tasks_eager",
    "use",
    "verify",
    "verify_signature",
]
