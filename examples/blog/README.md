# blog — the deep example

A full blog API in ~500 LOC that exercises every primitive Causeway ships in
v0.1: file routing with `$id.py` and nested subtrees, scoped DI via
`_scope.py`, per-subtree middleware, typed errors, background tasks,
cron, lifespan hooks, plugin registration, typed settings, and an
isolated test suite that drives the whole thing through `httpx`.

## What's in it

| Feature                        | Where it lives                                        |
| ------------------------------ | ----------------------------------------------------- |
| `Settings` (pydantic-settings) | `app/config.py`                                       |
| SQLAlchemy async engine + ORM  | `app/db.py`                                           |
| Scoped DI providers            | `app/deps.py` + `app/routes/**/_scope.py`             |
| App-wide middleware            | `app/routes/_middleware.py` (response-time header)    |
| Public read endpoints          | `app/routes/posts/...`                                |
| Token-gated admin endpoints    | `app/routes/admin/...` (via `current_admin` provider) |
| `@task` + `@cron`              | `app/tasks.py`                                        |
| Plugin registration            | `app/plugins.py`                                      |
| Lifespan hooks                 | `app/lifespan.py`                                     |
| Tests                          | `tests/test_blog.py`                                  |

## Layout

```
blog/
├── pyproject.toml
├── causeway.toml
├── .env.example
├── app/
│   ├── config.py             # Settings(BaseSettings)
│   ├── db.py                 # SQLAlchemy: engine, models, create_all
│   ├── deps.py               # @provide("db") + @provide("admin")
│   ├── tasks.py              # @task + @cron
│   ├── notifications.py      # in-process notification sink
│   ├── plugins.py            # register InMemoryAdapter for tasks
│   ├── lifespan.py           # startup/shutdown
│   ├── app.py                # `app = create_app("app/routes")`
│   └── routes/
│       ├── _middleware.py    # TimingHeader (x-response-time on every reply)
│       ├── _scope.py         # root: fires lifespan + plugin startup
│       ├── index.py          # GET /
│       ├── posts/
│       │   ├── _scope.py     # db_session provider
│       │   ├── index.py      # GET /posts
│       │   └── $id/
│       │       ├── index.py  # GET /posts/{id}
│       │       └── comments.py  # POST /posts/{id}/comments
│       └── admin/
│           ├── _scope.py     # db_session + current_admin providers
│           ├── stats.py      # GET /admin/stats
│           └── posts/
│               ├── index.py  # GET /admin/posts · POST /admin/posts
│               └── $id.py   # PATCH /admin/posts/{id} · DELETE /admin/posts/{id}
└── tests/
    └── test_blog.py
```

## Run

```bash
cd examples/blog
cp .env.example .env        # optional — defaults work for local dev
uv sync
uv run uvicorn app.app:app --reload
```

```bash
uv run pytest               # exercises the full request/task flow
```

## Try it

```bash
# Public read paths
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/posts

# Admin (bearer token from .env / .env.example)
TOKEN=changeme-in-prod

curl -X POST http://127.0.0.1:8000/admin/posts \
  -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"title":"hello","body":"world","published":true}'

curl http://127.0.0.1:8000/posts/1

curl -X POST http://127.0.0.1:8000/posts/1/comments \
  -H "content-type: application/json" \
  -d '{"author":"ada","body":"first!"}'

curl -H "authorization: Bearer $TOKEN" http://127.0.0.1:8000/admin/stats
# → {"ok":true,"data":{"posts":1,"published":1,"comments":1,"recent_notifications":1}}
```

The diagnostics page at `http://127.0.0.1:8000/__causeway` shows the
discovered route tree, the registered plugins, the current settings
(secrets redacted), and the registered `@task`/`@cron` jobs.

## How the wiring fits together

### 1. Providers (`app/deps.py`)

Providers are normal functions decorated with `@provide(name)`. They're
defined in `app/deps.py` so route files and `_scope.py` files can both
import the same function object. The file router matches
`Annotated[T, provider]` parameters to registered providers by
`(filename, qualname)` — so as long as both sides reference the same
function, the rewrite to `Depends(provider)` happens automatically.

```python
# app/deps.py
@provide("db")
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 2. Scope files

A `_scope.py` registers providers for everything in its subtree. To
register `db_session` for `/posts`, the scope file just imports it:

```python
# app/routes/posts/_scope.py
from app.deps import db_session  # noqa: F401  # discovered by name
```

The router scans the module namespace for callables stamped with
`__causeway_provide__` and registers them.

### 3. Handlers consume providers via `Annotated`

```python
# app/routes/posts/index.py
from app.deps import db_session

@get
async def list_posts(db: Annotated[AsyncSession, db_session]) -> list[PostSummary]:
    ...
```

> ⚠️ **Don't use `from __future__ import annotations` in route files
> that consume providers.** PEP 563 keeps annotations as strings; the
> file router needs real `typing.Annotated` objects to rewrite them
> into `Depends(provider)` calls. (You can still use it elsewhere.)

### 4. Admin auth via DI

`current_admin` is just another provider — it pulls the bearer token
off the request and raises `Unauthorized` if it's missing or wrong.
Every admin handler depends on it and declares `@raises(Unauthorized)`
so the failure flows through Causeway's `Result<T, E>` envelope and into
the generated TS client as a typed error branch.

```python
@get
@raises(Unauthorized)
async def stats(
    db: Annotated[AsyncSession, db_session],
    admin: Annotated[str, current_admin],
) -> Stats:
    ...
```

### 5. Background tasks

`@task` registers a coroutine with the active adapter. Calling
`my_task.enqueue(...)` queues it. `@cron` schedules a task on a
crontab expression. `app/plugins.py` wires the in-process
`InMemoryAdapter`; swap it for `causeway[dramatiq]` / Celery / Arq
without touching any handler code.

```python
@task(queue="emails", retries=3, backoff="exponential")
async def notify_new_comment(post_id: int, author: str) -> None:
    record("new_comment", post_id=post_id, author=author)
```

```python
# inside the POST /posts/{id}/comments handler
await notify_new_comment.enqueue(id, data.author)
```

### 6. Lifespan + plugin startup

`create_app()` loads sibling `app/lifespan.py` and `app/plugins.py`.
During ASGI startup it runs app lifespan startup, then plugin startup,
then any route-scope startup hooks. Shutdown runs in reverse.

```python
# app/lifespan.py
async def startup() -> None:
    await create_all()

async def shutdown() -> None:
    await dispose()
```

## What the response envelope looks like

Handlers decorated with `@raises(...)` return Causeway's `Result<T, E>` envelope:

```
{ "ok": true,  "data":  {...} }                # success
{ "ok": false, "error": { "kind": "NotFound", "message": "...", "detail": {} } }
```

The HTTP status stays 200; the discriminated `error.kind` is what the
generated TS client narrows on. Handlers without `@raises` return the
bare value (see `GET /posts`, which yields a plain `list[PostSummary]`).

## Notes / gotchas you'll hit

- **Route groups (`(group)/`) are stripped from URLs.** Two files at
  `(public)/posts/index.py` and `(admin)/posts/index.py` would both
  register `GET /posts` and conflict. Use real directory names
  (`posts/`, `admin/posts/`) when you want a different URL prefix.
- **Class `Middleware` instances apply globally**, regardless of which
  subtree's `_middleware.py` they're declared in. The `TimingHeader`
  in `app/routes/_middleware.py` stamps every response in the app.
  Subtree-scoped behavior belongs in providers (DI) or in handler
  logic.
