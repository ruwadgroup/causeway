# Internals

A contributor's tour. These docs are aimed at people who are reading or modifying Causeway itself — fixing a routing bug, writing a new plugin contract, cutting a release.

If you're trying to **use** Causeway to build an app, you're in the wrong directory. Start at [the docs root](../README.md).

## In this directory

- **[Architecture](./architecture.md)** — the 30-second mental model and the layer-by-layer tour. What happens when you type `causeway dev`.
- **[Code map](./code-map.md)** — every file in `packages/causeway/src/causeway/` annotated. The thing you read once and bookmark.
- **[Contributing (deep)](./contributing.md)** — beyond the top-level [CONTRIBUTING.md](../../CONTRIBUTING.md): coding conventions, when to add a comment vs. delete one, how to handle bundled adapters, why a public symbol gets re-exported.
- **[Testing strategy](./testing.md)** — what we test, what we don't, where the bar is.
- **[Releases](./releases.md)** — how release-please drives PyPI publishes, what changes versioning, how to ship a hotfix.
- **[Writing a new official adapter](./plugin-authoring.md)** — the on-ramp for a maintainer adding a bundled `causeway.contrib` adapter.
- **[Runtime substrate](../architecture/runtime-substrate.md)** — `causeway._runtime`: the typed-RPC engine under the convention layer. Read this before touching `_runtime/*` or before building a different framework on the same primitives.

## Quick orientation

```
causeway/                                     # monorepo root (pnpm workspace)
├── packages/
│   ├── causeway/                             # the core framework (PyPI: causeway)
│   │   ├── src/causeway/                     # see code-map.md
│   │   │   └── contrib/                      # official optional adapters
│   │   ├── tests/                        # pytest, asyncio mode auto
│   │   ├── pyproject.toml                # hatchling build, ruff/mypy/pytest config
│   │   └── pyrightconfig.json            # package-local pyright config
│   ├── causeway-client/                      # owned route-key client runtime
│   ├── causeway-react/                       # React provider + hooks
│   └── causeway-next/                        # Next.js server helpers
├── examples/                             # runnable starter projects, not published
├── docs/                                 # what you're reading
├── pyrightconfig.json                    # root pyright config — points venv at packages/causeway/.venv
└── .github/                              # CI, issue templates, workflows
```

## Where things live, at a glance

| Concern                                         | Lives in                                          |
| ----------------------------------------------- | ------------------------------------------------- |
| **Runtime substrate** (RPC engine, IR, codegen) | `packages/causeway/src/causeway/_runtime/`        |
| File-based router                               | `packages/causeway/src/causeway/routing.py`       |
| URL pattern translation                         | `packages/causeway/src/causeway/_paths.py`        |
| Handler decorators                              | `packages/causeway/src/causeway/_methods.py`      |
| App factory                                     | `packages/causeway/src/causeway/app.py`           |
| App Graph                                       | `packages/causeway/src/causeway/graph.py`         |
| Config (`Settings`)                             | `packages/causeway/src/causeway/config.py`        |
| Scoped DI                                       | `packages/causeway/src/causeway/scope.py`         |
| Plugin registry                                 | `packages/causeway/src/causeway/plugins.py`       |
| Plugin contracts (Protocols)                    | `packages/causeway/src/causeway/contracts.py`     |
| Reference adapters in core                      | `packages/causeway/src/causeway/adapters.py`      |
| Background tasks                                | `packages/causeway/src/causeway/tasks.py`         |
| Cron parser                                     | `packages/causeway/src/causeway/_cron.py`         |
| Middleware base + `@guard`                      | `packages/causeway/src/causeway/middleware.py`    |
| Observability (request id, OTel)                | `packages/causeway/src/causeway/observability.py` |
| Errors + handlers                               | `packages/causeway/src/causeway/errors.py`        |
| Health endpoints                                | `packages/causeway/src/causeway/health.py`        |
| Diagnostics (`/__causeway`)                     | `packages/causeway/src/causeway/diagnostics.py`   |
| Rich tracebacks + ASGI shield                   | `packages/causeway/src/causeway/_traceback.py`    |
| Testing kit                                     | `packages/causeway/src/causeway/testing.py`       |
| CLI                                             | `packages/causeway/src/causeway/cli.py`           |
| Scaffolding (`causeway new`)                    | `packages/causeway/src/causeway/_scaffold.py`     |

## The rule that decides most arguments

> If there are two reasonable ways to do something, one of them is wrong and we kill it.

That's it. That's the rule. It's why the docs are short and the code is short.
