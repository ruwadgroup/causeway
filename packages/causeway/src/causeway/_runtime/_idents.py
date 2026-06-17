"""Identifier transforms used by the codegen renderer."""

from __future__ import annotations


def to_camel(name: str) -> str:
    """``user_id`` → ``userId``. PascalCase / camelCase / mixed pass through untouched."""
    if "_" not in name:
        return name
    head, *rest = name.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest if p)
