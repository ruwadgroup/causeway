# Code map

Every module in `packages/causeway/src/causeway/`, in roughly the order you'd read them on a first pass. Line counts are the actual size, not target sizes — the framework is small on purpose, but nobody's chasing a number.

Underscore-prefixed modules are internal (`_paths.py`, `_methods.py`, etc.) — they're allowed to break across patches. Anything without an underscore prefix is part of the stable surface after 1.0.

---

## The public surface

### `__init__.py` — 124 lines

The public API re-export wall. Everything an application author types `from causeway import ...` for lives here:

- HTTP method decorators (`get`, `post`, `put`, `patch`, `delete`) — re-exported from `_methods.py`.
- `Middleware`, `guard` — from `middleware.py`.
- `use`, `IdempotencyMiddleware`, `require_permission` — route-local middleware helpers.
- `provide` — from `scope.py`.
- `task`, `cron`, `tasks_eager` — from `tasks.py`.
- `Event` (base class), `Subscriber`, `verify`, `IncomingWebhook`, `WebhookDeliveryFailed` — from `events.py` / `webhooks.py`.
- `Settings`, `Manifest` — from `config.py`.
- `register`, `env` — from `plugins.py`.
- `RequestIdMiddleware`, `configure_logging`, `configure_otel` — from `observability.py`.
- `create_app` — from `app.py`.

When you add a new public symbol, **add it here too**. That's the contract.

### `app.py` — 254 lines

`create_app(routes_root, *, events_root="app/events", listeners_root="app/listeners", subscribers_root="app/subscribers", settings=None, ...)` — the factory. Walks the routes tree plus (when present) the three event-related trees: `events_root` imports each `.py` so every `Event` subclass registers itself via `__init_subclass__`; `listeners_root` imports each `.py` so `@<Event>.listen` decorators run at module scope; `subscribers_root` imports each `.py` so module-level `Subscriber(...)` instances register against their event classes. Then registers handlers, builds the App Graph, wires lifespan hooks, attaches health endpoints, and returns a Starlette app wrapping the inner `causeway.App`. The `create_app_frozen` sibling takes a pre-built `Discovered` for the binary build path.

### `config.py` — 107 lines

`Settings` is a re-export of `pydantic_settings.BaseSettings` (with an explicit annotation so type checkers see a complete type even when pydantic-settings ships without a `py.typed`). `Manifest` reads `causeway.toml` and exposes `[client] expose_settings = [...]` — the allowlist for fields surfaced to the generated TS client. `expose_for_client(settings, manifest)` does the filtering, also dropping any `SecretStr` / `SecretBytes` fields so secrets can't leak even if you list them.

---

## Routing

### `_paths.py` — 92 lines

URL-pattern translation. Pure functions, no I/O.

`url_for(rel_path)` takes a route file's relative path (`users/$id/posts.py`) and returns the URL pattern (`/users/{id}/posts`). `route_key_for(method, rel_path)` returns the public client key (`GET /users/$id/posts`). `scope_groups_for(rel_path)` returns route-group metadata such as `("org",)`. The helpers reject dotted route filenames so the file tree stays the only URL convention.

### `routing.py` — 377 lines

The walker, the loader, the binder. The biggest module in core, and the one most worth reading first.

Three phases:

1. **`discover(routes_root)`** — recursive walk, builds `Discovered` (routes + middleware + lifespan hooks). Skips underscore-prefixed files. Handles `_middleware.py` and `_scope.py` as per-subtree composition. Derives route keys, scopes, refresh contracts, permission metadata, and idempotency metadata. Detects method conflicts.
2. **`register(app, found)`** — binds the discovered handlers onto a `causeway.App` via `@get` / `@post` decorators on the right paths.
3. **`_bind_providers` / `_compose_guards`** — wraps each handler with its provider chain (`Annotated[T, get_session]`) and guard chain (lightweight middleware functions).

Three subtleties worth knowing if you're touching this file:

- Modules are loaded via the shared `causeway._loader.import_path` helper (see below) so `$` filenames don't confuse Python's import system, and so `routing.py` and `events.py` share one module cache.
- Provider matching is by `(source_location, name)` — `$id` files can be reloaded without losing provider identity.
- The handler wrapper preserves the runtime's view of the original signature (`__wrapped__`, `__annotations__`, `__globals__`) so string forward-refs resolve correctly when `causeway._runtime.runtime.build_plan` inspects the wrapper.

### `_loader.py` — 42 lines

Path-keyed module cache and the `importlib.util.spec_from_file_location` loader. Shared between `routing.py` and `events.py` so a file imported through one walker is the same module instance as the file imported through the other — provider-identity comparisons in `_bind_providers` rely on it.

### `_methods.py` — 134 lines

Tiny shim that exposes the bare HTTP method decorators (`@get`, `@post`, etc.) plus metadata kwargs such as `@post(refreshes=(...))`. The file location supplies the path.

### `graph.py` — 199 lines

Builds the App Graph from the runtime app: routes, route keys, HTTP paths, source files, scopes, params, responses, errors, streams, refreshes, middleware, providers, permission metadata, idempotency metadata, plugins, tasks, and events. The graph is metadata-only; it does not participate in request execution.

### `scope.py` — 41 lines

`provide(name)` — the request-scoped DI provider decorator. Tracks provider source location so the router can dedupe across re-imports.

### `middleware.py` — 53 lines

`Middleware` ABC and `@guard` decorator (lightweight function-style middleware). Re-exports `Request` and `Response` from Starlette so users can type their middleware against them.

---

## Plugins

### `contracts.py` — 363 lines

Every official contract as a `typing.Protocol`. `Plugin`, `TaskAdapter`, `EventBus`, `Storage`, `KV`, `Mailer`, `AuthProvider`, `DBSession`, `BlobScanner`, `FeatureFlags`, `MetricsSink`, `LogSink`, `PubSub`, `RateLimiter`, `SessionStore`, `DeployTarget`. Each contract declares `contract_version: ClassVar[str] = "v1.0"`.

If you're adding a new official contract, **start here**. Then add a reference
adapter in `adapters.py` or an optional adapter under `contrib/`, plus a test
that round-trips against the protocol.

### `plugins.py` — 235 lines

The registry. Two discovery paths feed one ordered dict:

- **Entry-point discovery** (`discover("causeway.plugins")`) — auto-loads any installed package that declares a `causeway.plugins` entry point.
- **Explicit `register(adapter)`** — for adapters that need constructor args.

Lifecycle: `startup_all(settings)` fires every plugin's `startup` in registration order; `shutdown_all()` fires `shutdown` in reverse. `check_required_contracts()` walks `requires` lists and refuses to boot if a dependency is missing. `merge_settings_fragments(settings)` applies each plugin's optional `settings_fragment()` to the `Settings` instance.

### `adapters.py` — 305 lines

Reference adapters shipped in core: `MemoryKV`, `LocalStorage`, `MemoryLimiter`, `StaticFlags`, `NullSink`, `MemoryBus`, `NullScanner`. These exist so the framework boots out of the box; production users swap them via a sibling `causeway-*` package.

---

## Background tasks

### `tasks.py` — 514 lines

`@task`, `@cron`, `TaskRef`, `tasks_eager()`, `cancel_requested()` / `raise_if_cancelled()`, and `InMemoryAdapter` (the reference). The module holds two `ContextVar`s: one for the active adapter (so eager-mode swaps don't leak across concurrent tests) and one for the per-run cancel probe that the task body polls. The adapter implements both the cooperative cancel (flip a flag, body returns or raises) and the hard-cancel fallback (`runner.cancel()` after the grace window).

### `_cron.py` — 65 lines

5-field crontab parser used by `InMemoryAdapter._cron_loop`. Pure function, fully tested. Production adapters (Dramatiq, Celery) delegate to a real scheduler instead.

---

## Events + Webhooks

### `events.py`

The `Event` base class inherits from `msgspec.Struct(kw_only=True)`. Its `__init_subclass__` runs on every subclass, deriving `wire_name` from the class name (PascalCase → dot-separated lowercase via `_BOUNDARY` regex), initializing per-class `_listeners` and `_subscribers` lists, and registering the class in the process-global `_events: dict[wire_name, type[Event]]`. Collision (two classes with the same wire name) raises at registration.

The `webhook` flag is a plain class attribute (`webhook = True` on the subclass) — not an annotated field, so msgspec doesn't pick it up as part of the payload schema. The default `False` lives on `Event` itself.

`@<Cls>.listen` is a classmethod decorator that validates async-ness + arity at decoration time and appends to `cls._listeners`. `Event.emit()` is an instance method: `asyncio.gather` over `_listeners`, then (if `cls.webhook`) call the late-bound `_fanout_impl` (filled in by `webhooks.py` at import — one-way dependency, no cycle).

Discovery: `discover(events_root, listeners_root=None)` walks both trees via `_loader.import_path`. Events directory enforces `<class_snake>.py` matching `<ClassName>` and rejects two `Event` subclasses in one file. Listeners directory just imports modules so their `@listen` decorators run; underscore-prefixed components and absolute-path-component noise are stripped via `relative_to(root).parts`.

### `webhooks.py`

Signing helpers (`sign_payload`, `verify_signature`, `new_secret`) are unchanged in format from 0.1 — Stripe-style HMAC-SHA256 over `f"{ts}.{body}"`.

`Subscriber` is a `@dataclass(slots=True)`. Its `__post_init__` validates that every key in `where` is an actual field on each subscribed event class, then registers `self` on each event class's `_subscribers` list (idempotent on object identity, so re-importing the file during hot reload doesn't double-register).

`_deliver` is a `@task(queue="webhooks", retries=5, backoff="exponential")` that signs body + POSTs via httpx + raises on non-2xx (so the task adapter's retry chain picks it up). Body is passed as JSON-encoded UTF-8 _string_, not bytes — `_encode_body` decodes once at enqueue and `_deliver` re-encodes — because the task adapter's payload encoder uses `json.dumps` which can't carry raw bytes. msgspec-produced JSON is always valid UTF-8, so round-tripping is byte-identical.

`_fanout(event)` (registered as `events._fanout_impl` at module import via `events._set_fanout(_fanout)`) walks `cls._subscribers` (static) + `_store.subscribers_for(wire_name)` async iterator (dynamic), applies `_matches(event, where)`, and enqueues one `_deliver` task per match. Exceptions during enqueue are logged and don't stop the rest of the fan-out.

`verify(req, secret=...) -> IncomingWebhook` reads `await req.body()` (or `req._body` for already-buffered bytes), runs `verify_signature`, parses JSON, and returns the typed `IncomingWebhook(name, body, json)`. Malformed JSON surfaces as `Unauthorized` (401) — clients can't distinguish signature failure from body-parse failure.

`InMemoryWebhooks` is a lifecycle-only adapter — no subscription state lives in it. `InMemoryWebhookStore` is the reference dynamic-subscription store (process-local, not durable); production deployments install a sibling plugin (`causeway-webhooks-pg`).

---

## Cross-cutting

### `observability.py` — 142 lines

`RequestIdMiddleware` stamps every request with a stable id and echoes it as `X-Request-Id`. `configure_logging(json=True/False)` sets up structlog. `configure_otel(...)` and `instrument_asgi(app)` lazy-import OpenTelemetry — both are no-ops when the `otel` extra isn't installed.

### `errors.py` — 135 lines

`HttpError` hierarchy (`NotFound`, `BadRequest`, `Unauthorized`, `Forbidden`, …) and the global handler for undeclared exceptions. Declared `@raises(...)` errors flow through typed wire envelopes that the route-key client unwraps into `CausewayError`; undeclared exceptions render as RFC 7807 `application/problem+json`. The handler **never** leaks internal exception messages — the body for an uncaught exception is the generic `internal server error`. Subclass `HttpError` to opt into a custom message.

### `health.py` — 54 lines

`/healthz` (process up) and `/readyz` (every plugin's `ready()` returns true). `attach(app)` wires them; the dev loop and `create_app` both call it.

### `diagnostics.py` — 105 lines

The `/__causeway` endpoint and dev-only `/__causeway/graph` endpoint. Builds JSON snapshots for the dev panel: route tree, registered tasks, cron jobs, plugins, non-secret config, and the App Graph.

### `testing.py`

`TestApp.from_routes(routes_root)` / `TestApp.wrap(app)`, an httpx-based async client, `.override(provider, replacement)` for swapping DI providers in tests, `stub(provider, value)` for the common "just return this value" case, and a re-export of `tasks_eager()` for symmetry. Also re-exports the inline-scenario API (`scenario`, `expect`, `snapshot`, `Response`, `Expectation`, `ScenarioAssertionError`, `SnapshotValue`).

### `_testing/`

The inline-scenario runtime. Lives in a private subpackage so the implementation can evolve without touching the public `testing.py` surface.

- `scenario.py` — `scenario(...)` context manager and the synchronous `_It` client that drives httpx-over-ASGI through a per-scenario event loop.
- `expect.py` — `expect(...)` proxy with operator-overloaded assertions and path-aware diff messages.
- `response.py` — `Response` + `PathValue`, the attribute/item walker for JSON bodies.
- `snapshot.py` — `snapshot(...)` marker, ellipsis-aware structural match, pending-edit registry.
- `rewrite.py` — tokenize-based source rewriter used when `--update-snapshots` is set.
- `loader.py` — imports a route file with `__name__ == "__causeway_test__"` by compiling + execing source directly (bypasses importlib's name-match check).
- `registry.py` — contextvar plumbing the plugin uses to publish a `Registry` into the imported module.
- `discover.py` — finds routes roots by walking up for `causeway.toml` siblings, with a shallow `app/routes` fallback.
- `errors.py` — `ScenarioAssertionError(AssertionError)` with rendered unified diffs.

### `_pytest_plugin.py`

Registered via the `pytest11` entry point. Adds `--causeway-routes`, `--update-snapshots`, `--causeway-no-inline`; matches route files via `pytest_collect_file`; yields one `ScenarioItem` per `scenario(...)` block; applies snapshot rewrites in `pytest_sessionfinish`.

### `cli.py` — 543 lines

The `causeway` CLI built on Typer. Commands: `new` (scaffold via `_scaffold.py`), `dev` (owned uvicorn server + smart route hot-swap), `build` (codegen + wheel), `codegen`, `ir`, `inspect` (App Graph), `freeze`, auxiliary generators (`openapi`, `swift`, `kotlin`), `plugins` (list registered adapters), `diff` (IR breaking-change detection), `deploy <target>` (dispatch to a registered `DeployTarget`), and `plugin new <name>` (scaffold a new plugin package).

### `_scaffold.py` — 290 lines

Templates for `causeway new` and `causeway plugin new`. The longest non-routing module, almost entirely string literals.

---

## Tests

Every public module has a test file with the same name: `tests/test_routing_register.py`, `tests/test_paths.py`, `tests/test_plugins.py`, `tests/test_tasks.py`, etc. The pattern is:

- One test file per source module.
- pytest, `asyncio_mode = "auto"` (so `async def test_…` works without a marker).
- `filterwarnings = ["error"]` (warnings fail tests; we want to know).

When you fix a bug, add a regression test next to its module's test file. When you add a public API, add at least one test for it.
