"""Binary build driver. Phase-2 (Nuitka end-to-end gated by RUN_NUITKA_TESTS=1)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from causeway._binary import (
    _DEV_SURFACE_EXCLUDES,
    _binary_name,
    _collect_plugin_packages,
    _infer_user_app_package,
    _nuitka_command,
    build_binary,
)


def _make_project(root: Path) -> Path:
    (root / "src" / "app").mkdir(parents=True)
    (root / "src" / "app" / "__init__.py").write_text("")
    (root / "src" / "app" / "routes").mkdir()
    (root / "src" / "app" / "routes" / "index.py").write_text(
        "from causeway import get\n@get\nasync def root() -> dict: return {'status': 'ok'}\n",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "tinyapp"\nversion = "0.4.2"\n',
    )
    return root / "src" / "app" / "routes"


def test_dry_run_freezes_without_invoking_nuitka(tmp_path: Path) -> None:
    routes_root = _make_project(tmp_path)
    artifact = build_binary(
        project_root=tmp_path,
        out=tmp_path / "dist",
        routes_root=routes_root,
        user_plugins_module=None,
        settings_target=None,
        dry_run=True,
    )
    assert artifact.size_bytes == 0
    assert (tmp_path / ".causeway" / "build" / "_causeway_build" / "_frozen_routes.py").is_file()


def test_nuitka_command_includes_required_packages_and_excludes_dev_surface() -> None:
    cmd = _nuitka_command(
        entry=Path("/tmp/entry.py"),
        out_dir=Path("/tmp/out"),
        binary_name="tinyapp-0.4.2-linux-x86_64",
        plugin_packages=("causeway.contrib.s3", "causeway.contrib.sqlmodel"),
        extra_packages=(),
        user_app_package="app",
    )
    joined = " ".join(cmd)

    for required in ("causeway", "starlette", "uvicorn", "msgspec", "app"):
        assert f"--include-package={required}" in joined
    for plugin in ("causeway.contrib.s3", "causeway.contrib.sqlmodel"):
        assert f"--include-package={plugin}" in joined
    for dev_mod in _DEV_SURFACE_EXCLUDES:
        assert f"--nofollow-import-to={dev_mod}" in joined

    assert "--standalone" in cmd
    assert "--onefile" in cmd
    assert cmd[-1] == "/tmp/entry.py"


def test_collect_plugin_packages_parses_frozen_plugins(tmp_path: Path) -> None:
    freeze_out = tmp_path / "build"
    pkg = freeze_out / "_causeway_build"
    pkg.mkdir(parents=True)
    (pkg / "_frozen_plugins.py").write_text(
        "from __future__ import annotations\n"
        "from causeway.contrib.s3 import plugin as _EP_a\n"
        "from causeway.contrib.sqlmodel import plugin as _EP_b\n"
        "from some.nested.path import f as _EP_c\n",
    )
    assert _collect_plugin_packages(manifest=None, freeze_out=freeze_out) == (
        "causeway.contrib.s3",
        "causeway.contrib.sqlmodel",
        "some",
    )


def test_infer_user_app_package_finds_src_layout(tmp_path: Path) -> None:
    (tmp_path / "src" / "myapp").mkdir(parents=True)
    (tmp_path / "src" / "myapp" / "__init__.py").write_text("")
    assert _infer_user_app_package(tmp_path) == "myapp"


def test_infer_user_app_package_finds_flat_layout(tmp_path: Path) -> None:
    (tmp_path / "service").mkdir()
    (tmp_path / "service" / "__init__.py").write_text("")
    assert _infer_user_app_package(tmp_path) == "service"


def test_infer_user_app_package_skips_dot_and_underscore_dirs(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / "_private").mkdir()
    (tmp_path / "_private" / "__init__.py").write_text("")
    assert _infer_user_app_package(tmp_path) is None


def test_binary_name_includes_version_and_platform(tmp_path: Path) -> None:
    # tmp_path is named after the test function, so use a controlled subdir.
    project = tmp_path / "myapp"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "myapp"\nversion = "1.2.3"\n',
    )
    name = _binary_name(project)
    assert name.startswith("myapp-1.2.3-")
    assert any(name.endswith(suffix) for suffix in ("x86_64", "arm64", ".exe"))


def test_build_binary_raises_when_nuitka_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes_root = _make_project(tmp_path)
    from causeway import _binary

    monkeypatch.setattr(_binary, "_has_nuitka", lambda: False)
    with pytest.raises(RuntimeError, match="nuitka is not installed"):
        build_binary(
            project_root=tmp_path,
            out=tmp_path / "dist",
            routes_root=routes_root,
            user_plugins_module=None,
            settings_target=None,
        )


@pytest.mark.skipif(
    os.environ.get("RUN_NUITKA_TESTS") != "1",
    reason="set RUN_NUITKA_TESTS=1 to run the slow end-to-end Nuitka build",
)
def test_nuitka_end_to_end_serves_healthz(tmp_path: Path) -> None:
    routes_root = _make_project(tmp_path)
    artifact = build_binary(
        project_root=tmp_path,
        out=tmp_path / "dist",
        routes_root=routes_root,
        user_plugins_module=None,
        settings_target=None,
    )
    assert artifact.path.is_file()
    assert artifact.size_bytes > 0

    proc = subprocess.Popen(
        [str(artifact.path)],
        env={**os.environ, "PORT": "18742", "HOST": "127.0.0.1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        start = time.time()
        last_err: Exception | None = None
        while time.time() - start < 30:
            try:
                r = httpx.get("http://127.0.0.1:18742/healthz", timeout=1.0)
                if r.status_code == 200:
                    break
            except httpx.HTTPError as exc:
                last_err = exc
            time.sleep(0.2)
        else:
            raise AssertionError(f"binary never came up: {last_err}")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
