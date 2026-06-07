from __future__ import annotations

import types
from pathlib import Path

import pytest

import causeway.plugins as plugin_registry
from causeway.contrib.fs import FsStorage, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


async def test_startup_creates_root(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = FsStorage(root=root)
    assert not root.exists()
    await store.startup(None)
    assert root.is_dir()
    assert await store.ready() is True
    await store.shutdown()


async def test_put_get_delete_roundtrip(tmp_path: Path) -> None:
    store = FsStorage(root=tmp_path)
    await store.startup(None)

    await store.put("hello.txt", b"world", content_type="text/plain")
    assert (tmp_path / "hello.txt").read_bytes() == b"world"
    assert await store.get("hello.txt") == b"world"

    await store.delete("hello.txt")
    assert not (tmp_path / "hello.txt").exists()
    # Delete is idempotent.
    await store.delete("hello.txt")


async def test_nested_key_creates_dirs(tmp_path: Path) -> None:
    store = FsStorage(root=tmp_path)
    await store.startup(None)
    await store.put("a/b/c.bin", b"\x00\x01")
    assert (tmp_path / "a" / "b" / "c.bin").read_bytes() == b"\x00\x01"


async def test_unsafe_keys_rejected(tmp_path: Path) -> None:
    store = FsStorage(root=tmp_path)
    await store.startup(None)
    with pytest.raises(ValueError, match="unsafe key"):
        await store.put("../escape", b"x")
    with pytest.raises(ValueError, match="unsafe key"):
        await store.put("/abs/path", b"x")


async def test_signed_url_is_file_uri(tmp_path: Path) -> None:
    store = FsStorage(root=tmp_path)
    await store.startup(None)
    await store.put("a.txt", b"hi")
    url = await store.signed_url("a.txt", expires=60)
    assert url.startswith("file://")
    assert url.endswith("a.txt")


async def test_list_yields_only_files(tmp_path: Path) -> None:
    store = FsStorage(root=tmp_path)
    await store.startup(None)
    await store.put("x.txt", b"1")
    await store.put("d/y.txt", b"2")

    keys = [k async for k in store.list()]
    assert sorted(keys) == ["d/y.txt", "x.txt"]


async def test_list_missing_prefix_is_empty(tmp_path: Path) -> None:
    store = FsStorage(root=tmp_path)
    await store.startup(None)
    keys = [k async for k in store.list("does-not-exist")]
    assert keys == []


async def test_plugin_registers_when_root_set(tmp_path: Path) -> None:
    settings = types.SimpleNamespace(fs_storage_root=str(tmp_path))
    plugin(settings)
    registered = plugin_registry.registered()
    assert len(registered) == 1
    assert isinstance(registered[0], FsStorage)


def test_plugin_no_op_without_root() -> None:
    settings = types.SimpleNamespace()
    plugin(settings)
    assert plugin_registry.registered() == []


async def test_ready_false_when_root_missing(tmp_path: Path) -> None:
    target = tmp_path / "missing"
    store = FsStorage(root=target)
    assert await store.ready() is False
