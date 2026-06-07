from __future__ import annotations

import types

import pytest
from msgspec import Struct
from pydantic import BaseModel, SecretStr
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlmodel import Field, SQLModel

import causeway.plugins as plugin_registry
from causeway.contrib.sqlmodel import SqlModelSession, TypedJson, json_field, plugin

_DSN = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


async def test_startup_initializes_engine_and_factory() -> None:
    db = SqlModelSession(dsn=_DSN)
    assert await db.ready() is False
    await db.startup(None)
    try:
        assert await db.ready() is True
        async with db.session() as s:
            result = await s.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await db.shutdown()
    assert await db.ready() is False


async def test_session_outside_startup_raises() -> None:
    db = SqlModelSession(dsn=_DSN)
    with pytest.raises(RuntimeError, match="used before startup"):
        async with db.session():
            pass


async def test_transaction_commits_on_success() -> None:
    db = SqlModelSession(dsn=_DSN)
    await db.startup(None)
    try:
        async with db.session() as s:
            await s.execute(text("CREATE TABLE t (id INTEGER)"))
            await s.commit()

        async with db.transaction() as s:
            await s.execute(text("INSERT INTO t VALUES (1)"))

        async with db.session() as s:
            count = (await s.execute(text("SELECT COUNT(*) FROM t"))).scalar_one()
            assert count == 1
    finally:
        await db.shutdown()


async def test_transaction_rolls_back_on_error() -> None:
    db = SqlModelSession(dsn=_DSN)
    await db.startup(None)

    async def fail_inside_transaction() -> None:
        async with db.transaction() as s:
            await s.execute(text("INSERT INTO t VALUES (1)"))
            raise RuntimeError("boom")

    try:
        async with db.session() as s:
            await s.execute(text("CREATE TABLE t (id INTEGER)"))
            await s.commit()

        with pytest.raises(RuntimeError, match="boom"):
            await fail_inside_transaction()

        async with db.session() as s:
            count = (await s.execute(text("SELECT COUNT(*) FROM t"))).scalar_one()
            assert count == 0
    finally:
        await db.shutdown()


async def test_health_checks_db_connectivity() -> None:
    db = SqlModelSession(dsn=_DSN)
    assert await db.health() is False
    await db.startup(None)
    try:
        assert await db.health() is True
    finally:
        await db.shutdown()
    assert await db.health() is False


async def test_health_false_when_dsn_unreachable() -> None:
    db = SqlModelSession(dsn="sqlite+aiosqlite:////no/such/dir/db.sqlite")
    await db.startup(None)
    try:
        assert await db.health() is False
    finally:
        await db.shutdown()


async def test_shutdown_before_startup_is_noop() -> None:
    db = SqlModelSession(dsn=_DSN)
    await db.shutdown()
    assert await db.ready() is False


async def test_typed_json_field_round_trips_struct() -> None:
    class Payload(Struct):
        enabled: bool
        labels: list[str]

    class JsonDoc(SQLModel, table=True):
        __tablename__ = "typed_json_docs"

        id: int | None = Field(default=None, primary_key=True)
        payload: Payload = json_field(Payload)

    db = SqlModelSession(dsn=_DSN)
    await db.startup(None)
    try:
        assert db._engine is not None
        async with db._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        async with db.transaction() as s:
            s.add(JsonDoc(payload=Payload(enabled=True, labels=["kyc", "edd"])))

        async with db.session() as s:
            doc = await s.get(JsonDoc, 1)
            assert doc is not None
            assert doc.payload == Payload(enabled=True, labels=["kyc", "edd"])
    finally:
        await db.shutdown()


def test_typed_json_uses_jsonb_for_postgres() -> None:
    json_type = TypedJson(dict[str, str], none_as_null=True)
    dialect = postgresql_dialect()

    impl = json_type.load_dialect_impl(dialect)

    assert isinstance(impl, JSONB)
    assert impl.none_as_null is True


def test_typed_json_processes_null_and_untyped_values() -> None:
    json_type = TypedJson()

    assert json_type.process_bind_param(None, object()) is None
    assert json_type.process_result_value({"raw": True}, object()) == {"raw": True}


def test_typed_json_processes_pydantic_values() -> None:
    class PayloadModel(BaseModel):
        enabled: bool

    json_type = TypedJson(PayloadModel)

    assert json_type.process_bind_param(PayloadModel(enabled=True), object()) == {"enabled": True}
    assert json_type.process_result_value({"enabled": False}, object()) == PayloadModel(
        enabled=False
    )


def test_json_field_accepts_default_options() -> None:
    field = json_field(dict[str, str], default={"mode": "test"}, nullable=False)

    assert field.default == {"mode": "test"}
    assert field.nullable is False


def test_json_field_accepts_default_factory() -> None:
    field = json_field(list[str], default_factory=list)

    assert field.default_factory is list


def test_plugin_no_op_without_dsn() -> None:
    plugin(types.SimpleNamespace())
    assert plugin_registry.registered() == []


def test_plugin_registers_when_dsn_present() -> None:
    plugin(types.SimpleNamespace(database_url=_DSN))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, SqlModelSession)
    assert adapter.dsn == _DSN


def test_plugin_unwraps_secret_dsn() -> None:
    plugin(types.SimpleNamespace(database_url=SecretStr(_DSN)))
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, SqlModelSession)
    assert adapter.dsn == _DSN
