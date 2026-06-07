"""Outbound webhook delivery + incoming signature verification.

A **subscriber** is an external HTTP endpoint that wants to receive a
webhook when an event fires. Two flavors:

- **Static** — declared in ``app/subscribers/<name>.py`` as a
  :class:`Subscriber` instance. URL/secret come from config. Discovered at
  boot, registered against each event class's ``_subscribers`` list.
- **Dynamic** — created at runtime through :class:`WebhookStore.subscribe`
  (a separate contract, only implemented by durable plugins). Used when end
  users supply their own webhook URLs.

Delivery rides the :class:`~causeway.contracts.TaskAdapter`. The retry
schedule (10s, 60s, 5m, 30m, 4h) is the task adapter's retry primitive —
there is no bespoke delivery loop in this module. Durable retry +
multi-process delivery come for free with a durable task adapter.

Signing format is unchanged from earlier versions: Stripe-style HMAC-SHA256
over ``f"{timestamp}.{body}"`` in ``X-Causeway-Signature``, paired with
``X-Causeway-Timestamp``.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import inspect
import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

import msgspec

import causeway.events as _events
from causeway.errors import Unauthorized
from causeway.events import Event
from causeway.tasks import task

if TYPE_CHECKING:
    from causeway.contracts import WebhookStore

_log = logging.getLogger("causeway.webhooks")

SIGNATURE_HEADER = "x-causeway-signature"
TIMESTAMP_HEADER = "x-causeway-timestamp"
EVENT_HEADER = "x-causeway-event"


def sign_payload(
    secret: str,
    body: bytes,
    *,
    timestamp: int | None = None,
) -> tuple[str, str]:
    """Produce the ``(signature, timestamp)`` headers for an outgoing webhook.

    The timestamp defaults to ``time.time()``; callers pass an explicit value
    only in tests, where deterministic output matters.
    """
    ts = str(int(timestamp if timestamp is not None else time.time()))
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"v1,{mac}", ts


def verify_signature(
    secret: str,
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    *,
    max_skew_seconds: int = 300,
    now: int | None = None,
) -> None:
    """Raise :class:`Unauthorized` unless the signature checks out.

    Two failure modes: a missing/malformed signature, and a stale or
    tampered one. Both surface as 401 — clients shouldn't be able to tell
    them apart.
    """
    if not signature or not timestamp:
        raise Unauthorized("missing webhook signature")
    try:
        ts_int = int(timestamp)
    except ValueError:
        raise Unauthorized("malformed webhook timestamp") from None

    current = int(now if now is not None else time.time())
    if abs(current - ts_int) > max_skew_seconds:
        raise Unauthorized("webhook timestamp outside allowed skew")

    if not signature.startswith("v1,"):
        raise Unauthorized("unsupported webhook signature version")

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature[3:]):
        raise Unauthorized("webhook signature mismatch")


def new_secret() -> str:
    """Generate a fresh URL-safe secret for a new webhook endpoint."""
    return secrets.token_urlsafe(32)


@dataclass(slots=True)
class Subscriber:
    """A static outbound webhook target.

    Declared as a module-level instance in ``app/subscribers/<name>.py``.
    On construction it registers itself against each event class in
    ``events=[...]`` so ``Event.emit()`` can fan out to it.

    ``where`` filters by exact-match on event fields — only events whose
    field values match every key get a delivery. See the "Filterable events"
    section of the redesign plan.
    """

    url: str
    secret: str
    events: list[type[Event]]
    where: dict[str, Any] | None = None
    id: str = ""
    _registered: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.where:
            for event_cls in self.events:
                fields = {f.name for f in msgspec.structs.fields(event_cls)}
                for key in self.where:
                    if key not in fields:
                        msg = (
                            f"Subscriber where-key {key!r} is not a field on "
                            f"{event_cls.__name__}; declared fields: {sorted(fields)}"
                        )
                        raise ValueError(msg)
        for event_cls in self.events:
            if self not in event_cls._subscribers:
                event_cls._subscribers.append(self)
        self._registered = True


_MISSING = object()


def _matches(event: Event, where: dict[str, Any] | None) -> bool:
    """Return True iff every key in ``where`` equals the corresponding field
    on ``event``. Equality is JSON-roundtrip permissive: ``UUID("...")`` and
    its string form compare equal."""
    if not where:
        return True
    for key, expected in where.items():
        actual = getattr(event, key, _MISSING)
        if actual is _MISSING:
            return False
        if not _json_equal(actual, expected):
            return False
    return True


def _json_equal(a: Any, b: Any) -> bool:
    if a == b:
        return True
    if isinstance(a, UUID) or isinstance(b, UUID):
        return str(a) == str(b)
    return False


@dataclass(slots=True)
class StoredSubscriber:
    """A row from a :class:`WebhookStore`. Shape mirrors :class:`Subscriber`
    enough that delivery code doesn't care which it came from."""

    id: str
    url: str
    secret: str
    events: list[str]  # wire names
    where: dict[str, Any] | None = None


_store: WebhookStore | None = None


def set_store(store: WebhookStore | None) -> None:
    """Install the active :class:`WebhookStore`. Plugins call this from
    their ``startup`` hook. ``None`` clears the binding."""
    global _store
    _store = store


def active_store() -> WebhookStore | None:
    """Return the currently-installed :class:`WebhookStore`, or ``None``."""
    return _store


@task(queue="webhooks", retries=5, backoff="exponential")
async def _deliver(
    *,
    url: str,
    secret: str,
    wire_name: str,
    body: str,
) -> None:
    """Sign and POST one webhook delivery.

    Body is passed as JSON-encoded UTF-8 string (not bytes) because the
    task adapter's payload encoder uses ``json.dumps`` which can't carry
    raw bytes. The body is always valid UTF-8 JSON anyway — round-tripping
    through ``str`` is byte-identical for msgspec-encoded content.

    Signing happens inside the task so each retry signs against the
    current timestamp (avoiding skew-rejection from receivers when retries
    span minutes). Non-2xx → exception → task adapter retries per its
    backoff policy.
    """
    import httpx  # local import keeps httpx a soft dependency

    body_bytes = body.encode("utf-8")
    sig, ts = sign_payload(secret, body_bytes)
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(
            url,
            content=body_bytes,
            headers={
                SIGNATURE_HEADER: sig,
                TIMESTAMP_HEADER: ts,
                EVENT_HEADER: wire_name,
                "content-type": "application/json",
            },
        )
    if not 200 <= resp.status_code < 300:
        msg = f"webhook {wire_name} → {url} returned {resp.status_code}"
        raise RuntimeError(msg)


def _encode_body(event: Event) -> str:
    """Wire envelope: ``{"event": "<wire_name>", "data": <payload>}``."""
    return msgspec.json.encode({"event": type(event).wire_name, "data": event}).decode("utf-8")


async def _fanout(event: Event) -> list[str]:
    """Called by ``Event.emit()`` when the class has ``webhook=True``.

    Walks static subscribers + dynamic store entries, applies ``where``
    filters, and enqueues one ``_deliver`` task per match.
    """
    cls = type(event)
    body = _encode_body(event)
    delivery_ids: list[str] = []

    for sub in cls._subscribers:
        if not _matches(event, sub.where):
            continue
        try:
            tid = await _deliver.enqueue(
                url=sub.url,
                secret=sub.secret,
                wire_name=cls.wire_name,
                body=body,
            )
        except Exception:
            _log.exception(
                "failed to enqueue webhook delivery for %s → %s",
                cls.wire_name,
                sub.url,
            )
            continue
        delivery_ids.append(tid)

    store = _store
    if store is not None:
        async for stored in store.subscribers_for(cls.wire_name):
            if not _matches(event, stored.where):
                continue
            try:
                tid = await _deliver.enqueue(
                    url=stored.url,
                    secret=stored.secret,
                    wire_name=cls.wire_name,
                    body=body,
                )
            except Exception:
                _log.exception(
                    "failed to enqueue webhook delivery for %s → %s",
                    cls.wire_name,
                    stored.url,
                )
                continue
            delivery_ids.append(tid)

    return delivery_ids


# Wire the fan-out into Event.emit() at import time. One-way dependency.
_events._set_fanout(_fanout)


@dataclass(slots=True)
class IncomingWebhook:
    """A verified incoming webhook. The ``body`` bytes are the raw signed
    payload; ``json`` is the parsed dict; ``name`` is the wire-level event
    name (read from ``X-Causeway-Event`` header or the JSON envelope)."""

    name: str
    body: bytes
    json: dict[str, Any]


async def verify(
    req: Any,
    *,
    secret: str,
    max_skew_seconds: int = 300,
) -> IncomingWebhook:
    """Verify the request's HMAC + timestamp, parse the body, return it typed."""
    body = await _async_body(req)
    headers = _headers(req)

    verify_signature(
        secret,
        body,
        headers.get(SIGNATURE_HEADER),
        headers.get(TIMESTAMP_HEADER),
        max_skew_seconds=max_skew_seconds,
    )

    try:
        parsed = msgspec.json.decode(body) if body else {}
    except msgspec.DecodeError:
        raise Unauthorized("webhook body is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise Unauthorized("webhook body must be a JSON object")

    name = headers.get(EVENT_HEADER) or str(parsed.get("event", ""))
    data = parsed.get("data", parsed)
    if not isinstance(data, dict):
        data = {"value": data}
    return IncomingWebhook(name=name, body=body, json=data)


async def _async_body(req: Any) -> bytes:
    body_attr = getattr(req, "body", None)
    if isinstance(body_attr, (bytes, bytearray)):
        return bytes(body_attr)
    cached = getattr(req, "_body", None)
    if isinstance(cached, (bytes, bytearray)):
        return bytes(cached)
    if callable(body_attr):
        result = body_attr()
        if inspect.isawaitable(result):
            awaited = await result
            if isinstance(awaited, (bytes, bytearray)):
                return bytes(awaited)
            return b""
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
    return b""


def _headers(req: Any) -> dict[str, str]:
    raw = getattr(req, "headers", {})
    with contextlib.suppress(Exception):
        return {k.lower(): v for k, v in dict(raw).items()}
    return {}


class InMemoryWebhooks:
    """Reference :class:`~causeway.contracts.Webhooks` implementation.

    Holds no subscription state — static subscribers live on the event
    classes themselves, dynamic ones live in a :class:`WebhookStore` plugin.
    This adapter just provides the lifecycle methods + sign/verify so the
    plugin registry has something to install in the simple case.
    """

    contract_version: ClassVar[str] = "v2.0"

    async def startup(self, settings: Any) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def ready(self) -> bool:
        return True


class WebhookDeliveryFailed(Event):
    """Emitted when a delivery exhausts its retry budget.

    Wire name: ``"webhook.delivery.failed"``. Apps listen in
    ``app/listeners/webhook_health.py`` to disable persistently-failing
    endpoints. Itself NOT webhook-bridged (``webhook = False``) to avoid
    a cascade where the failure event tries to deliver and fails again.
    """

    delivery_id: str
    endpoint_url: str
    event_wire_name: str
    attempts: int
    last_error: str


class InMemoryWebhookStore:
    """Process-local :class:`~causeway.contracts.WebhookStore`. Not durable —
    restarts lose every subscription. Use only in tests or single-process
    setups where loss is acceptable."""

    contract_version: ClassVar[str] = "v1.0"

    def __init__(self) -> None:
        self._rows: dict[str, StoredSubscriber] = {}

    async def startup(self, settings: Any) -> None:
        set_store(self)

    async def shutdown(self) -> None:
        set_store(None)
        self._rows.clear()

    async def ready(self) -> bool:
        return True

    async def subscribe(
        self,
        *,
        url: str,
        secret: str,
        events: list[str],
        where: dict[str, Any] | None = None,
    ) -> str:
        endpoint_id = uuid.uuid4().hex
        self._rows[endpoint_id] = StoredSubscriber(
            id=endpoint_id,
            url=url,
            secret=secret,
            events=list(events),
            where=where,
        )
        return endpoint_id

    async def unsubscribe(self, endpoint_id: str) -> None:
        self._rows.pop(endpoint_id, None)

    async def disable(self, endpoint_id: str) -> None:
        self._rows.pop(endpoint_id, None)

    async def subscribers_for(self, wire_name: str) -> AsyncIterator[StoredSubscriber]:
        for row in list(self._rows.values()):
            if wire_name in row.events:
                yield row


__all__ = [
    "EVENT_HEADER",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "InMemoryWebhookStore",
    "InMemoryWebhooks",
    "IncomingWebhook",
    "StoredSubscriber",
    "Subscriber",
    "WebhookDeliveryFailed",
    "active_store",
    "new_secret",
    "set_store",
    "sign_payload",
    "verify",
    "verify_signature",
]
