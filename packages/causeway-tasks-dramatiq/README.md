# causeway-tasks-dramatiq

Dramatiq adapter for Causeway's `TaskAdapter` contract. Install:

```bash
uv add causeway-tasks-dramatiq
```

Register in `src/app/plugins.py`:

```python
from causeway import register
from causeway_tasks_dramatiq import DramatiqAdapter

register(DramatiqAdapter(broker_url="redis://localhost"))
```

Or let the entry point auto-load and read `settings.redis_url` from your config.

## Local dev

Run the API, worker, and scheduler as separate processes:

```bash
causeway dev
causeway-dramatiq worker --app app:app --tasks app.tasks
causeway-dramatiq scheduler --app app:app --tasks app.tasks
```

The worker command bootstraps the Causeway app, starts registered plugins with
your app settings, imports the task module so `@task` / `@cron` decorators run,
and registers Dramatiq actors for every task.

The scheduler command uses Periodiq and only emits `@cron` tasks. It does not
consume regular queues, so keep the worker running too.

For monorepos, wire those commands into your process runner explicitly:

```json
{
  "scripts": {
    "dev:worker": "causeway-dramatiq worker --app app:app --tasks app.tasks",
    "dev:cron": "causeway-dramatiq scheduler --app app:app --tasks app.tasks"
  }
}
```

Use repeated `--tasks` or comma-separated modules when tasks live in more than
one package:

```bash
causeway-dramatiq worker --tasks app.tasks --tasks app.integrations.tasks
causeway-dramatiq scheduler --tasks app.tasks,app.integrations.tasks
```
