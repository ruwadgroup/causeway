from __future__ import annotations

import asyncio
import importlib
import os
import runpy
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any

import dramatiq
import pytest
from dramatiq.brokers.stub import StubBroker
from pydantic import SecretStr
import typer
from typer.testing import CliRunner

import causeway.plugins as plugin_registry
from causeway.tasks import TaskRef, _clear as clear_tasks, cron, task
import causeway_tasks_dramatiq.cli as cli_module
import causeway_tasks_dramatiq.runtime as runtime_module
from causeway_tasks_dramatiq import DramatiqAdapter, plugin
from causeway_tasks_dramatiq.cli import cli


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()
    clear_tasks()


@pytest.fixture
def stub_broker(monkeypatch: pytest.MonkeyPatch) -> StubBroker:
    """Swap RedisBroker for StubBroker so startup() doesn't dial Redis."""
    captured: dict[str, StubBroker] = {}

    class _StubFactory(StubBroker):
        def __init__(self, *, url: str | None = None) -> None:
            super().__init__()
            self.url = url
            captured["broker"] = self

    monkeypatch.setattr("causeway_tasks_dramatiq.RedisBroker", _StubFactory)
    return captured  # type: ignore[return-value]


def _make_ref(name: str, called: list[tuple[Any, ...]]) -> TaskRef:
    async def fn(*args: Any, **kwargs: Any) -> None:
        called.append((args, kwargs))

    fn.__module__ = "tests"
    fn.__name__ = name
    return TaskRef(module="tests", name=name, fn=fn)


async def test_lifecycle_starts_broker(stub_broker: dict[str, StubBroker]) -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    assert await adapter.ready() is False
    await adapter.startup(None)
    try:
        assert await adapter.ready() is True
        # set_adapter wired us up as the active task adapter.
        from causeway.tasks import _active_adapter  # type: ignore[attr-defined]

        assert _active_adapter() is adapter
    finally:
        await adapter.shutdown()
    assert await adapter.ready() is False


async def test_enqueue_pushes_to_broker(stub_broker: dict[str, StubBroker]) -> None:
    called: list[tuple[Any, ...]] = []
    ref = _make_ref("greet", called)

    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        msg_id = await adapter.enqueue(ref, b'{"args": [], "kwargs": {}}')
        assert isinstance(msg_id, str) and msg_id
        # Same TaskRef reuses the same actor (cache hit path).
        await adapter.enqueue(ref, b'{"args": [], "kwargs": {}}')
        assert len(adapter._actors) == 1
    finally:
        await adapter.shutdown()


async def test_actor_names_are_stable_and_distinct(
    stub_broker: dict[str, StubBroker],
) -> None:
    called: list[tuple[Any, ...]] = []
    first = _make_ref("first", called)
    second = _make_ref("second", called)

    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        await adapter.enqueue(first, b'{"args": [], "kwargs": {}}')
        await adapter.enqueue(second, b'{"args": [], "kwargs": {}}')
        assert set(adapter._actors) == {"tests.first", "tests.second"}
        assert adapter._actors["tests.first"].actor_name == "tests.first"
        assert adapter._actors["tests.second"].actor_name == "tests.second"
    finally:
        await adapter.shutdown()


async def test_enqueue_without_callable_raises(
    stub_broker: dict[str, StubBroker],
) -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        bare = TaskRef(module="m", name="n", fn=None)
        with pytest.raises(RuntimeError, match="no callable bound"):
            await adapter.enqueue(bare, b"{}")
    finally:
        await adapter.shutdown()


async def test_schedule_computes_delay(stub_broker: dict[str, StubBroker]) -> None:
    called: list[tuple[Any, ...]] = []
    ref = _make_ref("later", called)
    when = datetime.now(timezone.utc) + timedelta(seconds=5)

    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        msg_id = await adapter.schedule(ref, when, b'{"args": [], "kwargs": {}}')
        assert msg_id
    finally:
        await adapter.shutdown()


async def test_schedule_clamps_negative_delay(
    stub_broker: dict[str, StubBroker],
) -> None:
    called: list[tuple[Any, ...]] = []
    ref = _make_ref("past", called)
    when = datetime.now(timezone.utc) - timedelta(minutes=1)

    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        msg_id = await adapter.schedule(ref, when, b'{"args": [], "kwargs": {}}')
        assert msg_id
    finally:
        await adapter.shutdown()


async def test_cron_registers_actor_only(stub_broker: dict[str, StubBroker]) -> None:
    called: list[tuple[Any, ...]] = []
    ref = _make_ref("every", called)

    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        await adapter.cron(ref, "*/5 * * * *")
        actor = adapter._actors["tests.every"]
        assert str(actor.options["periodic"]) == "*/5 * * * *"
    finally:
        await adapter.shutdown()


def test_actor_executes_decoded_payload(
    stub_broker: dict[str, StubBroker],
) -> None:
    called: list[tuple[Any, ...]] = []
    ref = _make_ref("execute", called)

    adapter = DramatiqAdapter(broker_url="redis://x")
    asyncio.run(adapter.startup(None))
    try:
        actor = adapter._actor_for(ref)
        actor.fn('{"args": [1], "kwargs": {"name": "Ada"}}')
    finally:
        asyncio.run(adapter.shutdown())

    assert called == [((1,), {"name": "Ada"})]


async def test_existing_broker_actor_is_reused(
    stub_broker: dict[str, StubBroker],
) -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:

        @dramatiq.actor(actor_name="tests.existing")
        def existing() -> None:
            pass

        ref = TaskRef(module="tests", name="existing", fn=lambda: None)
        actor = adapter._actor_for(ref)

        assert actor is existing
        assert adapter._actor_for(ref) is existing
    finally:
        await adapter.shutdown()


async def test_startup_registers_discovered_tasks(
    stub_broker: dict[str, StubBroker],
) -> None:
    @task()
    async def queued() -> None:
        pass

    @cron("0 * * * *")
    async def hourly() -> None:
        pass

    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        assert f"{queued.module}.{queued.name}" in adapter._actors
        cron_actor = adapter._actors[f"{hourly.module}.{hourly.name}"]
        assert str(cron_actor.options["periodic"]) == "0 * * * *"
    finally:
        await adapter.shutdown()


async def test_eager_context_swaps_broker(stub_broker: dict[str, StubBroker]) -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    await adapter.startup(None)
    try:
        outer = adapter._broker
        async with adapter.eager():
            inner = adapter._broker
            assert inner is not outer
            assert isinstance(inner, StubBroker)
        assert adapter._broker is outer
    finally:
        await adapter.shutdown()


async def test_eager_context_handles_adapter_without_broker() -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")

    async with adapter.eager():
        assert isinstance(adapter._broker, StubBroker)

    assert adapter._broker is None


async def test_shutdown_without_broker_is_ok() -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")

    await adapter.shutdown()

    assert adapter._actors == {}


async def test_status_returns_pending(stub_broker: dict[str, StubBroker]) -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    state = await adapter.status("any-id")
    assert state.state == "pending"


async def test_result_raises_not_implemented(
    stub_broker: dict[str, StubBroker],
) -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    with pytest.raises(NotImplementedError, match="Results middleware"):
        await adapter.result("any-id")


async def test_cancel_raises_not_implemented() -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")

    with pytest.raises(NotImplementedError, match="does not implement cancel"):
        await adapter.cancel("any-id")


def test_plugin_defaults_to_localhost(stub_broker: dict[str, StubBroker]) -> None:
    plugin(types.SimpleNamespace())
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, DramatiqAdapter)
    assert adapter.broker_url == "redis://localhost"


async def test_plugin_default_reads_settings_on_startup(
    stub_broker: dict[str, StubBroker],
) -> None:
    plugin(types.SimpleNamespace())
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, DramatiqAdapter)
    await adapter.startup(
        types.SimpleNamespace(redis_url=SecretStr("redis://settings"))
    )
    try:
        assert adapter.broker_url == "redis://settings"
    finally:
        await adapter.shutdown()


def test_plugin_reads_redis_url(stub_broker: dict[str, StubBroker]) -> None:
    plugin(types.SimpleNamespace(redis_url="redis://h:1234/0"))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, DramatiqAdapter)
    assert adapter.broker_url == "redis://h:1234/0"


def test_plugin_unwraps_secret_url(stub_broker: dict[str, StubBroker]) -> None:
    plugin(types.SimpleNamespace(redis_url=SecretStr("redis://h")))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, DramatiqAdapter)
    assert adapter.broker_url == "redis://h"


def test_bootstrap_imports_app_tasks_and_returns_broker(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    stub_broker: dict[str, StubBroker],
) -> None:
    pkg = tmp_path / "demoapp"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("app = object()\n", encoding="utf-8")
    (pkg / "tasks.py").write_text(
        "\n".join(
            [
                "from causeway import cron, task",
                "",
                "@task()",
                "async def send_email():",
                "    pass",
                "",
                "@cron('*/10 * * * *')",
                "async def sweep():",
                "    pass",
                "",
            ],
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    from causeway_tasks_dramatiq.runtime import bootstrap

    try:
        broker = bootstrap(app_target="demoapp:app", task_modules=("demoapp.tasks",))
        assert broker is stub_broker["broker"]
        [adapter] = [
            candidate
            for candidate in plugin_registry.registered()
            if isinstance(candidate, DramatiqAdapter)
        ]
        assert "demoapp.tasks.send_email" in adapter._actors
        periodic = adapter._actors["demoapp.tasks.sweep"].options["periodic"]
        assert str(periodic) == "*/10 * * * *"
    finally:
        asyncio.run(plugin_registry.shutdown_all())


def test_env_list_returns_default_and_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAUSEWAY_TEST_MODULES", raising=False)

    assert runtime_module._env_list("CAUSEWAY_TEST_MODULES", ("app.tasks",)) == (
        "app.tasks",
    )

    monkeypatch.setenv("CAUSEWAY_TEST_MODULES", " app.tasks, extra.tasks ,,")

    assert runtime_module._env_list("CAUSEWAY_TEST_MODULES", ()) == (
        "app.tasks",
        "extra.tasks",
    )


def test_split_target_validates_shape() -> None:
    assert runtime_module._split_target("demoapp:app") == ("demoapp", "app")

    with pytest.raises(ValueError, match="module:attr"):
        runtime_module._split_target("demoapp")


def test_import_optional_default_swallow_only_default_missing(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("app", None)
    sys.modules.pop("app.tasks", None)

    runtime_module._import_optional_default("app.tasks")

    with pytest.raises(ModuleNotFoundError):
        runtime_module._import_optional_default("missing_required_tasks")


def test_ensure_adapter_reuses_existing_adapter() -> None:
    adapter = DramatiqAdapter(broker_url="redis://x")
    plugin_registry.register(adapter)

    runtime_module._ensure_adapter()

    adapters = [
        candidate
        for candidate in plugin_registry.registered()
        if isinstance(candidate, DramatiqAdapter)
    ]
    assert adapters == [adapter]


def test_dramatiq_adapter_requires_registration() -> None:
    with pytest.raises(RuntimeError, match="No DramatiqAdapter"):
        runtime_module._dramatiq_adapter()


def test_bootstrap_errors_if_startup_does_not_create_broker(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = tmp_path / "nobroker"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("app = object()\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        runtime_module,
        "load_settings",
        lambda module: types.SimpleNamespace(module=module),
    )

    async def fake_startup_all(settings: Any) -> None:
        del settings

    monkeypatch.setattr(runtime_module, "startup_all", fake_startup_all)

    with pytest.raises(RuntimeError, match="did not start a broker"):
        runtime_module.bootstrap(app_target="nobroker:app", task_modules=())


def test_worker_module_exposes_bootstrapped_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(runtime_module, "bootstrap", lambda: sentinel)
    sys.modules.pop("causeway_tasks_dramatiq.worker", None)

    module = importlib.import_module("causeway_tasks_dramatiq.worker")

    try:
        assert module.broker is sentinel
    finally:
        sys.modules.pop("causeway_tasks_dramatiq.worker", None)


def test_worker_cli_sets_bootstrap_env_and_dramatiq_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_APP", raising=False)
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_TASKS", raising=False)
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_IMPORTS", raising=False)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str]) -> None:
        captured["args"] = args

    monkeypatch.setattr("causeway_tasks_dramatiq.cli._run_dramatiq", fake_run)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "worker",
            "--app",
            "demoapp:app",
            "--tasks",
            "demoapp.tasks,other.tasks",
            "--import",
            "demoapp.listeners",
            "--processes",
            "2",
            "--threads",
            "4",
            "--queue",
            "emails",
        ],
    )

    assert result.exit_code == 0
    assert captured["args"] == [
        "--processes",
        "2",
        "--threads",
        "4",
        "--queues",
        "emails",
        "causeway_tasks_dramatiq.worker:broker",
    ]
    assert os.environ["CAUSEWAY_DRAMATIQ_APP"] == "demoapp:app"
    assert os.environ["CAUSEWAY_DRAMATIQ_TASKS"] == "demoapp.tasks,other.tasks"
    assert os.environ["CAUSEWAY_DRAMATIQ_IMPORTS"] == "demoapp.listeners"


def test_worker_cli_default_args_watch_verbose_and_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_APP", raising=False)
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_TASKS", raising=False)
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_IMPORTS", raising=False)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str]) -> None:
        captured["args"] = args

    monkeypatch.setattr(cli_module, "_run_dramatiq", fake_run)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "worker",
            "--watch",
            "src",
            "--verbose",
            "--log-file",
            "worker.log",
        ],
    )

    assert result.exit_code == 0
    assert captured["args"] == [
        "--watch",
        "src",
        "--verbose",
        "--log-file",
        "worker.log",
        "causeway_tasks_dramatiq.worker:broker",
    ]
    assert os.environ["CAUSEWAY_DRAMATIQ_APP"] == "app:app"
    assert os.environ["CAUSEWAY_DRAMATIQ_TASKS"] == "app.tasks"
    assert os.environ["CAUSEWAY_DRAMATIQ_IMPORTS"] == ""


def test_scheduler_cli_sets_env_and_periodiq_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_APP", raising=False)
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_TASKS", raising=False)
    monkeypatch.delenv("CAUSEWAY_DRAMATIQ_IMPORTS", raising=False)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str]) -> None:
        captured["args"] = args

    monkeypatch.setattr(cli_module, "_run_periodiq", fake_run)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "scheduler",
            "--app",
            "demoapp:app",
            "--tasks",
            "demoapp.tasks",
            "--import",
            "demoapp.listeners",
            "--verbose",
            "--skip-delay",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert captured["args"] == [
        "--verbose",
        "--skip-delay",
        "0",
        "causeway_tasks_dramatiq.worker:broker",
    ]
    assert os.environ["CAUSEWAY_DRAMATIQ_APP"] == "demoapp:app"
    assert os.environ["CAUSEWAY_DRAMATIQ_TASKS"] == "demoapp.tasks"
    assert os.environ["CAUSEWAY_DRAMATIQ_IMPORTS"] == "demoapp.listeners"


def test_run_dramatiq_uses_parser_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = types.SimpleNamespace(parsed=True)
    captured: dict[str, Any] = {}

    class Parser:
        def parse_args(self, args: list[str]) -> types.SimpleNamespace:
            captured["args"] = args
            return parsed

    def fake_main(value: types.SimpleNamespace) -> int:
        captured["parsed"] = value
        return 0

    monkeypatch.setattr("dramatiq.cli.make_argument_parser", lambda: Parser())
    monkeypatch.setattr("dramatiq.cli.main", fake_main)

    with pytest.raises(typer.Exit) as exc_info:
        cli_module._run_dramatiq(["--processes", "1", "module:broker"])

    assert exc_info.value.exit_code == 0
    assert captured == {
        "args": ["--processes", "1", "module:broker"],
        "parsed": parsed,
    }


def test_run_periodiq_uses_parser_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = types.SimpleNamespace(parsed=True)
    captured: dict[str, Any] = {}

    class Parser:
        def parse_args(self, args: list[str]) -> types.SimpleNamespace:
            captured["args"] = args
            return parsed

    def fake_main(value: types.SimpleNamespace) -> int:
        captured["parsed"] = value
        return 3

    monkeypatch.setattr("periodiq.make_argument_parser", lambda: Parser())
    monkeypatch.setattr("periodiq.main", fake_main)

    with pytest.raises(typer.Exit) as exc_info:
        cli_module._run_periodiq(["--skip-delay", "0", "module:broker"])

    assert exc_info.value.exit_code == 3
    assert captured == {
        "args": ["--skip-delay", "0", "module:broker"],
        "parsed": parsed,
    }


def test_cli_main_invokes_typer_app(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_cli() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli_module, "cli", fake_cli)

    cli_module.main()

    assert called is True


def test_main_module_invokes_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_main() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli_module, "main", fake_main)
    sys.modules.pop("causeway_tasks_dramatiq.__main__", None)

    runpy.run_module("causeway_tasks_dramatiq.__main__", run_name="__main__")

    assert called is True
