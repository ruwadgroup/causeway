# Testing strategy

What we test, what we don't, and where the bar is.

## The shape

```
packages/causeway/tests/
├── __init__.py
├── test_adapters.py             # MemoryKV / LocalStorage / NullSink / etc.
├── test_app_factory.py          # create_app() composition
├── test_cli.py                  # the Typer CLI
├── test_config.py               # Settings + Manifest
├── test_errors.py               # HttpError hierarchy + handler
├── test_health.py               # /healthz, /readyz
├── test_observability.py        # RequestIdMiddleware, structlog setup
├── test_paths.py                # url_for — folder routes + rejected old forms
├── test_plugin_features.py      # settings_fragment, requires, env()
├── test_plugins.py              # register / startup_all / shutdown_all
├── test_provider_binding.py     # @provide + Annotated[T, fn]
├── test_routing_discover.py     # walk + import
├── test_routing_register.py     # binding to causeway.App
├── test_tasks.py                # @task, InMemoryAdapter, cron loop
├── test_testing_kit.py          # TestApp behaviors
├── test_inline_scenarios.py     # scenario/expect runtime
├── test_inline_snapshots.py     # snapshot rewrite + ellipsis match
├── test_pytest_plugin.py        # plugin collection + execution (pytester)
└── test_version.py              # __version__ smoke
```

Each public module has a matching test file. New module → new test file.

## What we test

**Pure logic, every branch.** `_paths.py` is a pure function, so its test is parametrized over every interesting input. Same for `_cron.py`.

**Public contracts.** Every public symbol (`@task`, `@get`, `Settings`, `register`, `TestApp`, …) has at least one test asserting the documented behavior. If the docs say "two `@get` in the same file is a boot error", there's a test that boots a tree with two `@get` and asserts the error.

**Lifecycle.** Plugin startup / shutdown ordering, error handling per-plugin, ready-check aggregation — covered explicitly because the registry is load-bearing.

**Adapter parity.** The reference `InMemoryAdapter` is the contract probe.
Bundled adapters (`DramatiqAdapter`, etc.) have tests under `tests/contrib`,
but they implement the same `TaskAdapter` protocol the core tests verify.

**Integration via `TestApp`.** End-to-end tests — discover a synthesized routes tree under `tmp_path`, mount it with `TestApp.from_routes`, fire HTTP requests through httpx's `ASGITransport`, assert on the responses. These catch composition bugs that unit tests miss.

## What we don't test

**Framework dependencies.** We trust `pydantic-settings` to parse env vars, `structlog` to format logs, `msgspec` to encode JSON. If a third-party dependency has a bug, the fix is upstream. The TypeScript codegen lives in `causeway._runtime` and is covered by `tests/runtime/test_codegen.py`.

**Type-level behavior.** Pyright handles that. We run pyright in CI; type errors fail the build.

**Coverage numbers.** We don't enforce a percentage. The interesting question isn't "what's covered" — it's "what's the regression test for the last bug we fixed?" Every bug fix adds one.

## How tests are written

```python
# tests/test_paths.py
"""URL translation rules from docs/backend/routing.md."""

@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("index.py", "/"),
        ("users/$id.py", "/users/{id}"),
        # …
    ],
)
def test_url_for_folder_style(rel: str, expected: str) -> None:
    assert url_for(PurePosixPath(rel)) == expected
```

Parametrize over inputs when the test is the same shape for every case. One assertion per test, ideally. Test function names spell out what they're proving.

For async behavior:

```python
# pytest.ini_options sets asyncio_mode = "auto"
async def test_task_runs_eagerly() -> None:
    set_adapter(InMemoryAdapter())
    async with tasks_eager():
        task_id = await my_task.enqueue("hello")
    assert (await _active_adapter().result(task_id)) == "hello"
```

No `@pytest.mark.asyncio` decorator needed — auto mode handles it.

## CI

GitHub Actions runs the full suite on every push:

```yaml
- uv sync
- uv run ruff check packages/causeway/src packages/causeway/tests
- uv run mypy packages/causeway/src
- uv run pyright # root pyrightconfig.json
- uv run pytest -q
```

The bar is: every one of these passes on `main`. If you push something that fails, the next pusher fixes it — leaving the tree red blocks everyone.

## When a test is hard to write

Two common causes:

1. **The unit is doing too many things.** Split it.
2. **The unit depends on a real system.** Put a protocol between the unit and the system; test against the protocol with an in-memory fake.

If neither helps, it's probably an integration concern — use `TestApp` and an end-to-end test, and write it clearly enough that the next person knows why it's there.

## Filterwarnings

```toml
filterwarnings = ["error"]
```

Warnings are errors in tests. That's how we keep the surface honest: a `DeprecationWarning` someone forgot to clean up will fail CI before it lands. If a warning is intentional (e.g. the plugin-without-`contract_version` test), assert on it with `pytest.warns(UserWarning, match=...)`.
