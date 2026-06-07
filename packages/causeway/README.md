# causeway (Python)

> A lean backend framework for type-safe Python APIs.

```bash
uv add causeway
```

This is the core Python package of [Causeway](https://github.com/ruwadgroup/causeway). It ships:

- A **file-based router** that walks `src/app/routes/**/*.py`, picks up `$id.py`, `(group)/`, `_middleware.py`, and `_scope.py`, and registers handlers into the app's route table.
- A **typed config layer** that wraps `pydantic-settings` and exposes non-secret fields to the generated TypeScript client.
- A **scoped DI container** driven by `_scope.py` providers.
- A **`@task` contract** for background jobs with a Dramatiq reference adapter.
- A **plugin registry** with Python-entry-point discovery and per-environment activation.
- A **route-key client generator** that emits typed TypeScript clients from the same route IR.
- An **App Graph** that exposes routes, scopes, permissions, middleware, providers, tasks, plugins, events, and refresh contracts.
- A **CLI** (`causeway new`, `causeway dev`, `causeway build`, `causeway inspect`, `causeway deploy <target>`) that runs the whole loop.

For the full story, the design rationale, and a side-by-side vs. FastAPI / Django + Ninja / Encore.ts / NestJS, see the [repo README](https://github.com/ruwadgroup/causeway).

## 30-second example

```
my-app/
├── pyproject.toml
├── causeway.toml
└── src/app/
    ├── config.py
    ├── plugins.py
    └── routes/
        ├── _middleware.py
        ├── index.py
        └── users/
            ├── _scope.py
            ├── index.py
            └── $id.py
```

```python
# src/app/routes/users/$id.py
from typing import Annotated
from uuid import UUID
from msgspec import Struct
from causeway import get, raises
from causeway.errors import NotFound

class User(Struct):
    id: UUID
    name: str

@get
@raises(NotFound)
async def show(id: UUID) -> User:
    ...
```

Run it:

```bash
causeway dev
```

`causeway dev` discovers the routes, boots uvicorn once, hot-swaps route edits without restarting the process, and exposes `/__causeway` with the route tree, registered tasks, current config, plugin list, and App Graph.

The public client identity is the route key:

```ts
const user = await client.query("GET /users/$id", { id });
```

## Primitives in this package

| Primitive                                        | Purpose                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------ |
| File router (`$id.py`, `(group)/`)               | Discovery + URL pattern generation.                                      |
| `_middleware.py` / `_scope.py`                   | Per-subtree middleware + scoped DI providers.                            |
| `Settings` (wraps `pydantic-settings`)           | Typed config with allowlisted exposure to the generated client.          |
| `@get` / `@post` / `@put` / `@patch` / `@delete` | HTTP method decorators.                                                  |
| `@post(refreshes=...)`                           | Mutation refresh contract for the route-key client.                      |
| `@task(...)`                                     | Background-job contract; adapter-agnostic.                               |
| `@cron(...)`                                     | Scheduled tasks via the same adapter.                                    |
| `register(...)`                                  | Plugin registration (`TaskAdapter`, `Storage`, `KV`, `AuthProvider`, …). |
| `causeway inspect`                               | App Graph inspection.                                                    |
| `TestApp`                                        | Test client with DI overrides and `tasks_eager()` mode.                  |
| `causeway` CLI                                   | `new`, `dev`, `build`, `codegen`, `ir`, `inspect`, `openapi`, `deploy`.  |

Full reference: <https://github.com/ruwadgroup/causeway/tree/main/docs/reference>

## Optional extras

```bash
uv add 'causeway[dramatiq]'  # reference task adapter
uv add 'causeway[otel]'      # OpenTelemetry middleware hooks
uv add 'causeway[all]'       # everything
```

## Scope

Causeway ships project shape and a small set of contracts. It does **not** ship vertical integrations — no ORM, no admin panel, no template engine, no infrastructure provisioning. Those layers compose on top of the fundamentals and live in their own plugin packages or in user code.

## License

MIT
