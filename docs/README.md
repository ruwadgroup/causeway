# Causeway Docs

Causeway is a backend-first Python framework for type-safe APIs. The folder tree is the route table, the Python signature is the contract, and the generated TypeScript client calls the same route keys your backend exposes.

```python
# src/app/routes/customers/$id.py
@get
async def show(id: UUID) -> Customer: ...
```

```ts
const customer = await client.query("GET /customers/$id", { id });
```

The core convention is deliberately small: route files create route keys, handlers describe contracts, and `refreshes` is the explicit mutation-to-query bridge. There is no generated nested method tree, no resource-key layer, and no second cache naming system.

## Start Here

Read these in order if you are new. They take you from an empty app to a small product slice with a typed route, generated client call, mutation, and `refreshes`.

1. **[Installation](./start/installation.md)** — scaffold or add Causeway to a project.
2. **[Project structure](./start/project-structure.md)** — where routes, config, plugins, and scopes live.
3. **[Your first route](./start/first-route.md)** — one typed handler, `curl`, generated client.
4. **[First product slice](./start/first-slice.md)** — a realistic detail route, mutation, `refreshes`, and React UI.

The longer design story is [Why Causeway](./why-causeway.md).

## Choose a Lane

| Lane                                  | Read when you are working on...                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **[Backend](./backend/index.md)**     | Route files, handlers, params, responses, errors, middleware, permissions, tenancy, idempotency. |
| **[Client](./client/index.md)**       | Generated TypeScript, route keys, refreshes, React, Next.js, App Graph.                          |
| **[Application](./app/index.md)**     | Config, plugins, tasks, events, webhooks, subscribers, testing, observability.                   |
| **[Deploy](./deploy/index.md)**       | Docker, Fly.io, Modal, binary builds, production shape.                                          |
| **[Reference](./reference/index.md)** | Public API, CLI, decorators, functions, classes, file conventions.                               |

## Common Tasks

| I want to...                      | Read this                                                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Define routes                     | [Defining routes](./backend/routing.md), [dynamic segments](./backend/dynamic-segments.md)                                        |
| Add middleware or DI near routes  | [Middleware](./backend/middleware.md), [scopes](./backend/scopes.md)                                                              |
| Read path params, query, body     | [Params and body](./backend/params-and-body.md)                                                                                   |
| Return data and typed errors      | [Responses](./backend/responses.md), [errors](./backend/errors.md)                                                                |
| Use the TypeScript client         | [Client runtime](./client/index.md)                                                                                               |
| Use React or Next.js              | [React](./client/react.md), [Next.js](./client/next.md)                                                                           |
| Refresh queries after a mutation  | [HTTP methods](./backend/methods.md#refresh-contracts), [client refreshes](./client/index.md#refreshes)                           |
| Inspect what Causeway discovered  | [App Graph](./client/app-graph.md), [`causeway inspect`](./reference/cli/inspect.md)                                              |
| Add auth, idempotency, or tenancy | [Permissions](./backend/permissions.md), [idempotency keys](./backend/idempotency.md), [multi-tenancy](./backend/multi-tenant.md) |
| Add tasks, events, or webhooks    | [Background tasks](./app/tasks.md), [events](./app/events.md), [webhooks](./app/webhooks.md)                                      |
| Test routes                       | [Testing](./app/testing.md), [inline scenarios](./app/inline-scenarios.md)                                                        |
| Deploy                            | [Deploying overview](./deploy/index.md), [Docker](./deploy/docker.md)                                                             |

## Core Concepts

**Routing**

- [Backend overview](./backend/index.md)
- [Defining routes](./backend/routing.md)
- [Dynamic segments](./backend/dynamic-segments.md)
- [Route groups](./backend/route-groups.md)
- [Middleware](./backend/middleware.md)
- [Scopes](./backend/scopes.md)

**Handlers**

- [HTTP methods](./backend/methods.md)
- [Params and body](./backend/params-and-body.md)
- [Responses](./backend/responses.md)
- [Errors](./backend/errors.md)
- [Streaming](./backend/streaming.md)
- [Pagination](./backend/pagination.md)
- [Batch endpoints](./backend/batch.md)
- [File uploads](./backend/file-uploads.md)

**Client Runtime**

- [Client runtime](./client/index.md)
- [React](./client/react.md)
- [Next.js](./client/next.md)
- [App Graph](./client/app-graph.md)

**Application Layer**

- [Application overview](./app/index.md)
- [Configuration](./app/configuration.md)
- [Plugins](./app/plugins.md)
- [Background tasks](./app/tasks.md)
- [Events](./app/events.md)
- [Webhooks](./app/webhooks.md)
- [Subscribers](./app/subscribers.md)
- [Observability](./app/observability.md)

## Reference

- [API Reference](./reference/index.md)
- [CLI Reference](./reference/cli/index.md)
- [File conventions](./reference/file-conventions/index.md)
- [Architecture](./architecture/index.md)
- [Stability](./stability/README.md)
- [Upgrading](./upgrading/index.md)
- [Internals](./internals/README.md)

Something confusing or missing? Open a [docs issue](https://github.com/ruwadgroup/causeway/issues/new?labels=docs).
