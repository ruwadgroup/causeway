"""Background tasks.

The :func:`task` decorator marks a coroutine, the :func:`cron` decorator
schedules one, and :class:`InMemoryAdapter` is the reference broker.
Production adapters such as Dramatiq live under :mod:`causeway.contrib` and
replace the in-memory one via the plugin registry.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Any, ClassVar, Literal, get_type_hints
from uuid import UUID

_log = logging.getLogger("causeway.tasks")

Backoff = Literal["fixed", "linear", "exponential"]


@dataclass(slots=True)
class TaskState:
    """Snapshot returned by ``adapter.status()``."""

    state: Literal["pending", "running", "complete", "failed", "cancelled"]
    result: Any = None
    error: str | None = None


@dataclass(slots=True)
class TaskRef:
    """Handle to a registered ``@task`` function.

    Adapters use ``module`` + ``name`` to identify a task on the wire so a
    queued job survives a process restart. The original callable is kept on
    the ref so the eager / in-process adapter can dispatch directly.
    """

    module: str
    name: str
    queue: str = "default"
    retries: int = 0
    backoff: Backoff = "exponential"
    fn: Callable[..., Awaitable[Any]] | None = None

    async def enqueue(self, *args: Any, **kwargs: Any) -> str:
        adapter = _active_adapter()
        payload = _encode(args, kwargs)
        result: str = await adapter.enqueue(self, payload)
        return result

    async def schedule(self, when: datetime, *args: Any, **kwargs: Any) -> str:
        adapter = _active_adapter()
        payload = _encode(args, kwargs)
        result: str = await adapter.schedule(self, when, payload)
        return result

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"TaskRef({self.module}.{self.name}, queue={self.queue!r})"


_registered_tasks: dict[str, TaskRef] = {}
_cron_jobs: list[tuple[TaskRef, str]] = []


def task(
    *,
    queue: str = "default",
    retries: int = 0,
    backoff: Backoff = "exponential",
) -> Callable[[Callable[..., Awaitable[Any]]], TaskRef]:
    """Mark a coroutine as a background task.

    The decorator returns a :class:`TaskRef` — calling it directly raises,
    forcing users through ``.enqueue(...)``. That keeps the failure mode
    obvious: you can't accidentally execute a task in-band by forgetting
    the ``.enqueue``.

    Task args are JSON-serialized by :func:`_encode`. UUID / datetime / date /
    Decimal values survive the wire as their string forms; the decorator reads
    the function's type hints once and casts incoming string args back to the
    annotated type before calling the body. Untyped args pass through unchanged,
    so existing tasks keep working.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> TaskRef:
        wrapped = _wrap_with_coercion(fn)
        ref = TaskRef(
            module=getattr(fn, "__module__", "?"),
            name=fn.__name__,
            queue=queue,
            retries=retries,
            backoff=backoff,
            fn=wrapped,
        )
        key = f"{ref.module}.{ref.name}"
        _registered_tasks[key] = ref
        return ref

    return decorator


def cron(expr: str) -> Callable[[Callable[..., Awaitable[Any]]], TaskRef]:
    """Mark a coroutine as cron-scheduled. Accepts standard 5-field crontab syntax."""

    def decorator(fn: Callable[..., Awaitable[Any]]) -> TaskRef:
        ref = task(queue="cron", retries=0)(fn)
        _cron_jobs.append((ref, expr))
        return ref

    return decorator


def registered_tasks() -> dict[str, TaskRef]:
    """Snapshot of every ``@task`` registered. Adapters use this on startup."""
    return dict(_registered_tasks)


def cron_jobs() -> list[tuple[TaskRef, str]]:
    """Snapshot of every ``@cron`` registration."""
    return list(_cron_jobs)


def _clear() -> None:
    """For tests. Reset the module registries between cases."""
    _registered_tasks.clear()
    _cron_jobs.clear()


# A contextvar lets ``tasks_eager()`` swap the adapter for the current task
# only — without it, eager mode in one test would leak into concurrently
# running tests.
_adapter_var: ContextVar[Any] = ContextVar("_causeway_task_adapter")


def set_adapter(adapter: Any) -> None:
    """Install the default adapter the rest of the process will use."""
    _adapter_var.set(adapter)


def _active_adapter() -> Any:
    try:
        return _adapter_var.get()
    except LookupError as exc:
        msg = (
            "No TaskAdapter registered. Call causeway.tasks.set_adapter(...) at boot, "
            "or use a TaskAdapter plugin in src/app/plugins.py."
        )
        raise RuntimeError(msg) from exc


# Adapters install a per-run probe here so the task body can poll
# ``cancel_requested()`` without holding a reference to the adapter. The
# default returns False so calls outside a task body are harmless.
_cancel_check_var: ContextVar[Callable[[], bool]] = ContextVar(
    "_causeway_cancel_check", default=lambda: False
)


def cancel_requested() -> bool:
    """Return True if cancellation has been requested for the current task.

    Long-running task bodies should poll this between units of work and exit
    cleanly when it flips. Outside a task (or for adapters that don't support
    cancellation) it always returns False.
    """
    return _cancel_check_var.get()()


async def raise_if_cancelled() -> None:
    """Raise :class:`asyncio.CancelledError` if cancellation was requested.

    Convenience for tasks that prefer the "checkpoint" pattern over checking
    a boolean. The adapter recognizes ``CancelledError`` and transitions the
    task to ``cancelled`` instead of ``failed``.
    """
    if cancel_requested():
        raise asyncio.CancelledError


_DEFAULT_ENCODERS: dict[type, Callable[[Any], Any]] = {
    UUID: str,
    datetime: lambda v: v.isoformat(),
    date: lambda v: v.isoformat(),
    Decimal: str,
}


_DEFAULT_DECODERS: dict[type, Callable[[Any], Any]] = {
    UUID: lambda v: v if isinstance(v, UUID) else UUID(v),
    datetime: lambda v: v if isinstance(v, datetime) else datetime.fromisoformat(v),
    date: lambda v: v if isinstance(v, date) else date.fromisoformat(v),
    Decimal: lambda v: v if isinstance(v, Decimal) else Decimal(v),
}


def _json_default(value: Any) -> Any:
    for cls, enc in _DEFAULT_ENCODERS.items():
        if isinstance(value, cls):
            return enc(value)
    msg = f"unencodable task arg: {type(value).__name__}"
    raise TypeError(msg)


def _encode(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    return json.dumps({"args": list(args), "kwargs": kwargs}, default=_json_default).encode()


def _decode(payload: bytes) -> tuple[tuple[Any, ...], dict[str, Any]]:
    data = json.loads(payload)
    return tuple(data.get("args", [])), data.get("kwargs", {})


def _wrap_with_coercion(
    fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Wrap ``fn`` so JSON-decoded args are cast to their annotated types.

    JSON has no native UUID / datetime / Decimal — those round-trip as strings.
    Reading hints once at registration time keeps the call-time path cheap;
    functions whose args are all plain JSON-friendly types get no wrapper.
    """
    try:
        hints = get_type_hints(fn)
        sig = inspect.signature(fn)
    except (TypeError, ValueError, NameError):
        return fn

    coercers: dict[str, Callable[[Any], Any]] = {}
    for name in sig.parameters:
        ann = hints.get(name)
        coercer = _DEFAULT_DECODERS.get(ann) if ann is not None else None
        if coercer is not None:
            coercers[name] = coercer

    if not coercers:
        return fn

    @wraps(fn)
    async def coerced(*args: Any, **kwargs: Any) -> Any:
        try:
            bound = sig.bind_partial(*args, **kwargs)
        except TypeError:
            return await fn(*args, **kwargs)
        for name, value in bound.arguments.items():
            c = coercers.get(name)
            if c is not None and value is not None:
                bound.arguments[name] = c(value)
        return await fn(*bound.args, **bound.kwargs)

    return coerced


@dataclass(slots=True)
class _RunRecord:
    state: TaskState
    fut: asyncio.Future[Any] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )
    # The asyncio.Task running the body. ``cancel()`` hard-cancels it after
    # the cooperative grace window expires.
    runner: asyncio.Task[Any] | None = None
    cancel_requested: bool = False


class InMemoryAdapter:
    """In-process reference adapter.

    Each ``enqueue`` schedules an ``asyncio.Task`` that runs the underlying
    function with the decoded payload. Status / result are kept in a dict so
    a caller can poll. ``eager()`` switches to synchronous execution — useful
    in tests that want to assert on task side-effects before the test exits.

    Retry/backoff: the in-memory adapter implements ``fixed`` /``linear`` /
    ``exponential`` with a 100 ms base.
    """

    contract_version: ClassVar[str] = "v1.1"

    def __init__(self) -> None:
        self._records: dict[str, _RunRecord] = {}
        self._cron_tasks: list[asyncio.Task[None]] = []
        self._inflight: set[asyncio.Task[None]] = set()
        self._eager = False

    def _track(self, record: _RunRecord, coro: Awaitable[None]) -> asyncio.Task[None]:
        """Create an asyncio task for ``coro``, record it on ``record`` for cancel,
        and keep a strong reference so the event loop doesn't garbage-collect it."""
        runner: asyncio.Task[None] = asyncio.create_task(coro)  # type: ignore[arg-type]
        record.runner = runner
        self._inflight.add(runner)
        runner.add_done_callback(self._inflight.discard)
        return runner

    async def startup(self, settings: Any) -> None:
        set_adapter(self)
        for ref, expr in cron_jobs():
            self._cron_tasks.append(asyncio.create_task(self._cron_loop(ref, expr)))

    async def shutdown(self) -> None:
        for t in self._cron_tasks:
            t.cancel()
        for t in self._cron_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._cron_tasks.clear()
        self._records.clear()

    async def ready(self) -> bool:
        return True

    async def enqueue(self, task: TaskRef, payload: bytes) -> str:
        task_id = uuid.uuid4().hex
        record = _RunRecord(state=TaskState(state="pending"))
        self._records[task_id] = record

        coro = self._run(task, task_id, payload)
        if self._eager:
            await coro
        else:
            self._track(record, coro)
        return task_id

    async def schedule(self, task: TaskRef, when: datetime, payload: bytes) -> str:
        delay = max(0.0, (when - datetime.now(when.tzinfo)).total_seconds())
        task_id = uuid.uuid4().hex
        record = _RunRecord(state=TaskState(state="pending"))
        self._records[task_id] = record

        async def later() -> None:
            await asyncio.sleep(delay)
            # Cancelled while still in the sleep window — skip dispatch.
            if record.cancel_requested:
                return
            await self._run(task, task_id, payload)

        self._track(record, later())
        return task_id

    async def cron(self, task: TaskRef, expr: str) -> None:
        self._cron_tasks.append(asyncio.create_task(self._cron_loop(task, expr)))

    def eager(self) -> contextlib.AbstractAsyncContextManager[None]:
        return self._eager_context()

    @contextlib.asynccontextmanager
    async def _eager_context(self) -> AsyncIterator[None]:
        prev = self._eager
        self._eager = True
        try:
            yield
        finally:
            self._eager = prev

    async def status(self, task_id: str) -> TaskState:
        record = self._records.get(task_id)
        if record is None:
            return TaskState(state="failed", error=f"unknown task {task_id}")
        return record.state

    async def cancel(self, task_id: str, *, grace: float = 5.0) -> bool:
        """Request cancellation of ``task_id``.

        Cooperative first: flips a flag the body polls via
        ``cancel_requested()`` / ``raise_if_cancelled()``. If the task is still
        running after ``grace`` seconds, hard-cancel the underlying
        ``asyncio.Task``. Returns True if a cancel was issued, False if the
        task is unknown or already terminal.
        """
        record = self._records.get(task_id)
        if record is None:
            return False
        if record.state.state in ("complete", "failed", "cancelled"):
            return False
        record.cancel_requested = True

        # If the runner is still queued (``schedule()`` sleep window), tear it
        # down now so the body never starts and status() reflects the cancel.
        if record.state.state == "pending" and record.runner is not None:
            record.runner.cancel()
            record.state = TaskState(state="cancelled")
            return True

        runner = record.runner
        if runner is None or runner.done():
            if record.state.state != "cancelled":
                record.state = TaskState(state="cancelled")
            return True

        try:
            await asyncio.wait_for(asyncio.shield(runner), timeout=grace)
        except TimeoutError:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runner
        except (asyncio.CancelledError, Exception):
            # Body finished (cleanly or with an error) within the grace window;
            # _run already wrote the terminal state.
            pass
        return True

    async def result(self, task_id: str) -> Any:
        record = self._records.get(task_id)
        if record is None:
            msg = f"unknown task {task_id}"
            raise KeyError(msg)
        return await record.fut

    async def _run(self, task: TaskRef, task_id: str, payload: bytes) -> None:
        record = self._records[task_id]
        if task.fn is None:
            record.state = TaskState(state="failed", error=f"{task!r} has no callable")
            record.fut.set_exception(RuntimeError(record.state.error))
            return
        args, kwargs = _decode(payload)
        record.state = TaskState(state="running")
        # Bind the cancel probe so the body's ``cancel_requested()`` /
        # ``raise_if_cancelled()`` calls see this record.
        token = _cancel_check_var.set(lambda: record.cancel_requested)
        attempt = 0
        last_exc: BaseException | None = None
        try:
            while attempt <= task.retries:
                try:
                    result = await task.fn(*args, **kwargs)
                except asyncio.CancelledError:
                    # Cooperative raise or hard cancel — either way terminal,
                    # not a retry candidate.
                    record.state = TaskState(state="cancelled")
                    if not record.fut.done():
                        record.fut.set_exception(asyncio.CancelledError())
                    return
                except Exception as exc:
                    last_exc = exc
                    if attempt == task.retries:
                        break
                    await asyncio.sleep(_backoff_delay(task.backoff, attempt))
                    attempt += 1
                    continue
                # Body returned cleanly after seeing the cancel flag — record
                # it as a cancel so callers can tell "you stopped because I
                # asked" apart from "you finished the work."
                if record.cancel_requested:
                    record.state = TaskState(state="cancelled")
                    if not record.fut.done():
                        record.fut.set_exception(asyncio.CancelledError())
                else:
                    record.state = TaskState(state="complete", result=result)
                    if not record.fut.done():
                        record.fut.set_result(result)
                return
            record.state = TaskState(state="failed", error=str(last_exc))
            if not record.fut.done():
                assert last_exc is not None
                record.fut.set_exception(last_exc)
        finally:
            _cancel_check_var.reset(token)

    async def _cron_loop(self, task: TaskRef, expr: str) -> None:
        try:
            from causeway._cron import next_fire

            while True:
                delay = next_fire(expr, datetime.now())
                await asyncio.sleep(delay)
                await self.enqueue(task, _encode((), {}))
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("cron loop crashed for %r", task)


def _backoff_delay(strategy: Backoff, attempt: int) -> float:
    base = 0.1
    if strategy == "fixed":
        return base
    if strategy == "linear":
        return base * (attempt + 1)
    delay: float = base * (2**attempt)
    return delay


def tasks_eager() -> contextlib.AbstractAsyncContextManager[None]:
    ctx: contextlib.AbstractAsyncContextManager[None] = _active_adapter().eager()
    return ctx


__all__ = [
    "Backoff",
    "InMemoryAdapter",
    "TaskRef",
    "TaskState",
    "cancel_requested",
    "cron",
    "cron_jobs",
    "raise_if_cancelled",
    "registered_tasks",
    "set_adapter",
    "task",
    "tasks_eager",
]
