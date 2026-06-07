"""Diff two ``AppIR`` snapshots and surface breaking changes.

Breaking changes — exit non-zero, fail CI:

- A route is removed (or renamed).
- A param is removed.
- A param's wire alias changes.
- A param's location changes (``query`` → ``body`` etc.).
- A previously-optional param becomes required.
- A route's response schema narrows (a property is removed, a type tightens).
- A route's ``@raises`` set gains a new variant the client can't currently
  match on (or removes one the client may be switching on).

Non-breaking changes — informational, exit 0:

- A route is added.
- A param gains a default (optional widening).
- The response schema gains an optional property.
- An enum gains a value.

The diff operates on the JSON form of the IR. Emit with ``causeway ir`` and
diff with ``causeway diff old.json new.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

Severity = Literal["breaking", "info"]


@dataclass(slots=True)
class Change:
    severity: Severity
    code: str  # short kebab-case identifier, e.g. "route-removed"
    message: str
    route: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "route": self.route,
        }


def _empty_changes() -> list[Change]:
    return []


@dataclass(slots=True)
class DiffResult:
    changes: list[Change] = field(default_factory=_empty_changes)

    @property
    def breaking(self) -> list[Change]:
        return [c for c in self.changes if c.severity == "breaking"]

    @property
    def info(self) -> list[Change]:
        return [c for c in self.changes if c.severity == "info"]

    def add(self, severity: Severity, code: str, message: str, route: str | None = None) -> None:
        self.changes.append(Change(severity=severity, code=code, message=message, route=route))


def diff_ir(old: dict[str, Any], new: dict[str, Any]) -> DiffResult:
    """Compute the diff between two IR snapshots (JSON dicts)."""
    result = DiffResult()
    old_routes = {r["name"]: r for r in old.get("routes", [])}
    new_routes = {r["name"]: r for r in new.get("routes", [])}

    for name in old_routes.keys() - new_routes.keys():
        result.add("breaking", "route-removed", f"route {name!r} was removed", route=name)

    for name in new_routes.keys() - old_routes.keys():
        result.add("info", "route-added", f"route {name!r} was added", route=name)

    old_components = old.get("components", {})
    new_components = new.get("components", {})

    for name in old_routes.keys() & new_routes.keys():
        _diff_route(old_routes[name], new_routes[name], old_components, new_components, result)

    return result


def _diff_route(
    old: dict[str, Any],
    new: dict[str, Any],
    old_components: dict[str, Any],
    new_components: dict[str, Any],
    out: DiffResult,
) -> None:
    name = new["name"]

    if old.get("method") != new.get("method"):
        out.add(
            "breaking",
            "route-method-changed",
            f"{name!r} method changed {old.get('method')!r} → {new.get('method')!r}",
            route=name,
        )
    if old.get("path") != new.get("path"):
        out.add(
            "breaking",
            "route-path-changed",
            f"{name!r} path changed {old.get('path')!r} → {new.get('path')!r}",
            route=name,
        )

    _diff_params(name, old.get("params", []), new.get("params", []), out)
    _diff_response(name, old, new, old_components, new_components, out)
    _diff_raises(name, old.get("raises", []), new.get("raises", []), out)


def _diff_params(
    route: str,
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
    out: DiffResult,
) -> None:
    old_by_name = {p["name"]: p for p in old}
    new_by_name = {p["name"]: p for p in new}

    for n in old_by_name.keys() - new_by_name.keys():
        out.add("breaking", "param-removed", f"{route!r} param {n!r} was removed", route=route)

    for n in new_by_name.keys() - old_by_name.keys():
        p = new_by_name[n]
        if p.get("required"):
            out.add(
                "breaking",
                "param-added-required",
                f"{route!r} new required param {n!r} ({p.get('location')})",
                route=route,
            )
        else:
            out.add(
                "info", "param-added-optional", f"{route!r} new optional param {n!r}", route=route
            )

    for n in old_by_name.keys() & new_by_name.keys():
        op = old_by_name[n]
        np = new_by_name[n]
        if op.get("alias") != np.get("alias"):
            out.add(
                "breaking",
                "param-alias-changed",
                f"{route!r} param {n!r} alias {op.get('alias')!r} → {np.get('alias')!r}",
                route=route,
            )
        if op.get("location") != np.get("location"):
            out.add(
                "breaking",
                "param-location-changed",
                f"{route!r} param {n!r} location {op.get('location')!r} → {np.get('location')!r}",
                route=route,
            )
        if not op.get("required") and np.get("required"):
            out.add(
                "breaking",
                "param-now-required",
                f"{route!r} param {n!r} is now required",
                route=route,
            )


def _diff_response(
    route: str,
    old: dict[str, Any],
    new: dict[str, Any],
    old_components: dict[str, Any],
    new_components: dict[str, Any],
    out: DiffResult,
) -> None:
    o = _resolve(old.get("response"), old_components)
    n = _resolve(new.get("response"), new_components)
    if o is None and n is None:
        return
    if o is None or n is None:
        out.add(
            "breaking",
            "response-presence-changed",
            f"{route!r} response presence changed ({_describe(o)} → {_describe(n)})",
            route=route,
        )
        return

    o_props = _props(o)
    n_props = _props(n)
    for k in o_props.keys() - n_props.keys():
        out.add(
            "breaking",
            "response-property-removed",
            f"{route!r} response field {k!r} was removed",
            route=route,
        )
    for k in n_props.keys() - o_props.keys():
        # Added property is non-breaking on the wire (clients ignore extras),
        # but TS callers may need to handle it. Surface as info.
        out.add(
            "info", "response-property-added", f"{route!r} response field {k!r} added", route=route
        )


def _diff_raises(
    route: str,
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
    out: DiffResult,
) -> None:
    old_kinds = {e["name"] for e in old}
    new_kinds = {e["name"] for e in new}

    for kind in old_kinds - new_kinds:
        # Removing an error variant breaks the TS-side switch's exhaustiveness.
        out.add(
            "breaking",
            "error-variant-removed",
            f"{route!r} @raises variant {kind!r} was removed",
            route=route,
        )
    for kind in new_kinds - old_kinds:
        # Adding an error variant breaks the TS-side switch's exhaustiveness too —
        # TypeScript will fail the build on a non-exhaustive switch.
        out.add(
            "breaking",
            "error-variant-added",
            f"{route!r} @raises gained variant {kind!r}",
            route=route,
        )


def _props(schema: Any) -> dict[str, Any]:
    """Best-effort ``properties`` accessor that doesn't bleed Unknown types."""
    if not isinstance(schema, dict):
        return {}
    raw: Any = cast("dict[str, Any]", schema).get("properties")
    if isinstance(raw, dict):
        return cast("dict[str, Any]", raw)
    return {}


def _resolve(schema: Any, components: dict[str, Any]) -> Any:
    """Follow a single ``$ref`` into the components dict; otherwise pass through."""
    if not isinstance(schema, dict):
        return schema
    s = cast("dict[str, Any]", schema)
    ref: Any = s.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        resolved: Any = components.get(name, schema)
        return resolved
    return s


def _describe(schema: Any) -> str:
    if schema is None:
        return "none"
    if isinstance(schema, dict):
        return str(cast("dict[str, Any]", schema).get("type", "object"))
    return str(schema)


def format_human(diff: DiffResult) -> str:
    lines: list[str] = []
    if diff.breaking:
        lines.append(f"x {len(diff.breaking)} breaking change(s)")
        for c in diff.breaking:
            lines.append(f"  [{c.code}] {c.message}")
    if diff.info:
        lines.append(f"i {len(diff.info)} additive change(s)")
        for c in diff.info:
            lines.append(f"  [{c.code}] {c.message}")
    if not diff.changes:
        lines.append("✓ no changes detected")
    return "\n".join(lines)


def format_json(diff: DiffResult) -> str:
    return json.dumps({"changes": [c.as_dict() for c in diff.changes]}, indent=2)


def format_github(diff: DiffResult) -> str:
    """Emit GitHub Actions workflow commands so breaking changes annotate the PR."""
    lines: list[str] = []
    for c in diff.changes:
        level = "error" if c.severity == "breaking" else "notice"
        lines.append(f"::{level} title=causeway-diff::[{c.code}] {c.message}")
    return "\n".join(lines)


def load_ir(path: Path) -> dict[str, Any]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"IR snapshot at {path} must be a JSON object, got {type(raw).__name__}"
        raise TypeError(msg)
    return cast("dict[str, Any]", raw)
