"""SQLModel / SQLAlchemy adapter for :class:`causeway.contracts.DBSession`.

Provides an ``AsyncEngine``-backed session factory plus a transaction
context manager. The session itself is exposed as a Causeway scope provider
so handlers pull it via ``Annotated[AsyncSession, db_session]``.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

import msgspec
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.types import TypeDecorator

if TYPE_CHECKING:
    JsonPrimitive: TypeAlias = str | int | float | bool | None
    JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
    JsonObject: TypeAlias = dict[str, JsonValue]
    JsonArray: TypeAlias = list[JsonValue]
else:
    JsonPrimitive = str | int | float | bool | None
    JsonValue = Any
    JsonObject = dict[str, Any]
    JsonArray = list[Any]


class TypedJson(TypeDecorator[Any]):
    """SQLAlchemy JSON/JSONB column that round-trips a declared Python type.

    Use this when a JSON column has a real shape instead of annotating it as
    ``dict[str, Any]`` everywhere:

        payload: MyPayload = Field(sa_type=TypedJson(MyPayload))

    The database still stores JSON. On writes, msgspec-friendly structs,
    dataclasses, UUIDs, dates, and other JSON-compatible Python values are
    converted to builtins. On reads, ``python_type`` is applied with
    ``msgspec.convert`` so route code gets the typed shape back.
    """

    impl = JSON
    cache_ok = True

    def __init__(
        self,
        python_type: Any = Any,
        *,
        use_jsonb: bool = True,
        none_as_null: bool = False,
    ) -> None:
        super().__init__()
        self.value_type = python_type
        self.use_jsonb = use_jsonb
        self.none_as_null = none_as_null

    def load_dialect_impl(self, dialect: Any) -> Any:
        if self.use_jsonb and dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB(none_as_null=self.none_as_null))
        return dialect.type_descriptor(JSON(none_as_null=self.none_as_null))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        del dialect
        if value is None:
            return None
        return _to_jsonable(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        del dialect
        if value is None or self.value_type in (Any, object):
            return value
        if hasattr(self.value_type, "model_validate"):
            return self.value_type.model_validate(value)
        return msgspec.convert(value, self.value_type)


_UNSET = object()


def json_field(
    python_type: Any = Any,
    *,
    default: Any = _UNSET,
    default_factory: Any = _UNSET,
    use_jsonb: bool = True,
    none_as_null: bool = False,
    **field_kwargs: Any,
) -> Any:
    """Return a SQLModel ``Field`` backed by :class:`TypedJson`.

    This keeps model declarations compact while preserving a typed Python
    shape for JSON columns.

        payload: MyPayload = json_field(MyPayload)
    """

    from sqlmodel import Field

    if default is not _UNSET:
        field_kwargs["default"] = default
    if default_factory is not _UNSET:
        field_kwargs["default_factory"] = default_factory
    field_kwargs["sa_type"] = TypedJson(
        python_type,
        use_jsonb=use_jsonb,
        none_as_null=none_as_null,
    )
    return Field(**field_kwargs)


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return msgspec.to_builtins(value)


class SqlModelSession:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(self, dsn: str, *, echo: bool = False) -> None:
        self.dsn = dsn
        self.echo = echo
        self._engine: AsyncEngine | None = None
        self._factory: Any = None

    async def startup(self, settings: Any) -> None:
        del settings
        self._engine = create_async_engine(self.dsn, echo=self.echo, future=True)
        self._factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._factory = None

    async def ready(self) -> bool:
        return self._engine is not None

    def session(self) -> contextlib.AbstractAsyncContextManager[AsyncSession]:
        return self._session_ctx()

    @contextlib.asynccontextmanager
    async def _session_ctx(self) -> AsyncGenerator[AsyncSession]:
        if self._factory is None:
            msg = "SqlModelSession used before startup()"
            raise RuntimeError(msg)
        async with self._factory() as session:
            yield session

    def transaction(self) -> contextlib.AbstractAsyncContextManager[AsyncSession]:
        return self._transaction_ctx()

    @contextlib.asynccontextmanager
    async def _transaction_ctx(self) -> AsyncGenerator[AsyncSession]:
        async with self._session_ctx() as session, session.begin():
            yield session

    async def health(self) -> bool:
        if self._engine is None:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
        except Exception:
            return False
        return True


def plugin(settings: Any) -> None:
    from causeway import register

    dsn = getattr(settings, "database_url", None)
    if not dsn:
        return
    if hasattr(dsn, "get_secret_value"):
        dsn = dsn.get_secret_value()
    register(SqlModelSession(dsn=str(dsn)))


__all__ = [
    "JsonArray",
    "JsonObject",
    "JsonPrimitive",
    "JsonValue",
    "SqlModelSession",
    "TypedJson",
    "json_field",
    "plugin",
]
