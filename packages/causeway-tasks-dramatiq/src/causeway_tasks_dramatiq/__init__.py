"""Dramatiq adapter for Causeway's :class:`causeway.contracts.TaskAdapter`.

Dramatiq has its own actor model — we adapt it to Causeway's TaskRef + enqueue
shape so handlers don't change when a project swaps brokers. The actor
side of Dramatiq is created lazily for each TaskRef seen at enqueue time;
its message dispatch path runs the underlying function with the decoded
payload.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, ClassVar

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.errors import ActorNotFound
from periodiq import PeriodiqMiddleware, cron as periodiq_cron

from causeway.tasks import TaskRef, TaskState, cron_jobs, registered_tasks, set_adapter

_DEFAULT_BROKER_URL = "redis://localhost"


def _secret_value(value: Any) -> Any:
    getter = getattr(value, "get_secret_value", None)
    return getter() if callable(getter) else value


def _broker_url_from_settings(settings: Any) -> str | None:
    if settings is None:
        return None
    url = _secret_value(getattr(settings, "redis_url", None))
    return str(url) if url else None


def _cron_expr_for(task: TaskRef) -> str | None:
    key = f"{task.module}.{task.name}"
    for ref, expr in cron_jobs():
        if ref is task or f"{ref.module}.{ref.name}" == key:
            return expr
    return None


class DramatiqAdapter:
    """Routes Causeway tasks through a Dramatiq Redis broker.

    Notes on retries: Dramatiq's ``max_retries`` honors the TaskRef's
    ``retries`` setting. Backoff strategies map onto Dramatiq's
    ``min_backoff`` / ``max_backoff`` (exponential is the default; we
    pin the floor to 100 ms to match the in-memory adapter).
    """

    contract_version: ClassVar[str] = "v1.1"

    def __init__(self, broker_url: str | None = None, *, periodiq_skip_delay: int = 30) -> None:
        self.broker_url = broker_url or _DEFAULT_BROKER_URL
        self._uses_default_broker_url = broker_url is None
        self.periodiq_skip_delay = periodiq_skip_delay
        self._broker: RedisBroker | None = None
        self._actors: dict[str, Any] = {}

    @property
    def broker(self) -> RedisBroker | None:
        return self._broker

    async def startup(self, settings: Any) -> None:  # noqa: ARG002
        if self._uses_default_broker_url:
            self.broker_url = _broker_url_from_settings(settings) or self.broker_url
        self._broker = RedisBroker(url=self.broker_url)
        self._broker.add_middleware(PeriodiqMiddleware(skip_delay=self.periodiq_skip_delay))
        dramatiq.set_broker(self._broker)
        for task in registered_tasks().values():
            self._actor_for(task)
        set_adapter(self)

    async def shutdown(self) -> None:
        if self._broker is not None:
            self._broker.close()
            self._broker = None
        self._actors.clear()

    async def ready(self) -> bool:
        return self._broker is not None

    def _actor_for(self, task: TaskRef, *, cron_expr: str | None = None) -> Any:
        key = f"{task.module}.{task.name}"
        if key in self._actors:
            return self._actors[key]
        try:
            actor = dramatiq.get_broker().get_actor(key)
        except ActorNotFound:
            actor = None
        if actor is not None:
            self._actors[key] = actor
            return actor
        if task.fn is None:
            msg = f"{task!r} has no callable bound; cannot create Dramatiq actor"
            raise RuntimeError(msg)

        target = task.fn
        expr = cron_expr or _cron_expr_for(task)
        actor_kwargs: dict[str, Any] = {
            "actor_name": key,
            "queue_name": task.queue,
            "max_retries": task.retries,
            "min_backoff": 100,
        }
        if expr is not None:
            actor_kwargs["periodic"] = periodiq_cron(expr)

        @dramatiq.actor(**actor_kwargs)
        def _run(payload_json: str = '{"args": [], "kwargs": {}}') -> None:
            payload = json.loads(payload_json)
            asyncio.run(target(*payload.get("args", []), **payload.get("kwargs", {})))

        self._actors[key] = _run
        return _run

    async def enqueue(self, task: TaskRef, payload: bytes) -> str:
        actor = self._actor_for(task)
        message = actor.send(payload.decode())
        return str(message.message_id)

    async def schedule(self, task: TaskRef, when: datetime, payload: bytes) -> str:
        delay_ms = max(
            0, int((when - datetime.now(when.tzinfo)).total_seconds() * 1000)
        )
        actor = self._actor_for(task)
        message = actor.send_with_options(args=(payload.decode(),), delay=delay_ms)
        return str(message.message_id)

    async def cron(self, task: TaskRef, expr: str) -> None:
        self._actor_for(task, cron_expr=expr)

    def eager(self) -> contextlib.AbstractAsyncContextManager[None]:
        return self._eager_context()

    @contextlib.asynccontextmanager
    async def _eager_context(self) -> AsyncIterator[None]:
        from dramatiq.brokers.stub import StubBroker

        prev_broker = self._broker
        stub = StubBroker()
        dramatiq.set_broker(stub)
        self._broker = stub
        try:
            yield
        finally:
            if prev_broker is not None:
                dramatiq.set_broker(prev_broker)
            self._broker = prev_broker

    async def status(self, task_id: str) -> TaskState:
        # Dramatiq doesn't track per-message status without a result backend.
        # The status surface returns "pending" by default; users wanting
        # results plug in ``dramatiq[redis]``'s ``Results`` middleware.
        del task_id
        return TaskState(state="pending")

    async def result(self, task_id: str) -> Any:
        del task_id
        msg = (
            "Dramatiq doesn't expose results without the Results middleware. "
            "Enable it on the broker or use a TaskAdapter that does."
        )
        raise NotImplementedError(msg)

    async def cancel(self, task_id: str, *, grace: float = 5.0) -> bool:
        # Dramatiq has no first-class cancel for in-flight messages; the worker
        # would need a cooperative protocol on top of the broker. Surface that
        # honestly rather than pretending the call did something.
        del task_id, grace
        msg = (
            "DramatiqAdapter does not implement cancel(); cancellation requires "
            "a coordinated worker protocol on top of the broker."
        )
        raise NotImplementedError(msg)


def plugin(settings: Any) -> None:
    """Entry-point hook. Reads ``settings.redis_url`` if available."""
    from causeway import register

    register(DramatiqAdapter(broker_url=_broker_url_from_settings(settings)))


__all__ = ["DramatiqAdapter", "plugin"]
