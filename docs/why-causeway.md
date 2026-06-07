# Why Causeway

This is the long version of the story in the README — why Causeway exists, what it deliberately won't do, and how it compares to everything in the same lane. If you only want to know "what is this thing" you can skim the headings.

## The story

A while back I was working on AML — Anti-Money-Laundering — software for a client. The problem space is roughly half rules-and-graph traversal (here's a customer, here are their transactions over 90 days, do any of these patterns look like layering?) and half ML — gradient-boosted trees, anomaly detection, the occasional graph neural network for entity resolution. Python wasn't a preference, it was the only sane choice. So Python won the whole backend.

The trouble was that I'm a React person, and I have been since around the time hooks shipped. I'd spent years inside Next.js and, more recently, TanStack Start, and I'd gotten very used to the idea that **the type at the API boundary is the same type on both sides** — change the response shape on the server, the client lights up red until you fix it. That's the world I wanted to keep living in even though the backend was now Python.

So I reached for FastAPI. It had the OpenAPI story going for it, and on paper that should mean a typed client falls out the other end for free.

In practice it didn't. The seam between the Python types I'd just written — `pydantic` models, `dataclasses`, `TypedDict`s — and the TypeScript types my React app needed was always a little broken. OpenAPI generators drift. The shapes don't quite match what the handler actually returns. The discriminated unions FastAPI emits don't compose the way TanStack's `Route` types compose. The path params come through as `string`, never the actual UUID I narrowed in the handler. I ended up writing the same `interface User` in three places — once in Pydantic, once in OpenAPI's intermediate schema, once by hand in the React code because the generator output wasn't quite right.

I tried four different OpenAPI-to-TypeScript generators. Some were better than others. None were good enough.

At some point I stopped trying to patch the gap and started thinking about what I actually wanted: a primitive that walks Python handlers directly into an IR (intermediate representation), then emits TypeScript that matches exactly what the server returns. No OpenAPI middle-man, no generator drift, no manual sync. The Python signature **is** the wire contract.

That primitive lives inside Causeway as `causeway._runtime` — a small, focused substrate that does one thing: typed-RPC from Python to TypeScript, with streaming primitives for SSE and bidirectional async iterators. It knows nothing about routing, config, dependency injection, background jobs, middleware, or plugins. That layering is intentional — if you ever want to build a different framework on the same RPC engine, [the substrate is documented and reachable](./architecture/runtime-substrate.md). But on its own it's not enough to ship a product.

**Causeway** is what you actually use: the substrate plus the layer that turns it into something you can build on. File-based routing, route-key client generation, scoped DI, middleware composition, a plugin registry, a background-task contract, observability, an App Graph, and the CLI that ties it all together. You write Python handlers; Causeway walks them into the IR, the codegen emits the TypeScript client, and your frontend gets exactly the types your server produces.

That's the whole shape: one install (`causeway`), one brand, but two layers under the hood — the runtime substrate and the convention layer on top of it.

## What I wanted that I wasn't getting elsewhere

These weren't bullet points I wrote down up front. They're the things I kept hitting friction on, in roughly the order I hit them.

**A signature that is the contract.** Not a signature plus a Pydantic model plus an OpenAPI spec plus a generated TypeScript interface. One source of truth, traced from Python to the wire to the client.

**File-based routing for the backend.** Next.js and TanStack Start taught me that the folder tree is a great route table. I missed that on the Python side. `app.route("/users/{id}", ...)` in a giant `urls.py` is fine but it's not what I want anymore.

**A client that doesn't invent a second naming system.** If the backend route is `routes/users/$id/screen.py`, the public client identity should be `"POST /users/$id/screen"`. Not `screenCustomer`, not `customers.screening.run`, not whatever an OpenAPI operation-name heuristic guesses today. The route key is boring, and boring is a feature.

**Cache refreshes as backend contract, not frontend folklore.** A mutation often knows which queries it makes stale. Causeway lets that live beside the mutation with `@post(refreshes=(...))`, then the client runtime does the simple thing after success. The frontend can still be clever, but it should not have to remember every invalidation edge by hand.

**A place to put middleware and DI providers that's _near_ the routes they apply to.** Not a single `main.py` that grows forever. Not a decorator stack on every handler. A `_middleware.py` or `_scope.py` at the root of a subtree, and everything under it inherits.

**Conventions over configuration, defaults over magic.** One place for routes, one for config, one for plugins. If two ways to do the same thing emerge, one of them is wrong and we should kill it.

**A plugin contract, not a kitchen sink.** Real apps have opinions about which ORM, which auth, which storage. The framework owning all of that — Django-style — is great for greenfield and terrible six months in. I wanted a framework that opinionated on **structure** and stayed neutral on **implementation**.

**The cloud-agnostic part.** Encore is the closest thing in spirit to what I wanted, but its cloud-coupled model wasn't where I needed to be — I had clients on AWS, on bare metal, on Modal, on a single VPS, and I didn't want my framework choice to constrain that.

Causeway is what those preferences look like when you actually sit down and build them.

## The six principles

If you boil the above into principles you can argue with, you get these. Each is a knife — it cuts things out as much as it decides what to keep.

### 1. Conventions over configuration, defaults over magic

Every choice has one obvious place; surprising behavior is a bug. There is one place to register a route (the routes directory), one place to declare config (`config.py`), one place to install plugins (`plugins.py`). If two ways to do the same thing emerge, one of them is wrong and we kill it.

### 2. Backend-first, client-aware

No template engine, no asset pipeline, no page router. Causeway owns the backend contract and the client runtime that speaks to it; your frontend framework remains yours. React and Next.js get small adapters over the same route-key client instead of each one inventing its own cache/invalidation story.

### 3. Plugins, not batteries

Core ships **contracts** (`TaskAdapter`, `Storage`, `KV`, `AuthProvider`, …) and **one reference adapter each**. Picking a real implementation is a one-line plugin install. We deliberately reject the Rails / Laravel / AdonisJS "framework owns everything" model — its productivity peak is greenfield, its mismatch with reality six months in is painful.

### 4. Type-driven, graph-grounded

Everything Causeway knows about your contract lives in the IR; everything Causeway knows about the application shape lives in the App Graph. Routes, route keys, scopes, permissions, middleware, tasks, plugins, events, and refresh contracts have one inspectable shape. There is no second source of truth.

### 5. General-purpose, narrow scope

Causeway binds the web / task surface and stops there. No ORM, no admin panel, no infra provisioning. Those layers move on a different cadence and live in user code or in dedicated libraries.

### 6. One artifact, anywhere

A Causeway app is an ASGI app + a manifest. It runs under `uvicorn` locally, in Docker, on Modal, on Fly, on Lambda (via Mangum) — without code changes. The deploy adapter is a wrapper around provider CLIs, not a hosting platform.

## The "lean core" boundary

The two coherent models in 2026 are:

- **Rails / Laravel / AdonisJS** — framework owns everything. Productivity peaks for greenfield; the mismatch with reality is painful.
- **Encore / Litestar / NestJS** — framework owns architecture and primitives, delegates implementations.

Causeway is the second model. We opinionate on **structure, lifecycle, naming, and contracts** — and stay deliberately neutral on **storage, identity, infrastructure, and presentation**.

## Positioning matrix

| Framework          | Scope                | Owns ORM?        | Owns auth? | File routing? | Closest comparison  |
| ------------------ | -------------------- | ---------------- | ---------- | ------------- | ------------------- |
| FastAPI            | router lib           | no               | no         | no            | building block      |
| Litestar           | API framework        | partial (SQLA)   | primitives | no            | peer-ish, lower     |
| Django + Ninja     | full framework       | yes              | yes        | no            | heavy alternative   |
| AdonisJS / Laravel | full-stack batteries | yes              | yes        | no            | what Causeway isn't |
| NestJS             | structural framework | no               | partial    | no            | structural peer     |
| Encore.ts / .go    | backend + infra      | no (declarative) | partial    | no            | closest ambition    |
| **Causeway**       | backend framework    | **no**           | **no**     | **yes**       | —                   |

In one sentence:

> _Encore-style conventions, Litestar-style scope, Next.js / TanStack-style routing, route-key client ergonomics, cloud-agnostic, ORM-agnostic, auth-agnostic by design._

## Explicitly out of scope, ever

These aren't "we haven't gotten to them yet." They're "we have decided not to do them, and someone proposing them will be politely redirected."

1. **No ORM as a default.** SQLModel lives behind the optional `causeway[sqlmodel]` extra; other ORMs can plug in the same way.
2. **No admin panel in core.** Recommend `sqladmin` / `Dashibase` / `retool` / `RowZero`. Maybe a `causeway-admin-*` plugin family someday.
3. **No HTML rendering / template engine in core.** The output is a JSON API + a typed TypeScript client. If you want HTMX, build it yourself; the framework won't fight you, but it also won't help.
4. **No infrastructure provisioning.** That's Terraform / Pulumi / Modal. `causeway deploy` shells out to provider CLIs; it does not manage your infrastructure.
5. **No owned frontend framework.** Causeway ships client runtimes and framework adapters. It does not own your pages, components, design system, or rendering strategy.

## Decision-forcing changes

If the world shifts, the plan shifts. Here are the specific shifts I've thought through, so it's easier to discuss them when they come up:

| If…                                               | Then…                                                                                |
| ------------------------------------------------- | ------------------------------------------------------------------------------------ |
| The IR can't represent task registrations cleanly | Add an `extensions` namespace upstream first; don't fork the IR.                     |
| Route params use one file-tree convention         | `$id` works in leaves and folders.                                                   |
| Dramatiq adoption is too low among target users   | Switch the reference to TaskIQ (newer, asyncio-native); keep the contract identical. |
| `pydantic-settings` v3 changes API significantly  | Vendor a thin wrapper that exposes a stable `Settings` interface.                    |
| User demand emerges for server-rendered HTML      | Don't add it. Recommend HTMX + a separate template lib. Hold the line.               |
| User demand emerges for multi-tenancy             | Add it in v0.3 as a `tenant` scope on `_scope.py` — not in v0.1.                     |

## Where to go from here

- **[Get started](./start/installation.md)** — install, scaffold, see the route tree and a typed handler in five minutes.
- **[Routing](./backend/routing.md)** — file-based routing with folders, route groups, middleware, and scopes.
- **[Plugins](./app/plugins.md)** — the plugin contract: discovery, registration, manifest.
- **[Tasks](./app/tasks.md)** — `@task` contract and the adapter ecosystem.
- **[Runtime substrate](./architecture/runtime-substrate.md)** — what lives inside `causeway._runtime`, when to reach into it, and how to build your own opinionated framework on the same RPC engine.
- **[Internals](./internals/README.md)** — contributor's tour of the codebase.
