"""IR builder.

Every registered handler reduces to a JSON-Schema-2020-12 IR that the
codegen walks to emit TypeScript. The two-step (IR → renderer) split keeps
type extraction independent of the renderer.

Two passes:

1. Per-route: reuse the runtime's ``build_plan`` so the IR sees the same
   parameter resolution the request path does — no drift between what
   the wire accepts and what the client generates for.
2. Global schema bake: collect every type and call
   ``msgspec.json.schema_components`` once. Shared types get one ``$defs``
   entry, not one per route.
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass, fields
from typing import Any, cast

import msgspec

from causeway._runtime._pydantic import is_pydantic_model
from causeway._runtime._pydantic import json_schema as pydantic_json_schema
from causeway._runtime.app import App, Route
from causeway._runtime.params import ParamLocation
from causeway._runtime.runtime import HandlerPlan, build_plan

_REF_TEMPLATE = "#/$defs/{name}"


@dataclass(slots=True)
class ParamIR:
    name: str
    alias: str
    schema: dict[str, Any]
    location: ParamLocation
    required: bool
    embed: bool = False


@dataclass(slots=True)
class ErrorIR:
    name: str
    schema: dict[str, Any]


@dataclass(slots=True)
class RouteIR:
    method: str
    path: str
    route_key: str
    name: str
    source: str | None
    scopes: tuple[str, ...]
    params: list[ParamIR]
    response: dict[str, Any] | None
    streams: bool
    event_schema: dict[str, Any] | None
    raises: list[ErrorIR]
    refreshes: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    idempotency: dict[str, Any] | None = None
    binary_body: bool = False  # body is raw bytes (skip JSON envelope)
    binary_response: bool = False  # response is raw bytes (decode as Blob on TS side)
    form_body: bool = False  # body is application/x-www-form-urlencoded / multipart
    description: str | None = None  # handler docstring, surfaces as JSDoc in generated types


@dataclass(slots=True)
class AppIR:
    routes: list[RouteIR]
    components: dict[str, dict[str, Any]]


# Sentinel for "this slot doesn't need a schema" (File params, None returns).
# Keeps the type-list positions stable so we can stitch results back by index.
class _Skip:
    pass


def build_ir(app: App) -> AppIR:
    plans: list[tuple[Route, HandlerPlan]] = []
    for route in app.routes:
        plan = route.plan or build_plan(route.handler, route.path)
        route.plan = plan
        plans.append((route, plan))

    types_for_extraction: list[Any] = []
    slots: list[tuple[str, int, Any]] = []  # (kind, route_idx, payload)

    for r_idx, (_route, plan) in enumerate(plans):
        for p in plan.params:
            if p.location is None:  # Context / Depends — not on the wire
                continue
            slots.append(("param", r_idx, p))
            if p.location == "file" or p.py_type is bytes:
                # File uploads + raw-byte body slots use a fixed binary schema.
                types_for_extraction.append(_Skip)
            else:
                types_for_extraction.append(
                    p.py_type if p.py_type is not inspect.Signature.empty else Any,
                )

        ret = plan.return_annotation
        slots.append(("response", r_idx, None))
        if plan.streams and plan.event_type is not None:
            types_for_extraction.append(plan.event_type)
        elif ret is None or ret is type(None) or ret is inspect.Signature.empty or ret is bytes:
            types_for_extraction.append(_Skip)
        else:
            types_for_extraction.append(ret)

        for exc in plan.raises:
            slots.append(("raises", r_idx, exc))
            types_for_extraction.append(_synth_exc_type(exc))

    # msgspec.json.schema_components chokes on Pydantic models and _Skip
    # placeholders. Split the type list into:
    #   - msgspec-handled types (Struct/dataclass/scalar)
    #   - Pydantic models (handled by ``model_json_schema``)
    # and stitch the merged schemas back to their original slot index.
    msgspec_indices: list[int] = []
    msgspec_types: list[Any] = []
    pydantic_indices: list[int] = []
    pydantic_types: list[Any] = []
    pydantic_modes: list[str] = []  # "validation" for params, "serialization" for responses
    for i, t in enumerate(types_for_extraction):
        if t is _Skip:
            continue
        if is_pydantic_model(t):
            pydantic_indices.append(i)
            pydantic_types.append(t)
            # Response/event/raises slots want serialization mode so that
            # ``@computed_field`` properties land in the generated TS type.
            kind = slots[i][0]
            pydantic_modes.append(
                "serialization" if kind in ("response", "raises") else "validation",
            )
        else:
            msgspec_indices.append(i)
            msgspec_types.append(t)

    schemas_by_index: dict[int, dict[str, Any]] = {}
    components: dict[str, dict[str, Any]] = {}
    if msgspec_types:
        # A user-defined generic like ``BatchResult[T, E]`` may parameterize
        # ``E`` with a bare Exception subclass — msgspec doesn't know how to
        # emit a schema for that on its own. Resolve to the same synthesized
        # tagged Struct the top-level ``@raises`` path uses so the TS client
        # can narrow on ``error.kind`` either way. We inline the schema (no
        # ``$ref``) because the schema_hook can't add to the shared components
        # dict — codegen tolerates the duplication.
        def _schema_hook(t: type[Any]) -> dict[str, Any]:
            # ``object`` (and bare ``Any``) shows up when a generic Struct uses
            # ``T`` for a heterogeneous slot — emit "any" rather than failing.
            if t is object:
                return {}
            if issubclass(t, Exception):
                synth = _synth_exc_type(t)
                full = msgspec.json.schema(synth)
                defs = cast("dict[str, dict[str, Any]]", full.pop("$defs", {}) or {})
                ref = full.get("$ref")
                if isinstance(ref, str):
                    name = ref.rsplit("/", 1)[-1]
                    inlined = defs.get(name)
                    if inlined is not None:
                        return inlined
                return full
            raise TypeError(str(t))

        real_schemas, real_components = _msgspec_schema_components(
            msgspec_types,
            schema_hook=_schema_hook,
        )
        for i, s in zip(msgspec_indices, real_schemas, strict=True):
            schemas_by_index[i] = s
        components.update(real_components)

    for i, t, mode in zip(pydantic_indices, pydantic_types, pydantic_modes, strict=True):
        schema, pyd_components = _split_pydantic_schema(pydantic_json_schema(t, mode=mode))
        schemas_by_index[i] = schema
        components.update(pyd_components)

    routes_ir: list[RouteIR] = []
    for r_idx, (route, plan) in enumerate(plans):
        params_ir: list[ParamIR] = []
        response_schema: dict[str, Any] | None = None
        event_schema: dict[str, Any] | None = None
        raises_ir: list[ErrorIR] = []
        binary_body = False
        binary_response = plan.return_annotation is bytes
        form_body = any(p.is_form for p in plan.params)

        for slot_idx, (kind, slot_r_idx, payload) in enumerate(slots):
            if slot_r_idx != r_idx:
                continue
            slot_schema: dict[str, Any] | None = schemas_by_index.get(slot_idx)
            if kind == "param":
                p = payload
                assert p.location is not None
                if p.py_type is bytes and p.location == "body":
                    binary_body = True
                    slot_schema = _binary_schema()
                params_ir.append(
                    ParamIR(
                        name=p.name,
                        alias=p.alias,
                        schema=slot_schema if slot_schema is not None else _binary_schema(),
                        location=p.location,
                        required=p.required,
                        embed=p.embed,
                    ),
                )
            elif kind == "response":
                if plan.streams:
                    event_schema = slot_schema
                elif binary_response:
                    response_schema = _binary_schema()
                else:
                    response_schema = slot_schema
            elif kind == "raises":
                raises_ir.append(
                    ErrorIR(name=payload.__name__, schema=slot_schema or _exc_schema(payload)),
                )

        routes_ir.append(
            RouteIR(
                method=route.method,
                path=route.path,
                route_key=route.route_key or f"{route.method} {route.path}",
                name=route.name or route.handler.__name__,
                source=route.source,
                scopes=route.scopes,
                params=params_ir,
                response=response_schema,
                streams=plan.streams,
                event_schema=event_schema,
                raises=raises_ir,
                refreshes=route.refreshes,
                requires=route.requires,
                idempotency=route.idempotency,
                binary_body=binary_body,
                binary_response=binary_response,
                form_body=form_body,
                description=_extract_docstring(route.handler),
            ),
        )

    return AppIR(routes=routes_ir, components=components)


def _binary_schema() -> dict[str, Any]:
    """Wire shape for raw bytes — File uploads + ``bytes`` body/response slots."""
    return {"type": "string", "format": "binary"}


def _extract_docstring(handler: Any) -> str | None:
    return inspect.getdoc(handler) or None


def _split_pydantic_schema(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split a Pydantic schema's ``$defs`` out into a components dict.

    Pydantic emits ``#/$defs/Name`` refs that the codegen already understands —
    we just need the defs hoisted into the shared components bucket alongside
    msgspec's, and the schema rewritten to be a bare ``$ref`` so it slots into
    the same slot-by-index machinery msgspec types use.
    """
    defs_any: Any = schema.pop("$defs", {}) or {}
    defs = cast("dict[str, dict[str, Any]]", defs_any)
    components: dict[str, dict[str, Any]] = dict(defs)
    title = schema.get("title")
    if title and schema.get("type") == "object":
        components[str(title)] = schema
        return {"$ref": f"#/$defs/{title}"}, components
    return schema, components


def _msgspec_schema_components(
    types: list[Any],
    *,
    schema_hook: Any,
) -> tuple[tuple[dict[str, Any], ...], dict[str, dict[str, Any]]]:
    try:
        return msgspec.json.schema_components(
            types,
            ref_template=_REF_TEMPLATE,
            schema_hook=schema_hook,
        )
    except KeyError:
        pass

    schemas: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}
    for typ in types:
        (schema,), next_components = msgspec.json.schema_components(
            [typ],
            ref_template=_REF_TEMPLATE,
            schema_hook=schema_hook,
        )
        renames = _component_renames(components, next_components)
        schemas.append(_rewrite_refs(schema, renames))
        for name, component in next_components.items():
            components[renames.get(name, name)] = _rewrite_refs(component, renames)
    return tuple(schemas), components


def _component_renames(
    existing: dict[str, dict[str, Any]],
    incoming: dict[str, dict[str, Any]],
) -> dict[str, str]:
    renames: dict[str, str] = {}
    for name, schema in incoming.items():
        if name not in existing or existing[name] == schema:
            continue
        renames[name] = _next_component_name(name, existing, incoming, renames)
    for name, schema in incoming.items():
        if name in renames or name not in existing:
            continue
        if existing[name] != _rewrite_refs(schema, renames):
            renames[name] = _next_component_name(name, existing, incoming, renames)
    return renames


def _next_component_name(
    name: str,
    existing: dict[str, dict[str, Any]],
    incoming: dict[str, dict[str, Any]],
    renames: dict[str, str],
) -> str:
    suffix = 2
    used = {*existing, *incoming, *renames.values()}
    while True:
        candidate = f"{name}{suffix}"
        if candidate not in used:
            return candidate
        suffix += 1


def _rewrite_refs(value: Any, renames: dict[str, str]) -> Any:
    if not renames:
        return value
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        obj = cast("dict[str, Any]", value)
        for key, item in obj.items():
            if key == "$ref" and isinstance(item, str):
                rewritten[key] = _rewrite_ref(item, renames)
            else:
                rewritten[key] = _rewrite_refs(item, renames)
        return rewritten
    if isinstance(value, list):
        items = cast("list[Any]", value)  # type: ignore[redundant-cast]
        return [_rewrite_refs(item, renames) for item in items]
    return value


def _rewrite_ref(ref: str, renames: dict[str, str]) -> str:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        return ref
    name = ref.removeprefix(prefix)
    renamed = renames.get(name)
    if renamed is None:
        return ref
    return f"{prefix}{renamed}"


def _synth_exc_type(exc: type[Exception]) -> Any:
    """Coerce an exception class into a tagged msgspec Struct.

    Even for dataclass-style exceptions, we build a tagged Struct rather than
    passing the dataclass through directly — the ``kind`` discriminator is what
    lets the TS side narrow ``result.error.kind === "PostNotFound"``, and the
    raw dataclass schema doesn't carry it.
    """
    return _build_exc_struct(exc)


_EXC_STRUCT_CACHE: dict[type[Exception], type[msgspec.Struct]] = {}


def _build_exc_struct(exc: type[Exception]) -> type[msgspec.Struct]:
    cached = _EXC_STRUCT_CACHE.get(exc)
    if cached is not None:
        return cached

    try:
        hints = typing.get_type_hints(exc, include_extras=False)
    except Exception:
        hints = {}
    hints.pop("return", None)

    field_defs: list[tuple[str, Any] | tuple[str, Any, Any]] = list(hints.items())
    if "request_id" not in hints:
        field_defs.append(("request_id", str | None, None))
    struct_type: type[msgspec.Struct] = msgspec.defstruct(
        exc.__name__,
        field_defs,
        tag=exc.__name__,
        tag_field="kind",
    )
    _EXC_STRUCT_CACHE[exc] = struct_type
    return struct_type


def _exc_schema(exc: type[Exception]) -> dict[str, Any]:
    """Last-resort schema for an exception that msgspec wouldn't accept."""
    props: dict[str, dict[str, Any]] = {"kind": {"const": exc.__name__, "type": "string"}}
    if hasattr(exc, "__dataclass_fields__"):
        for f in fields(exc):  # type: ignore[arg-type]
            props[f.name] = {"type": "string"}
    return {"type": "object", "title": exc.__name__, "properties": props, "required": ["kind"]}
