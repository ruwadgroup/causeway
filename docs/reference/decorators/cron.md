# `@cron`

Schedule a coroutine on a cron expression.

```python
from causeway import cron

@cron("0 * * * *")            # every hour
async def hourly() -> None:
    await refresh_embeddings.enqueue()
```

## Signature

```python
cron(expr: str) -> Callable[[Coroutine], TaskRef]
```

`expr` is standard 5-field crontab syntax (`min hour day month weekday`).

Returns a [`TaskRef`](../classes/TaskRef.md), queued under `cron`, with retries disabled.

## How it runs

The cron loop is owned by the registered [`TaskAdapter`](../classes/contracts.md):

- **`InMemoryAdapter`** — internal asyncio loop with `next_fire` computation.
- **`DramatiqAdapter`** — `causeway-dramatiq scheduler` uses Periodiq to emit jobs,
  while `causeway-dramatiq worker` consumes them.
- **`CeleryAdapter`** — `celery-beat`.
- **`ArqAdapter`** — `cron_jobs`.

`@cron` doesn't take retry/backoff options — cron jobs should be idempotent. If you need retries, have the cron-body `enqueue` a regular `@task`.

## Common expressions

| Expression     | Meaning                |
| -------------- | ---------------------- |
| `* * * * *`    | every minute           |
| `0 * * * *`    | top of every hour      |
| `0 0 * * *`    | midnight UTC every day |
| `0 0 * * 0`    | midnight every Sunday  |
| `*/15 * * * *` | every 15 minutes       |

## See also

- [Tasks overview](../../app/tasks.md)
- [`@task`](./task.md)
