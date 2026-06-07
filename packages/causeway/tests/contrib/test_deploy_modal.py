from __future__ import annotations

import subprocess
import types
from pathlib import Path
from typing import Any

import pytest

import causeway.plugins as plugin_registry
from causeway.contrib.modal import ModalDeploy, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


async def test_lifecycle_is_a_no_op() -> None:
    target = ModalDeploy(app_name="x")
    await target.startup(None)
    await target.shutdown()
    assert await target.ready() is True


def test_manifest_carries_app_name() -> None:
    manifest = ModalDeploy(app_name="my-app").manifest()
    assert manifest == {
        "target": "modal",
        "app": "my-app",
        "files": ["modal_app.py"],
    }


def test_package_emits_modal_app(tmp_path: Path) -> None:
    target = ModalDeploy(app_name="ship-it")
    body = target.package(target_dir=tmp_path)
    written = (tmp_path / "modal_app.py").read_text()
    assert 'modal.App("ship-it"' in written
    assert "from app.app import app as causeway_app" in written
    assert body == written.encode()


async def test_push_errors_when_modal_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("causeway.contrib.modal.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="modal not on PATH"):
        await ModalDeploy().push("target")


async def test_push_invokes_modal_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("causeway.contrib.modal.shutil.which", lambda _: "/bin/modal")
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("causeway.contrib.modal.subprocess.run", fake_run)
    out = await ModalDeploy().push("ignored")
    assert out == "ok\n"
    assert captured["cmd"] == ["modal", "deploy", "modal_app.py"]


async def test_push_raises_on_modal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("causeway.contrib.modal.shutil.which", lambda _: "/bin/modal")
    monkeypatch.setattr(
        "causeway.contrib.modal.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, stdout="", stderr="nope"),
    )
    with pytest.raises(RuntimeError, match="modal deploy failed: nope"):
        await ModalDeploy().push("target")


def test_plugin_reads_settings_modal_app() -> None:
    plugin(types.SimpleNamespace(modal_app="from-settings"))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, ModalDeploy)
    assert adapter.app_name == "from-settings"


def test_plugin_defaults_when_no_settings() -> None:
    plugin(types.SimpleNamespace())
    [adapter] = plugin_registry.registered()
    assert adapter.app_name == "causeway-app"
