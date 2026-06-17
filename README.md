<div align="center">

# Causeway

**A lean backend framework for type-safe Python APIs.**
**Your function signature is the API contract; the typed TypeScript client comes free.**

[![CI](https://github.com/ruwadgroup/causeway/actions/workflows/ci.yml/badge.svg)](https://github.com/ruwadgroup/causeway/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/causeway.svg)](https://pypi.org/project/causeway/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

[**Quickstart**](./docs/start/installation.md) · [**Why Causeway**](./docs/why-causeway.md) · [**Docs**](./docs) · [**Roadmap**](./ROADMAP.md)

</div>

## Why I built this

A while back I was working on AML (Anti-Money-Laundering) software for a client. Half the system was rules-and-graph-traversal work, and the other half — the half that actually caught the suspicious behavior — was ML models. Python was the only sane choice on the model side, so Python won the whole backend.

But I'm a React person at heart. I wanted the frontend story to feel as good as it does in Next.js or TanStack Start. So I reached for **FastAPI**, because it had the OpenAPI story going for it, and tried to make the contract flow from Python into the React app.

It mostly worked. But "mostly" is exactly where you start losing whole afternoons — the OpenAPI generators drift, the request/response shapes don't quite match what your handlers actually return, you end up writing the same `interface User` in three places. The seam between the Python types I'd just written and the TypeScript types my React app needed was always a little broken.

So I built the typed-RPC substrate that now lives inside Causeway: it walks Python signatures into an IR and emits a TypeScript client that matches what the server actually returns. No OpenAPI middle-man, no generator drift, no manual sync.

That substrate was the right primitive, but a primitive is not an application framework. It knew nothing about routing, config, DI, background jobs, middleware, or plugins. I needed the layer above it too — the thing that gives a backend a shape.

That layer is **Causeway**, and this is the framework I wish I'd had on that project.

## What it actually is

Causeway is a backend-first, Python-native framework. I kept it small on purpose: it contributes a handful of firm opinions to your application surface and stays out of the way everywhere else.

Here's what I gave it:

1. **File-based routing** — `$id.py`, `$id/`, `(group)/` route groups, `_middleware.py` / `_scope.py` per-tree composition. See [Backend routing](./docs/backend/routing.md).
2. **Typed config & DI** — a `pydantic-settings` wrapper with request-scoped providers. No DI container boilerplate.
3. **Middleware & scope composition** — one file at the root of a subtree wraps every route below it.
4. **A background-task contract** — `@task` decorator + adapter protocol. Dramatiq ships as the reference; swap to Celery / Arq / TaskIQ with one line.
5. **A plugin registry** — built-in optional adapters via `causeway[jwt]`, `causeway[s3]`, `causeway[sqlmodel]`, plus entry-point discovery for third-party plugins.
6. **A route-key client runtime** — generated TypeScript types plus one tiny client API: `query`, `mutate`, `refresh`, `stream`.
7. **An App Graph** — an inspectable, agent-readable map of routes, scopes, permissions, middleware, tasks, plugins, events, and refresh contracts.

Underneath, the typed-RPC layer (IR + TS codegen + streaming) is `causeway._runtime`. From where you sit as an application author, it's all just Causeway: you write Python handlers; Causeway registers them, validates them, builds the App Graph, and emits a TypeScript client from the same route IR.

Everything outside that surface — ORM, auth implementation, mailer, storage, cache, search — is a **plugin contract with a reference adapter**, not core.

## What I deliberately left out

- It's not an ORM. Use SQLModel / SQLAlchemy / Tortoise / your choice via `causeway[sqlmodel]` or another adapter.
- It's not an admin panel.
- It's not an HTML / template engine. The TypeScript client is generated; the frontend is yours.
- It's not an infrastructure provisioner. That's Terraform / Pulumi / Modal.

The full design philosophy, and the non-goals I hold to on purpose, live in [`docs/why-causeway.md`](./docs/why-causeway.md).

## A 30-second example

```
my-app/
├── pyproject.toml
├── causeway.toml
└── src/app/
    ├── config.py            # Settings(BaseSettings)
    ├── plugins.py           # register(DramatiqAdapter(...))
    └── routes/
        ├── _middleware.py
        ├── index.py         # /
        └── users/
            ├── _scope.py    # provides db session
            ├── index.py     # /users
            └── $id.py       # /users/{id}
```

```python
# src/app/routes/users/$id.py
from typing import Annotated
from uuid import UUID
from msgspec import Struct
from causeway import get, patch, raises
from causeway.errors import NotFound

class User(Struct):
    id: UUID
    name: str
    email: str

@get
@raises(NotFound)
async def show(id: UUID, db: Annotated[Session, get_session]) -> User:
    user = await db.get(User, id)
    if user is None:
        raise NotFound(f"user {id}")
    return user
```

```python
# src/app/routes/users/$id/screen.py
from causeway import post

@post(refreshes=("GET /users/$id", "GET /users"))
async def screen(id: UUID, db: Annotated[Session, get_session]) -> User:
    return await db.users.screen(id)
```

```bash
causeway dev
```

Here's what that one command does:

1. Discovers `src/app/routes/` → registers handlers.
2. Boots uvicorn once on `http://127.0.0.1:8000`.
3. Serves `/__causeway` — route tree, registered tasks, current config (secrets redacted), plugin list.
4. Hot-swaps route edits in-process; if a reload is bad, it keeps the previous app serving.

Route files use folders for URL structure. I reject dotted route filenames on purpose, so backend routes, middleware scopes, App Graph metadata, and frontend route keys all describe the same thing.

```ts
const user = await client.query("GET /users/$id", { id });
await client.mutate("POST /users/$id/screen", { id });
```

That string isn't an operation name some generator invented. It's the public route key Causeway derives straight from your file tree.

## Why you'd reach for it

- **Signature-as-contract.** Your handler's Python signature _is_ the wire schema. No `class CreatePostRequest(BaseModel)` mirrored in three files.
- **Route keys, not generated folklore.** The client calls the route you wrote: `"GET /users/$id"`, `"POST /users/$id/screen"`.
- **Refreshes live next to the mutation.** A backend mutation can declare `refreshes=...`; the client runtime handles the cache update after success.
- **Project shape for free.** File-based routing, scoped DI, middleware, plugin registry — all there the moment you scaffold.
- **Plugins, not batteries.** Core ships contracts and one reference adapter each. Pick a real backend with one line in `plugins.py`.
- **Cloud-agnostic.** No provisioner, no platform lock-in. Runs anywhere ASGI runs.
- **Encore-style conventions, without Encore's cloud.**

## How it compares

|                     | **Causeway**      | FastAPI        | Django + Ninja | Encore.ts        | NestJS          |
| ------------------- | ----------------- | -------------- | -------------- | ---------------- | --------------- |
| Scope               | Backend framework | Router lib     | Full framework | Backend + infra  | Structural      |
| Owns ORM?           | **No**            | No             | Yes            | Declarative      | No              |
| Owns auth?          | **No** (plugins)  | No             | Yes            | Partial          | Partial         |
| File-based routing? | **Yes**           | No             | No             | No               | No              |
| Cloud lock-in?      | **None**          | None           | None           | Medium           | None            |
| Closest comparison  | —                 | Building block | Heavy alt      | Closest ambition | Structural peer |

The full positioning matrix and the trade-offs I made are in [`docs/why-causeway.md`](./docs/why-causeway.md).

## Install

> Causeway is in **alpha** (`0.1.0a0`). The version pin opts you into the
> prerelease channel. Once v0.1.0 ships, drop the pin.

```bash
uv add 'causeway==0.1.0a0'
```

## Stability

It's pre-1.0, so pin exact versions. Here's what I'm committing to after 1.0:

- **Patch + minor never break.**
- **Major bumps follow a deprecation cycle** — one full minor of warnings before removal.
- **The plugin contract is part of the stable surface.**

Details in [`docs/stability/`](./docs/stability) — semver, IR stability, LTS.

## Packages

| Package                                            | What it is                                                   | Status |
| -------------------------------------------------- | ------------------------------------------------------------ | ------ |
| [`causeway`](./packages/causeway) (PyPI)           | Core framework: routing, config, DI, tasks, plugin registry. | v0.1 α |
| [`@causewayjs/client`](./packages/causeway-client) | Owned route-key client runtime.                              | v0.1 α |
| [`@causewayjs/react`](./packages/causeway-react)   | React provider, `useQuery`, and `useMutation`.               | v0.1 α |
| [`@causewayjs/next`](./packages/causeway-next)     | Next.js server client, prefetch, hydrate helpers.            | v0.1 α |
| [`@causewayjs/ts`](./packages/causeway-ts)         | Low-level transport and shared runtime primitives.           | v0.1 α |

The official adapter set lives inside [`causeway.contrib`](./packages/causeway/src/causeway/contrib) and installs through extras like `causeway[dramatiq]`, `causeway[s3]`, `causeway[jwt]`, and `causeway[sqlmodel]`. Full inventory and roadmap in [`ROADMAP.md`](./ROADMAP.md#plugin-ecosystem).

> React and Next.js are the bindings I maintain. Any other framework can ride on the same `@causewayjs/ts` runtime — if you build a binding for one, I'd love to point people at it.

## Contributing

The issues I value most start with "I tried to use Causeway for X and got confused." Skim [CONTRIBUTING.md](./CONTRIBUTING.md) for the on-ramp, and if you're going deep, [`docs/internals/`](./docs/internals) is the contributor's tour of the codebase.

## License

[MIT](./LICENSE).
