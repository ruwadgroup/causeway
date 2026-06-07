from __future__ import annotations

import subprocess
import types
from pathlib import Path
from typing import Any

import pytest

import causeway.plugins as plugin_registry
from causeway.contrib.fly import FlyDeploy, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


async def test_lifecycle_is_a_no_op() -> None:
    target = FlyDeploy(app_name="x")
    await target.startup(None)
    await target.shutdown()
    assert await target.ready() is True


def test_manifest_carries_app_name() -> None:
    manifest = FlyDeploy(app_name="my-app").manifest()
    assert manifest["target"] == "fly"
    assert manifest["app"] == "my-app"
    assert "fly.toml" in manifest["files"]
    assert "Dockerfile" in manifest["files"]


def test_package_emits_fly_toml_with_app_name(tmp_path: Path) -> None:
    target = FlyDeploy(app_name="hello-fly")
    body = target.package(target_dir=tmp_path)

    fly_toml = (tmp_path / "fly.toml").read_text()
    assert 'app = "hello-fly"' in fly_toml
    assert body == fly_toml.encode()
    # Either the docker package wrote the multi-stage Dockerfile, or the
    # inline fallback wrote a simpler one — both should exist.
    assert (tmp_path / "Dockerfile").is_file()


def test_package_falls_back_when_docker_plugin_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "causeway.contrib.docker":
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    FlyDeploy(app_name="solo").package(target_dir=tmp_path)
    dockerfile = (tmp_path / "Dockerfile").read_text()
    assert "FROM python:3.13-slim" in dockerfile
    assert "uvicorn" in dockerfile


async def test_push_errors_when_flyctl_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("causeway.contrib.fly.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="flyctl not on PATH"):
        await FlyDeploy().push("target")


async def test_push_invokes_flyctl_and_returns_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("causeway.contrib.fly.shutil.which", lambda _: "/usr/bin/flyctl")

    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="deployed\n", stderr="")

    monkeypatch.setattr("causeway.contrib.fly.subprocess.run", fake_run)
    out = await FlyDeploy(app_name="x").push("ignored")
    assert out == "deployed\n"
    assert captured["cmd"] == ["flyctl", "deploy", "--app", "x"]


async def test_push_raises_on_flyctl_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("causeway.contrib.fly.shutil.which", lambda _: "/bin/flyctl")
    monkeypatch.setattr(
        "causeway.contrib.fly.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )
    with pytest.raises(RuntimeError, match="flyctl deploy failed: boom"):
        await FlyDeploy().push("target")


def test_plugin_reads_settings_fly_app() -> None:
    plugin(types.SimpleNamespace(fly_app="settings-app"))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, FlyDeploy)
    assert adapter.app_name == "settings-app"


def test_plugin_defaults_when_no_settings() -> None:
    plugin(types.SimpleNamespace())
    [adapter] = plugin_registry.registered()
    assert adapter.app_name == "causeway-app"
