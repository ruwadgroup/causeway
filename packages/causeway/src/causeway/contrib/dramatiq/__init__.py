"""Dramatiq adapter for Causeway's :class:`causeway.contracts.TaskAdapter`.

Dramatiq has its own actor model — we adapt it to Causeway's TaskRef + enqueue
shape so handlers don't change when a project swaps brokers. Actors are created
at ``startup`` for every registered task on the same broker the worker consumes,
so :func:`causeway.contrib.dramatiq.runtime.bootstrap` returns a broker with a
populated actor table — no post-hoc ``adapter.broker = dramatiq.get_broker()``
reassignment is needed.

Task state and cancellation are tracked in Redis (the broker's own client), so
``status``/``result``/``cancel`` work and tasks can cooperatively bail out via
:func:`causeway.tasks.raise_if_cancelled`. Those paths degrade to no-ops when no
Redis client is available.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections.abc import AsyncIterator
from concurrent.futures import CancelledError as FutureCancelledError
from datetime import datetime
from typing import Any, ClassVar

import dramatiq
from dramatiq.broker import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.errors import ActorNotFound
from dramatiq.middleware import CurrentMessage
from periodiq import PeriodiqMiddleware  # type: ignore[import-untyped]
from periodiq import cron as periodiq_cron

from causeway.tasks import (
    TaskRef,
    TaskState,
    _cancel_check_var,
    cron_jobs,
    registered_tasks,
    set_adapter,
)

_DEFAULT_BROKER_URL = "redis://localhost"
_STATE_TTL_SECONDS = 60 * 60 * 24

# One background event loop shared by every actor invocation in this process. A
# fresh ``asyncio.run`` per message would rebind loop-bound resources (async DB
# engines, connection pools) on every task and break them.
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


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


def _worker_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        loop = asyncio.new_event_loop()

        def run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        threading.Thread(target=run, name="causeway-dramatiq-asyncio", daemon=True).start()
        _loop = loop
        return loop


def _current_task_id() -> str | None:
    message = CurrentMessage.get_current_message()
    return str(message.message_id) if message is not None else None


class DramatiqAdapter:
    """Routes Causeway tasks through a Dramatiq Redis broker."""

    contract_version: ClassVar[str] = "v2.0"

    def __init__(self, broker_url: str | None = None, *, periodiq_skip_delay: int = 30) -> None:
        self.broker_url = broker_url or _DEFAULT_BROKER_URL
        self._uses_default_broker_url = broker_url is None
        self.periodiq_skip_delay = periodiq_skip_delay
        self._broker: Broker | None = None
        self._actors: dict[str, Any] = {}

    @property
    def broker(self) -> Broker | None:
        return self._broker

    async def startup(self, settings: Any) -> None:
        if self._uses_default_broker_url:
            self.broker_url = _broker_url_from_settings(settings) or self.broker_url
        broker = RedisBroker(url=self.broker_url)  # type: ignore[no-untyped-call]
        broker.add_middleware(CurrentMessage())
        broker.add_middleware(PeriodiqMiddleware(skip_delay=self.periodiq_skip_delay))
        dramatiq.set_broker(broker)
        self._broker = broker
        for task in registered_tasks().values():
            self._actor_for(task)
        set_adapter(self)

    async def shutdown(self) -> None:
        if self._broker is not None:
            self._broker.close()
            self._broker = None
        self._actors.clear()

    async def ready(self) -> bool:
        if self._broker is None:
            return False
        client = self._client()
        if client is None:
            return True  # non-Redis broker (e.g. stub) has no client to ping
        try:
            client.ping()
        except Exception:
            return False
        return True

    # ---- state + cancellation (Redis-backed; no-ops without a client) ----

    def _client(self) -> Any | None:
        # RedisBroker exposes `.client`; stub/other brokers don't (state is a no-op there).
        return getattr(self._broker, "client", None)

    def _state_key(self, task_id: str) -> str:
        return f"causeway:task:{task_id}:state"

    def _cancel_key(self, task_id: str) -> str:
        return f"causeway:task:{task_id}:cancel"

    def _set_state_sync(
        self,
        task_id: str,
        state: str,
        *,
        result: Any | None = None,
        error: str | None = None,
        overwrite: bool = True,
    ) -> None:
        client = self._client()
        if client is None:
            return
        key = self._state_key(task_id)
        if not overwrite and client.exists(key):
            return
        client.setex(
            key,
            _STATE_TTL_SECONDS,
            json.dumps({"state": state, "result": result, "error": error}, default=str),
        )

    def _get_state_sync(self, task_id: str) -> TaskState | None:
        client = self._client()
        if client is None:
            return None
        raw = client.get(self._state_key(task_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        data = json.loads(raw)
        return TaskState(
            state=data.get("state", "pending"),
            result=data.get("result"),
            error=data.get("error"),
        )

    def _cancel_requested_sync(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        client = self._client()
        if client is None:
            return False
        return bool(client.exists(self._cancel_key(task_id)))

    # ---- actor creation + dispatch ----

    def _actor_for(self, task: TaskRef, *, cron_expr: str | None = None) -> Any:
        key = f"{task.module}.{task.name}"
        if key in self._actors:
            return self._actors[key]
        try:
            existing = dramatiq.get_broker().get_actor(key)
        except ActorNotFound:
            existing = None
        if existing is not None:
            self._actors[key] = existing
            return existing
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

        @dramatiq.actor(**actor_kwargs)  # type: ignore[untyped-decorator]
        def _run(payload_json: str = '{"args": [], "kwargs": {}}') -> None:
            payload = json.loads(payload_json)
            self._dispatch(target, payload.get("args", []), payload.get("kwargs", {}))

        self._actors[key] = _run
        return _run

    def _dispatch(self, fn: Any, args: list[Any], kwargs: dict[str, Any]) -> None:
        task_id = _current_task_id()
        if task_id and self._cancel_requested_sync(task_id):
            self._set_state_sync(task_id, "cancelled")
            return
        if task_id:
            self._set_state_sync(task_id, "running")
        try:
            result = self._run_async(fn(*args, **kwargs), task_id=task_id)
        except (asyncio.CancelledError, FutureCancelledError):
            if task_id:
                self._set_state_sync(task_id, "cancelled")
            return
        except Exception as exc:
            if task_id:
                if self._cancel_requested_sync(task_id):
                    self._set_state_sync(task_id, "cancelled")
                else:
                    self._set_state_sync(task_id, "failed", error=str(exc))
            raise
        if task_id:
            if self._cancel_requested_sync(task_id):
                self._set_state_sync(task_id, "cancelled")
            else:
                self._set_state_sync(task_id, "complete", result=result)

    def _run_async(self, coro: Any, *, task_id: str | None) -> Any:
        async def invoke() -> Any:
            set_adapter(self)
            token = None
            if task_id:
                token = _cancel_check_var.set(lambda: self._cancel_requested_sync(task_id))
            try:
                return await coro
            finally:
                if token is not None:
                    _cancel_check_var.reset(token)

        return asyncio.run_coroutine_threadsafe(invoke(), _worker_loop()).result()

    # ---- TaskAdapter surface ----

    async def enqueue(self, task: TaskRef, payload: bytes) -> str:
        actor = self._actor_for(task)
        message = actor.send(payload.decode())
        self._set_state_sync(str(message.message_id), "pending", overwrite=False)
        return str(message.message_id)

    async def schedule(self, task: TaskRef, when: datetime, payload: bytes) -> str:
        delay_ms = max(0, int((when - datetime.now(when.tzinfo)).total_seconds() * 1000))
        actor = self._actor_for(task)
        message = actor.send_with_options(args=(payload.decode(),), delay=delay_ms)
        self._set_state_sync(str(message.message_id), "pending", overwrite=False)
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
        state = self._get_state_sync(task_id)
        return state if state is not None else TaskState(state="pending")

    async def result(self, task_id: str) -> Any:
        state = self._get_state_sync(task_id)
        if state is None:
            msg = f"unknown task {task_id}"
            raise KeyError(msg)
        if state.state == "failed":
            raise RuntimeError(state.error or "task failed")
        if state.state == "cancelled":
            raise asyncio.CancelledError
        return state.result

    async def cancel(self, task_id: str, *, grace: float = 5.0) -> bool:
        del grace
        client = self._client()
        if client is None:
            return False
        state = self._get_state_sync(task_id)
        if state is not None and state.state in {"complete", "failed", "cancelled"}:
            return False
        client.setex(self._cancel_key(task_id), _STATE_TTL_SECONDS, "1")
        self._set_state_sync(task_id, "cancelled")
        return True


def plugin(settings: Any) -> None:
    """Entry-point hook. Reads ``settings.redis_url`` if available."""
    from causeway import register

    register(DramatiqAdapter(broker_url=_broker_url_from_settings(settings)))


__all__ = ["DramatiqAdapter", "plugin"]
