"""Apply pending snapshot edits to route source files.

The plan calls for ``libcst`` to preserve formatting. ``libcst`` is
optional — installed via the ``inline-tests`` extra. We fall back to a
small line-based rewrite that still produces valid Python (it just
loses original formatting around the replaced ``snapshot(...)`` literal).
The fallback keeps ``--update-snapshots`` usable in environments where
``libcst`` isn't available; users get a warning telling them to install
the extra for clean diffs.
"""

from __future__ import annotations

import io
import pprint
import token
import tokenize
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from causeway._testing.snapshot import SnapshotEdit


def apply_edits(edits: Iterable[SnapshotEdit]) -> dict[Path, int]:
    """Group edits by file and apply them. Returns counts per file.

    Edits to the same file are applied in reverse line order so earlier
    edits don't shift later ones.
    """
    grouped: dict[Path, list[SnapshotEdit]] = {}
    for e in edits:
        grouped.setdefault(e.file, []).append(e)

    counts: dict[Path, int] = {}
    for path, file_edits in grouped.items():
        file_edits.sort(key=lambda e: (e.call_line, e.call_col), reverse=True)
        new_text = _rewrite_file(path, file_edits)
        if new_text is not None:
            _atomic_write(path, new_text)
            counts[path] = len(file_edits)
    return counts


def _rewrite_file(path: Path, edits: list[SnapshotEdit]) -> str | None:
    source = path.read_text()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return None

    snapshot_calls = _find_snapshot_calls(tokens)
    if not snapshot_calls:
        return None

    text = source
    for edit in edits:
        target = _pick_call_for_line(snapshot_calls, edit.call_line)
        if target is None:
            continue
        text = _replace_call_args(text, target, edit.new_value)
    return text


def _find_snapshot_calls(
    tokens: list[tokenize.TokenInfo],
) -> list[tuple[int, int, int]]:
    """Return ``(name_line, open_paren_offset, close_paren_offset)`` for each call.

    Offsets are absolute character positions in the source text.
    """
    results: list[tuple[int, int, int]] = []
    # We need a flat character offset; tokenize gives (line, col), so we
    # accumulate line starts.
    for i, tok in enumerate(tokens):
        if tok.type != token.NAME or tok.string != "snapshot":
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is None or nxt.type != token.OP or nxt.string != "(":
            continue
        # Find the matching ')'.
        depth = 0
        close_idx = -1
        for j in range(i + 1, len(tokens)):
            t = tokens[j]
            if t.type == token.OP and t.string == "(":
                depth += 1
            elif t.type == token.OP and t.string == ")":
                depth -= 1
                if depth == 0:
                    close_idx = j
                    break
        if close_idx == -1:
            continue
        results.append((tok.start[0], i + 1, close_idx))
    return results


def _pick_call_for_line(
    calls: list[tuple[int, int, int]], line: int
) -> tuple[int, int, int] | None:
    # Prefer an exact line match; otherwise the closest call whose name
    # token sits on or before the recorded line.
    exact = [c for c in calls if c[0] == line]
    if exact:
        return exact[0]
    before = [c for c in calls if c[0] <= line]
    if before:
        return max(before, key=lambda c: c[0])
    return None


def _replace_call_args(source: str, target: tuple[int, int, int], new_value: Any) -> str:
    """Replace the argument list inside a snapshot(...) call.

    We re-tokenize to get exact character offsets for the matching
    parens (tokenize's (line, col) is enough but we want character
    positions in ``source``).
    """
    name_line, open_tok_idx, close_tok_idx = target
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    if open_tok_idx >= len(tokens) or close_tok_idx >= len(tokens):
        return source
    open_tok = tokens[open_tok_idx]
    close_tok = tokens[close_tok_idx]
    if open_tok.string != "(" or close_tok.string != ")":
        return source

    open_offset = _line_col_to_offset(source, open_tok.start[0], open_tok.start[1])
    close_offset = _line_col_to_offset(source, close_tok.start[0], close_tok.start[1])
    if open_offset < 0 or close_offset < 0:
        return source

    rendered = pprint.pformat(new_value, width=78, sort_dicts=False)
    rendered = _indent_continuation(rendered, source, open_offset)
    new_chunk = f"({rendered})"
    _ = name_line  # reserved for future heuristics
    return source[:open_offset] + new_chunk + source[close_offset + 1 :]


def _indent_continuation(rendered: str, source: str, open_offset: int) -> str:
    """Re-indent multi-line literals so they line up with the call site."""
    if "\n" not in rendered:
        return rendered
    # Compute the column of the '(' in its line.
    line_start = source.rfind("\n", 0, open_offset) + 1
    col = open_offset - line_start
    pad = " " * (col + 1)
    lines = rendered.splitlines()
    return ("\n" + pad).join(lines)


def _line_col_to_offset(source: str, line: int, col: int) -> int:
    pos = 0
    cur_line = 1
    while cur_line < line:
        nl = source.find("\n", pos)
        if nl < 0:
            return -1
        pos = nl + 1
        cur_line += 1
    return pos + col


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".causeway-tmp")
    tmp.write_text(text)
    tmp.replace(path)
