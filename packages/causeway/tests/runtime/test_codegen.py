"""IR + codegen tests."""

# pyright: basic
# Tests don't need strict typing; handlers are also consumed via decorator side effects.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import msgspec
import pytest

from causeway._runtime import App, raises, stream
from causeway._runtime.codegen import render, write
from causeway._runtime.ir import build_ir
from causeway._runtime.params import Body, Header


def _render_text(app: App) -> str:
    return "\n".join(render(build_ir(app)).values())


def test_build_ir_captures_routes() -> None:
    app = App()

    @app.get("/ping")
    async def ping() -> str:
        return "pong"

    ir = build_ir(app)
    assert len(ir.routes) == 1
    assert ir.routes[0].path == "/ping"
    assert ir.routes[0].method == "GET"


def test_render_emits_header_and_routes() -> None:
    app = App()

    @app.get("/users/{user_id}")
    async def get_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    out = _render_text(app)
    assert "AUTO-GENERATED" in out
    assert "/users/{user_id}" in out
    assert '"GET"' in out


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    app = App()

    @app.get("/x")
    async def x() -> int:
        return 1

    target = tmp_path / "nested" / "deep" / "client"
    write(build_ir(app), target)
    assert (target / "index.ts").exists()
    assert (target / "types.d.ts").exists()
    assert "AUTO-GENERATED" in (target / "index.ts").read_text()


def test_write_rejects_single_file_output(tmp_path: Path) -> None:
    app = App()

    @app.get("/x")
    async def x() -> int:
        return 1

    with pytest.raises(ValueError, match="client directory"):
        write(build_ir(app), tmp_path / "client.ts")


def test_struct_becomes_ts_type_declaration() -> None:
    class CreatePost(msgspec.Struct):
        title: str
        body: str
        tags: list[str] = []

    app = App()

    @app.post("/posts")
    async def create(data: CreatePost) -> CreatePost:
        return data

    out = _render_text(app)
    assert "export type CreatePost" in out
    assert "title: string" in out
    assert "tags?: Array<string>" in out


def test_streaming_endpoint_emits_asynciterable() -> None:
    class Token(msgspec.Struct, tag_field="kind", tag="token"):
        text: str

    app = App()

    @app.get("/chat")
    async def chat() -> stream[Token]:
        yield Token(text="hi")

    out = _render_text(app)
    assert "data: Token" in out
    assert "streams: true" in out


def test_raises_emits_result_envelope() -> None:
    @dataclass
    class PostNotFound(Exception):
        post_id: int

    app = App()

    @app.get("/posts/{post_id}")
    @raises(PostNotFound)
    async def get_post(post_id: int) -> dict[str, int]:
        return {"id": post_id}

    out = _render_text(app)
    assert '"GET /posts/$post_id": {' in out
    assert "data: Record<string, number>" in out
    assert "error: PostNotFound" in out
    assert "PostNotFound" in out
    assert "requestId?: string | null" in out
    assert "result: true" in out


def test_result_import_omitted_when_no_route_raises() -> None:
    """No `@raises(...)` anywhere → no `Result` helper noise in the generated types."""
    app = App()

    @app.get("/ping")
    async def ping() -> str:
        return "pong"

    files = render(build_ir(app))
    assert "@causewayjs/ts" not in files["types.d.ts"]
    assert "Result" not in files["types.d.ts"]


def test_result_import_omitted_for_streaming_only_raises() -> None:
    """`@raises` on a streaming route surfaces as SSE error frames, not `Result`."""

    @dataclass
    class JobMissing(Exception):
        job_id: str

    class Tick(msgspec.Struct, tag_field="kind", tag="tick"):
        n: int

    app = App()

    @app.get("/jobs/{job_id}/events")
    @raises(JobMissing)
    async def watch(job_id: str) -> stream[Tick]:
        yield Tick(n=1)

    files = render(build_ir(app))
    assert "@causewayjs/ts" not in files["types.d.ts"]
    assert "Result<" not in files["types.d.ts"]


def test_route_contract_includes_error_union_when_any_route_raises() -> None:
    @dataclass
    class NotFound(Exception):
        thing_id: int

    app = App()

    @app.get("/ping")
    async def ping() -> str:
        return "pong"

    @app.get("/thing/{thing_id}")
    @raises(NotFound)
    async def get_thing(thing_id: int) -> dict[str, int]:
        return {"id": thing_id}

    files = render(build_ir(app))
    assert "error: NotFound" in files["types.d.ts"]
    assert "Result<" not in files["types.d.ts"]


def test_render_emits_configurable_api_factory_for_ssr() -> None:
    app = App()

    @app.get("/users/{user_id}")
    async def get_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    files = render(build_ir(app))
    out = "\n".join(files.values())
    assert files["index.ts"].startswith(
        "// @ts-nocheck\n/* eslint-disable */\n// biome-ignore-all lint: generated causeway client\n"
    )
    assert "export function createClient(options: RouteClientOptions = {})" in files["index.ts"]
    assert "return createRouteClient({ ...options, routeMeta, loadRoute })" in files["index.ts"]
    assert "export const client = createClient()" in files["index.ts"]
    assert "export const routeMeta: ReadonlyArray<RouteMeta>" in out
    assert 'import meta from "./meta.json"' in files["meta.ts"]
    assert "export async function loadRoute" in out
    assert '"routeKey": "GET /users/$user_id"' in files["meta.json"]
    assert '"path": "/users/{user_id}"' in files["meta.json"]
    assert "segments:" not in out
    assert "verb:" not in out


def test_render_emits_route_key_types_and_metadata() -> None:
    app = App()

    @app.get("/customers/{id}")
    async def get_customer(id: str) -> dict[str, str]:
        return {"id": id}

    @app.post("/customers/{id}/screen")
    async def screen_customer(id: str) -> dict[str, str]:
        return {"id": id}

    app.routes[1].refreshes = ("GET /customers/$id", "GET /customers")

    files = render(build_ir(app))
    types = files["types.d.ts"]
    meta_json = files["meta.json"]
    assert 'export type QueryRouteKey = "GET /customers/$id";' in types
    assert 'export type MutationRouteKey = "POST /customers/$id/screen";' in types
    assert '"GET /customers/$id": {' in types
    assert "input: { id: string }" in types
    assert 'export type RouteInput<K extends RouteKey> = RouteContracts[K]["input"];' in types
    assert 'declare module "@causewayjs/client"' in types
    assert "queryRouteKey: QueryRouteKey" in types
    assert "routeData: { [K in RouteKey]: RouteData<K> }" in types
    assert '"routeKey": "POST /customers/$id/screen"' in meta_json
    assert '"refreshes": [' in meta_json
    assert '"GET /customers/$id"' in meta_json
    assert '"GET /customers"' in meta_json


def test_load_route_emits_one_import_per_chunk_not_per_route() -> None:
    # Bundlers (Turbopack especially) track every `import(...)` call site as a
    # separate code-split computation in their persistent cache. The loader
    # must dedupe to one import per chunk file or the cache explodes on apps
    # with hundreds of routes — see https://github.com/tamimbinhakim/causeway.
    app = App()

    @app.get("/users")
    async def list_users() -> list[int]:
        return []

    @app.get("/users/{user_id}")
    async def get_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    @app.post("/users")
    async def create_user(name: str) -> dict[str, str]:
        return {"name": name}

    @app.get("/posts")
    async def list_posts() -> list[int]:
        return []

    files = render(build_ir(app))
    loader = files["routes/index.ts"]
    # Three user routes collapse to one `import("./users")`, posts to one
    # `import("./posts")`. The route table is plain strings, not imports.
    assert loader.count('import("./users")') == 1
    assert loader.count('import("./posts")') == 1
    assert "chunkLoaders" in loader
    assert "routeChunks" in loader
    # No fall-through switch case — the route table maps id → chunk directly.
    assert "switch (id)" not in loader
    assert 'case "listUsers"' not in loader


def test_descriptor_includes_param_locations() -> None:
    app = App()

    @app.get("/u/{user_id}")
    async def lookup(
        user_id: int,
        q: str,
        x_trace: Annotated[str, Header(alias="x-trace-id")] = "",
    ) -> dict[str, str]:
        return {"user_id": str(user_id), "q": q, "trace": x_trace}

    out = _render_text(app)
    assert 'in: "path"' in out
    assert 'in: "query"' in out
    assert 'in: "header"' in out
    assert '"x-trace-id"' in out


def test_embedded_body_params_marked_embed() -> None:
    app = App()

    @app.post("/login")
    async def login(
        email: Annotated[str, Body()],
        password: Annotated[str, Body()],
    ) -> dict[str, str]:
        return {"email": email, "pw_len": str(len(password))}

    out = _render_text(app)
    assert out.count("embed: true") == 2


def test_route_contract_emitted_for_unary_with_raises() -> None:
    @dataclass
    class NotFound(Exception):
        post_id: int

    app = App()

    @app.get("/posts/{post_id}")
    @raises(NotFound)
    async def get_post(post_id: int) -> dict[str, int]:
        return {"id": post_id}

    out = _render_text(app)
    assert "export interface RouteContracts" in out
    assert '"GET /posts/$post_id": {' in out
    assert "input: { postId: number }" in out
    assert "data: Record<string, number>" in out
    assert "error: NotFound" in out


def test_route_contract_for_streaming_endpoint() -> None:
    class Token(msgspec.Struct, tag_field="kind", tag="token"):
        text: str

    app = App()

    @app.get("/chat")
    async def chat() -> stream[Token]:
        yield Token(text="hi")

    out = _render_text(app)
    assert '"GET /chat": {' in out
    assert "data: Token" in out
    assert "streams: true" in out


def test_mixed_param_path_emits_route_key_contract() -> None:
    app = App()

    @app.get("/exports/{id}.csv")
    async def export_csv(id: str) -> dict[str, str]:
        return {"id": id}

    out = _render_text(app)
    assert '"GET /exports/$id.csv": {' in out
    assert "input: { id: string }" in out
    assert 'path: "/exports/{id}.csv"' in out
    assert "segments:" not in out
    assert "verb:" not in out


def test_enum_field_stays_type_only() -> None:
    class Issue(msgspec.Struct):
        id: int
        status: Literal["open", "in_progress", "blocked", "closed"]

    app = App()

    @app.get("/issues/{issue_id}")
    async def get_issue(issue_id: int) -> Issue:
        return Issue(id=issue_id, status="open")

    out = _render_text(app)
    assert '| "open"' in out
    assert '| "in_progress"' in out
    assert '| "blocked"' in out
    assert '| "closed"' in out
    assert "export const IssueStatus = " not in out


def test_kind_discriminator_skipped_for_enum_const() -> None:
    """Tag values (kind) are msgspec internals — no `EvenKind` const."""

    class Foo(msgspec.Struct, tag_field="kind", tag="foo"):
        x: int

    class Bar(msgspec.Struct, tag_field="kind", tag="bar"):
        y: int

    app = App()

    @app.get("/event")
    async def evt() -> Foo | Bar:
        return Foo(x=1)

    out = _render_text(app)
    # No `FooKind` / `BarKind` const should appear.
    assert "FooKind" not in out
    assert "BarKind" not in out


def test_large_struct_wraps_to_multi_line() -> None:
    """Structs past the inline-field threshold render one field per line."""

    class BigStruct(msgspec.Struct):
        a: int
        b: int
        c: int
        d: int
        e: int

    app = App()

    @app.post("/big")
    async def big(data: BigStruct) -> BigStruct:
        return data

    out = _render_text(app)
    assert "export type BigStruct = {\n  a: number;\n" in out
    # Trailing comma on the close brace's preceding line is preserved.
    assert "  e: number;\n};" in out


def test_small_struct_stays_inline() -> None:
    """≤ 3-field structs without nested objects stay on one line."""

    class Tiny(msgspec.Struct):
        a: int
        b: str

    app = App()

    @app.post("/tiny")
    async def tiny(data: Tiny) -> Tiny:
        return data

    out = _render_text(app)
    assert "export type Tiny = { a: number; b: string };" in out


def test_handler_docstring_not_emitted_as_jsdoc() -> None:
    app = App()

    @app.get("/ping")
    async def ping() -> str:
        """Health probe — returns the literal string ``pong``."""
        return "pong"

    out = _render_text(app)
    assert "Health probe" not in out
    assert '"GET /ping": {' in out
    assert "data: string" in out


def test_multi_line_docstring_not_emitted_as_jsdoc() -> None:
    app = App()

    @app.get("/x")
    async def x() -> int:
        """First line.

        Second paragraph with extra detail.
        """
        return 1

    out = _render_text(app)
    assert "First line." not in out
    assert "Second paragraph with extra detail." not in out
    assert '"GET /x": {' in out
    assert "data: number" in out


def test_msgspec_auto_title_not_emitted_as_jsdoc() -> None:
    """msgspec emits ``title=<ClassName>`` on every Struct; that's noise, not docs."""

    class Plain(msgspec.Struct):
        x: int

    app = App()

    @app.post("/plain")
    async def plain(data: Plain) -> Plain:
        return data

    out = _render_text(app)
    # The redundant `/** Plain */` JSDoc above `export type Plain` must NOT appear.
    assert "/** Plain */\nexport type Plain" not in out


def test_unconstrained_object_type_is_not_never_record() -> None:
    class Payload(msgspec.Struct):
        metadata: dict[str, Any]

    app = App()

    @app.post("/payload")
    async def payload(data: Payload) -> Payload:
        return data

    out = _render_text(app)
    assert "export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];" in out
    assert "metadata: JsonObject" in out
    assert "Record<string, never>" not in out


def test_opaque_dict_fields_emit_route_descriptor_paths() -> None:
    """`dict[str, Any]` fields surface as opaqueRequestPaths / opaqueResponsePaths.

    The TS runtime uses these paths to skip snake_case<->camelCase rename
    inside user-defined JSON payloads, so opaque content round-trips with
    its original keys intact.
    """

    class Version(msgspec.Struct):
        id: str
        definition: dict[str, Any]

    class VersionBody(msgspec.Struct):
        definition: dict[str, Any]
        change_note: str | None = None

    app = App()

    @app.post("/versions")
    async def create_version(body: VersionBody) -> Version:
        return Version(id="1", definition=body.definition)

    out = _render_text(app)
    assert (
        '"opaqueRequestPaths": ["definition"]' in out or 'opaqueRequestPaths: ["definition"]' in out
    )
    assert (
        '"opaqueResponsePaths": ["definition"]' in out
        or 'opaqueResponsePaths: ["definition"]' in out
    )


def test_opaque_paths_prefixed_with_data_for_result_routes() -> None:
    """When the route declares `@raises`, the response is wrapped in
    `Result<T, E>` (`{ok: true, data: T}`) — opaque paths must be prefixed
    with `data.` so they apply to the success-envelope payload at runtime.
    """

    class NotFound(Exception):
        pass

    class Version(msgspec.Struct):
        id: str
        definition: dict[str, Any]

    app = App()

    @app.get("/versions/{id}")
    @raises(NotFound)
    async def show_version(id: str) -> Version:
        return Version(id=id, definition={})

    out = _render_text(app)
    assert 'opaqueResponsePaths: ["data.definition"]' in out


def test_opaque_paths_skip_routes_with_no_response_body() -> None:
    """Routes returning `None` skip opaque-path collection on the response side."""

    app = App()

    @app.post("/jobs/{id}/cancel")
    async def cancel_job(id: str) -> None:
        return None

    out = _render_text(app)
    assert "opaqueResponsePaths" not in out
    assert "opaqueRequestPaths" not in out


def test_opaque_paths_skip_routes_with_no_body_params() -> None:
    """Routes whose only inputs are path/query/header params skip request-side collection."""

    app = App()

    @app.get("/items/{id}")
    async def show_item(id: str, q: str = "") -> dict[str, str]:
        return {"id": id, "q": q}

    out = _render_text(app)
    assert "opaqueRequestPaths" not in out


def test_opaque_paths_handle_optional_union_fields() -> None:
    """`X | None` becomes a `oneOf`/`anyOf` (or `type: [...]`) branch — the walker
    must descend each branch without crashing on the non-object branches.
    """

    class Outer(msgspec.Struct):
        title: str | None = None
        config: dict[str, Any] = {}

    app = App()

    @app.get("/items")
    async def list_items() -> Outer:
        return Outer()

    out = _render_text(app)
    assert 'opaqueResponsePaths: ["config"]' in out


def test_opaque_walk_terminates_on_recursive_components() -> None:
    """A self-referencing component must not loop the cycle guard forever.

    Exercises `_walk_for_opaque` directly because msgspec can't resolve a
    forward-ref inside a function-scoped struct (this is purely about the
    walker's cycle handling, not about codegen).
    """
    from causeway._runtime.codegen import _walk_for_opaque

    components: dict[str, dict[str, Any]] = {
        "Node": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "child": {"$ref": "#/components/schemas/Node"},
                "meta": {"type": "object"},
            },
        }
    }
    out: list[str] = []
    _walk_for_opaque(
        {"$ref": "#/components/schemas/Node"},
        components,
        prefix="root",
        out=out,
        seen=set(),
    )
    # Walker terminates and records the opaque `meta` field exactly once.
    assert out == ["root.meta"]


def test_opaque_walk_ignores_missing_refs_and_non_dict_schemas() -> None:
    """Dangling `$ref` and non-dict schema inputs must short-circuit cleanly."""
    from causeway._runtime.codegen import _walk_for_opaque

    out: list[str] = []
    _walk_for_opaque({"$ref": "#/components/schemas/Missing"}, {}, prefix="x", out=out, seen=set())
    _walk_for_opaque(None, {}, prefix="x", out=out, seen=set())  # type: ignore[arg-type]
    _walk_for_opaque("not-a-dict", {}, prefix="x", out=out, seen=set())  # type: ignore[arg-type]
    assert out == []


def test_opaque_paths_descend_into_arrays() -> None:
    """Opaque-path collection should walk through array `items` so that
    `list[dict[str, Any]]` surfaces the opaque element type. Arrays inherit
    the parent path — opaque paths are property-relative, not index-relative.
    """

    class Outer(msgspec.Struct):
        rows: list[dict[str, Any]]

    app = App()

    @app.get("/outer")
    async def get_outer() -> Outer:
        return Outer(rows=[])

    out = _render_text(app)
    assert 'opaqueResponsePaths: ["rows"]' in out


def test_struct_docstring_not_emitted_as_jsdoc() -> None:
    class Thing(msgspec.Struct):
        """A thing that lives in the system."""

        id: int

    app = App()

    @app.post("/things")
    async def create(data: Thing) -> Thing:
        return data

    out = _render_text(app)
    assert "A thing that lives in the system." not in out
    assert "export type Thing" in out


def test_route_descriptor_wraps_when_long() -> None:
    """Long route descriptors break onto multiple lines with trailing commas."""
    app = App()

    @app.get("/posts")
    async def list_posts(
        tag: Annotated[list[str] | None, Header()] = None,
        cursor: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, int]]:
        return []

    out = _render_text(app)
    # The multi-param list should wrap with item-per-line and trailing commas.
    assert 'params: [\n    { name: "tag",' in out
    assert "  ],\n};" in out


def test_long_route_contract_wraps_input_object() -> None:
    """Long input contracts stay readable without emitting generated method overloads."""
    app = App()

    @app.get("/search")
    async def search_with_many_filters(
        query: str,
        category: str,
        tag: str,
        author: str,
        sort: str,
        cursor: str | None = None,
    ) -> list[dict[str, str]]:
        return []

    files = render(build_ir(app))
    types = files["types.d.ts"]
    assert '"GET /search": {' in types
    assert "input: {" in types
    assert "query: string;" in types
    assert "cursor?: string | null;" in types
    assert "CallOptions" not in types


def test_struct_named_array_gets_renamed_to_avoid_shadowing_builtin() -> None:
    """A user struct called ``Array`` must not be emitted as ``export type Array``."""

    class Array(msgspec.Struct):
        items: list[int]

    app = App()

    @app.post("/arr")
    async def arr(data: Array) -> Array:
        return data

    out = _render_text(app)
    assert "export type Array =" not in out
    # The render path always uses the disambiguated name, both for the type
    # declaration and at every reference site — so no orphaned `Array` refs.
    assert "export type Array " not in out


def test_struct_named_delete_gets_renamed() -> None:
    """JS reserved words like ``delete`` are not valid top-level type names."""

    class delete(msgspec.Struct):
        x: int

    app = App()

    @app.post("/d")
    async def d(data: delete) -> delete:
        return data

    out = _render_text(app)
    assert "export type delete " not in out


def test_route_name_collision_raises() -> None:
    """Two routes that camelCase to the same TS name fail loudly at render."""
    app = App()

    @app.get("/a")
    async def get_user() -> int:
        return 1

    @app.get("/b")
    async def getUser() -> int:  # collision with `get_user` is the point of the test
        return 2

    ir = build_ir(app)
    with pytest.raises(ValueError, match="getUser"):
        render(ir)


def test_duplicate_route_names_are_path_qualified() -> None:
    app = App()

    @app.get("/accounts/{id}")
    async def show_account(id: str) -> dict[str, str]:
        return {"id": id}

    @app.get("/customers/{id}")
    async def show_customer(id: str) -> dict[str, str]:
        return {"id": id}

    show_account.__name__ = "show"
    show_customer.__name__ = "show"

    out = _render_text(app)
    assert '"GET /accounts/$id": {' in out
    assert '"GET /customers/$id": {' in out
    assert '"id": "accountsIdShow"' in out
    assert '"id": "customersIdShow"' in out
    assert "segments:" not in out
    assert "verb:" not in out
    assert '"id": "show"' not in out


def test_enum_literals_do_not_emit_runtime_values() -> None:
    class UserRole(msgspec.Struct):
        slug: str

    class User(msgspec.Struct):
        id: int
        role: Literal["admin", "member"]

    app = App()

    @app.get("/users/{user_id}")
    async def get_user(user_id: int) -> User:
        return User(id=user_id, role="admin")

    @app.get("/roles")
    async def list_roles() -> list[UserRole]:
        return []

    out = _render_text(app)
    assert "export type UserRole =" in out  # User struct keeps its name.
    assert "export const UserRole = " not in out


def test_duplicate_enum_literal_fields_stay_type_only() -> None:
    class A(msgspec.Struct):
        status: Literal["a", "b"]

    class B(msgspec.Struct):
        status: Literal["c", "d"]

    app = App()

    @app.get("/a")
    async def aa() -> A:
        return A(status="a")

    @app.get("/b")
    async def bb() -> B:
        return B(status="c")

    out = _render_text(app)
    assert 'status: "a" | "b"' in out
    assert 'status: "c" | "d"' in out
    assert "export const AStatus = " not in out
    assert "export const BStatus = " not in out


def test_exact_optional_vs_nullable() -> None:
    """T: msgspec's required + anyOf-with-null translate to TS correctly."""

    class Mixed(msgspec.Struct, kw_only=True):
        a: int  # required, non-null    → a: number
        b: int = 5  # default, non-null → b?: number
        c: int | None  # required, null → c: number | null
        d: int | None = None  # default, null → d?: number | null

    app = App()

    @app.post("/mixed")
    async def mixed(data: Mixed) -> Mixed:
        return data

    out = _render_text(app)
    # Order in msgspec output may vary; check each shape appears.
    assert "a: number" in out
    assert "a?: number" not in out
    assert "b?: number" in out
    assert "c: number | null" in out
    assert "d?: number | null" in out


# Module-scope types for the generics test. msgspec resolves forward refs in
# the class's own globals, so these can't live inside the test function when
# ``from __future__ import annotations`` is active.
from typing import Generic, TypeVar  # noqa: E402

_GenT = TypeVar("_GenT")
_GenE = TypeVar("_GenE")


class _GenBadRequest(Exception):
    """Stand-in for a typed HTTP error inside a generic type parameter."""


class _GenFailure(msgspec.Struct, Generic[_GenT, _GenE]):
    input: _GenT
    error: _GenE


class _GenBatchOut(msgspec.Struct, Generic[_GenT, _GenE]):
    ok: list[_GenT]
    failed: list[_GenFailure[_GenT, _GenE]]


class _GenPage(msgspec.Struct, Generic[_GenT]):
    items: list[_GenT]
    next_cursor: str | None = None


class _GenItem(msgspec.Struct):
    name: str


def test_generic_struct_with_exception_in_type_args() -> None:
    """User-defined generics with an Exception class inside (e.g. ``BatchResult[T, E]``)
    must flow through the IR — msgspec needs the schema_hook the IR installs.
    """
    app = App()

    @app.post("/bulk")
    async def bulk(items: list[_GenItem]) -> _GenBatchOut[_GenItem, _GenBadRequest]:
        return _GenBatchOut(ok=[], failed=[])

    out = _render_text(app)
    # The generic parameterization reaches the components map; the error's
    # synthesized tagged Struct surfaces inline so the TS client can narrow
    # on ``error.kind``.
    assert "GenBatchOut" in out
    assert "kind" in out


def test_generic_components_survive_duplicate_type_names() -> None:
    run_a = msgspec.defstruct("Run", [("id", str)])
    run_b = msgspec.defstruct("Run", [("id", str), ("status", str)])
    app = App()

    async def list_a() -> _GenPage[run_a]:  # type: ignore[valid-type]
        return _GenPage(items=[])

    async def list_b() -> _GenPage[run_b]:  # type: ignore[valid-type]
        return _GenPage(items=[])

    app.get("/a")(list_a)
    app.get("/b")(list_b)

    ir = build_ir(app)
    assert len(ir.routes) == 2
    assert len([name for name in ir.components if name.startswith("_GenPage_Run")]) == 2
    render(ir)
