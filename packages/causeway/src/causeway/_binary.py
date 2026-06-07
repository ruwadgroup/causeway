"""Nuitka driver. Compiles the frozen tree into a single executable."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from causeway._freeze import MIRROR_PACKAGE, FreezeManifest, freeze


@dataclass(slots=True, frozen=True)
class BinaryArtifact:
    path: Path
    size_bytes: int
    sbom_path: Path | None = None
    signature_path: Path | None = None

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


# These would inflate the binary by ~20 MB and re-introduce the runtime
# discovery surface the freeze step deliberately removed.
_DEV_SURFACE_EXCLUDES = (
    "causeway.cli",
    "causeway._scaffold",
    "causeway._freeze",
    "causeway._binary",
    "watchfiles",
    "rich",
    "typer",
)


def build_binary(
    project_root: Path,
    out: Path,
    *,
    routes_root: Path | None = None,
    user_plugins_module: str | None = "app.plugins",
    settings_target: str | None = "app.config:Settings",
    sign: bool = False,
    sbom: bool = False,
    extra_packages: tuple[str, ...] = (),
    dry_run: bool = False,
) -> BinaryArtifact:
    """Freeze the project and compile a standalone binary via Nuitka.

    ``dry_run=True`` exits after freezing — useful for tests and inspection
    without paying the 5-minute compile cost.
    """
    project_root = project_root.resolve()
    out = out.resolve()
    routes_root = (routes_root or project_root / "app" / "routes").resolve()
    out.mkdir(parents=True, exist_ok=True)

    freeze_out = project_root / ".causeway" / "build"
    manifest = freeze(
        routes_root=routes_root,
        out_dir=freeze_out,
        user_plugins_module=user_plugins_module,
        settings_target=settings_target,
    )

    binary_name = _binary_name(project_root)
    entry = freeze_out / MIRROR_PACKAGE / "_frozen_entry.py"
    plugin_packages = _collect_plugin_packages(manifest, freeze_out)

    cmd = _nuitka_command(
        entry=entry,
        out_dir=out,
        binary_name=binary_name,
        plugin_packages=plugin_packages,
        extra_packages=extra_packages,
        user_app_package=_infer_user_app_package(project_root),
    )

    if dry_run:
        return BinaryArtifact(path=out / binary_name, size_bytes=0)

    if not _has_nuitka():
        msg = (
            "nuitka is not installed; install with `pip install causeway[binary]` "
            "or `uv add nuitka` in this project."
        )
        raise RuntimeError(msg)

    # Nuitka spawns scanner subprocesses, so cwd alone isn't enough — PYTHONPATH
    # is the reliable way to surface the frozen tree + the user's ``app`` package.
    pythonpath_parts = [str(freeze_out), str(project_root), str(project_root / "src")]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        pythonpath_parts.append(existing)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(pythonpath_parts)}
    subprocess.run(cmd, check=True, cwd=freeze_out, env=env)

    binary_path = out / binary_name
    if not binary_path.is_file():
        msg = f"nuitka finished without producing {binary_path}"
        raise RuntimeError(msg)

    sbom_path = _emit_sbom(binary_path) if sbom else None
    signature_path = _sign(binary_path) if sign else None

    return BinaryArtifact(
        path=binary_path,
        size_bytes=binary_path.stat().st_size,
        sbom_path=sbom_path,
        signature_path=signature_path,
    )


def _nuitka_command(
    *,
    entry: Path,
    out_dir: Path,
    binary_name: str,
    plugin_packages: tuple[str, ...],
    extra_packages: tuple[str, ...],
    user_app_package: str | None,
) -> list[str]:
    cmd: list[str] = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        "--lto=yes",
        "--python-flag=no_site,no_warnings,isolated",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--include-package=causeway",
        "--include-package=starlette",
        "--include-package=uvicorn",
        "--include-package=pydantic",
        "--include-package=pydantic_settings",
        "--include-package=msgspec",
        "--include-package=anyio",
        f"--include-package={MIRROR_PACKAGE}",
        f"--output-dir={out_dir}",
        f"--output-filename={binary_name}",
    ]
    if user_app_package:
        cmd.append(f"--include-package={user_app_package}")
    for pkg in (*plugin_packages, *extra_packages):
        cmd.append(f"--include-package={pkg}")
    for mod in _DEV_SURFACE_EXCLUDES:
        cmd.append(f"--nofollow-import-to={mod}")
    cmd.append(str(entry))
    return cmd


def _collect_plugin_packages(
    manifest: FreezeManifest | None,
    freeze_out: Path,
) -> tuple[str, ...]:
    """Return the unique package per frozen entry-point plugin.

    Filters by the ``_EP_`` alias prefix so future non-plugin imports in
    ``_frozen_plugins.py`` are ignored.
    """
    del manifest
    plugins_py = freeze_out / MIRROR_PACKAGE / "_frozen_plugins.py"
    if not plugins_py.is_file():
        return ()
    packages: set[str] = set()
    for raw in plugins_py.read_text().splitlines():
        line = raw.strip()
        if not line.startswith("from ") or " as _EP_" not in line:
            continue
        head = line.split(" import ", 1)[0]
        module = head[len("from ") :].strip()
        parts = module.split(".")
        if parts[:2] == ["causeway", "contrib"] and len(parts) >= 3:
            packages.add(".".join(parts[:3]))
        else:
            packages.add(parts[0])
    return tuple(sorted(packages))


def _infer_user_app_package(project_root: Path) -> str | None:
    for candidate in (project_root / "src", project_root):
        if not candidate.is_dir():
            continue
        for entry in candidate.iterdir():
            if (
                entry.is_dir()
                and (entry / "__init__.py").is_file()
                and not entry.name.startswith((".", "_"))
            ):
                return entry.name
    return None


def _binary_name(project_root: Path) -> str:
    name = project_root.name
    version = _project_version(project_root)
    plat = _platform_tag()
    suffix = ".exe" if sys.platform == "win32" else ""
    return f"{name}-{version}-{plat}{suffix}"


def _platform_tag() -> str:
    system = sys.platform
    arch = platform.machine().lower()
    if system.startswith("linux"):
        return f"linux-{arch}"
    if system == "darwin":
        return f"darwin-{arch}"
    if system == "win32":
        return f"windows-{arch}"
    return f"{system}-{arch}"


def _project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.is_file():
        return "0.0.0"
    import tomllib

    data = tomllib.loads(pyproject.read_text())
    return str(data.get("project", {}).get("version", "0.0.0"))


def _has_nuitka() -> bool:
    import importlib.util

    return importlib.util.find_spec("nuitka") is not None


def _emit_sbom(binary_path: Path) -> Path | None:
    syft = shutil.which("syft")
    if syft is None:
        sys.stderr.write("causeway: syft not found on PATH; skipping SBOM\n")
        return None
    sbom_path = binary_path.with_suffix(binary_path.suffix + ".sbom.json")
    subprocess.run(
        [syft, "scan", f"file:{binary_path}", "-o", f"cyclonedx-json={sbom_path}"],
        check=True,
    )
    return sbom_path


def _sign(binary_path: Path) -> Path | None:
    cosign = shutil.which("cosign")
    if cosign is None:
        msg = "cosign not found on PATH; cannot sign. Install cosign or drop --sign."
        raise RuntimeError(msg)
    sig_path = binary_path.with_suffix(binary_path.suffix + ".sig")
    args = [cosign, "sign-blob", "--yes", "--output-signature", str(sig_path)]
    if "COSIGN_PRIVATE_KEY" in os.environ:
        args.extend(["--key", "env://COSIGN_PRIVATE_KEY"])
    args.append(str(binary_path))
    subprocess.run(args, check=True)
    return sig_path


__all__ = ["BinaryArtifact", "build_binary"]
