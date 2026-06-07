"""``expect(...)`` assertion proxy.

``expect`` accepts a :class:`PathValue`, a :class:`Response`, a scenario
proxy (in which case its ``.last`` response is used), or any plain value.
The returned :class:`Expectation` lets users chain attribute access and
perform assertions via overloaded comparison operators.
"""

from __future__ import annotations

import collections.abc
from typing import Any

from causeway._testing.errors import ScenarioAssertionError
from causeway._testing.registry import current_registry
from causeway._testing.response import PathValue, Response, _Missing


def _is_collecting() -> bool:
    """Should ``expect`` short-circuit?

    True when we're outside any scenario, in collection mode, or in
    execute mode but the scenario currently running is not the one
    pytest is targeting.
    """
    reg = current_registry()
    if reg is None:
        return True
    if reg.mode == "collect":
        return True
    from causeway._testing.scenario import is_active_scenario

    return not is_active_scenario()


class Expectation:
    """Path-aware assertion proxy.

    Attribute / item access produce a deeper ``Expectation``; comparison
    operators fire an assertion. ``==`` against a
    :class:`~causeway._testing.snapshot.SnapshotValue` is handled
    specially so snapshot mismatches carry the source location to the
    rewriter.
    """

    __slots__ = ("_path", "_response", "_value")

    def __init__(
        self,
        value: Any,
        *,
        path: tuple[str, ...] = (),
        response: Response | None = None,
    ) -> None:
        self._value = value
        self._path = path
        self._response = response

    def __getattr__(self, name: str) -> Expectation:
        return self._step(name)

    def __getitem__(self, key: Any) -> Expectation:
        return self._step(key)

    def _step(self, key: Any) -> Expectation:
        v = self._value
        new_path = (*self._path, str(key))
        if isinstance(v, PathValue):
            return Expectation(v[key], path=new_path, response=self._response)
        if isinstance(v, _Missing):
            return Expectation(v, path=new_path, response=self._response)
        if isinstance(v, dict):
            return Expectation(
                v.get(key, _Missing(new_path)), path=new_path, response=self._response
            )
        if isinstance(v, list):
            try:
                idx = int(key)
            except (TypeError, ValueError):
                return Expectation(_Missing(new_path), path=new_path, response=self._response)
            if 0 <= idx < len(v):
                return Expectation(v[idx], path=new_path, response=self._response)
            return Expectation(_Missing(new_path), path=new_path, response=self._response)
        if isinstance(key, str) and hasattr(v, key):
            return Expectation(getattr(v, key), path=new_path, response=self._response)
        return Expectation(_Missing(new_path), path=new_path, response=self._response)

    def _resolved(self) -> Any:
        v = self._value
        if isinstance(v, PathValue):
            return v.unwrap()
        return v

    def __eq__(self, other: object) -> bool:
        from causeway._testing.snapshot import SnapshotValue

        if _is_collecting():
            return True
        actual = self._resolved()
        if isinstance(other, SnapshotValue):
            other.compare(actual, source_path=self._path)
            return True
        if isinstance(actual, _Missing):
            raise ScenarioAssertionError(
                message="expected value missing",
                path=self._path,
                expected=other,
            )
        if actual != other:
            raise ScenarioAssertionError(
                message="values differ",
                actual=actual,
                expected=other,
                path=self._path,
            )
        return True

    def __ne__(self, other: object) -> bool:
        if _is_collecting():
            return True
        actual = self._resolved()
        if isinstance(actual, _Missing):
            return True
        if actual == other:
            raise ScenarioAssertionError(
                message="values unexpectedly equal",
                actual=actual,
                expected=other,
                path=self._path,
            )
        return True

    def __lt__(self, other: Any) -> bool:
        return self._cmp(other, lambda a, b: a < b, "<")

    def __le__(self, other: Any) -> bool:
        return self._cmp(other, lambda a, b: a <= b, "<=")

    def __gt__(self, other: Any) -> bool:
        return self._cmp(other, lambda a, b: a > b, ">")

    def __ge__(self, other: Any) -> bool:
        return self._cmp(other, lambda a, b: a >= b, ">=")

    def __contains__(self, other: Any) -> bool:
        if _is_collecting():
            return True
        actual = self._resolved()
        if isinstance(actual, _Missing):
            raise ScenarioAssertionError(message="container missing", path=self._path)
        if other not in actual:
            raise ScenarioAssertionError(
                message=f"value {other!r} not in container",
                actual=actual,
                expected=other,
                path=self._path,
            )
        return True

    def _cmp(self, other: Any, op: Any, name: str) -> bool:
        if _is_collecting():
            return True
        actual = self._resolved()
        if isinstance(actual, _Missing):
            raise ScenarioAssertionError(message="value missing", path=self._path)
        if not op(actual, other):
            raise ScenarioAssertionError(
                message=f"comparison {name} failed",
                actual=actual,
                expected=other,
                path=self._path,
            )
        return True

    def is_(self, other: Any) -> bool:
        actual = self._resolved()
        if actual is not other:
            raise ScenarioAssertionError(
                message="identity check failed",
                actual=actual,
                expected=other,
                path=self._path,
            )
        return True

    def is_not(self, other: Any) -> bool:
        actual = self._resolved()
        if actual is other:
            raise ScenarioAssertionError(
                message="identity check unexpectedly held",
                actual=actual,
                expected=other,
                path=self._path,
            )
        return True

    def matches(self, predicate: collections.abc.Callable[[Any], bool]) -> bool:
        actual = self._resolved()
        if not predicate(actual):
            raise ScenarioAssertionError(
                message="predicate returned false",
                actual=actual,
                path=self._path,
            )
        return True

    def __bool__(self) -> bool:
        raise TypeError(
            "Expectation cannot be evaluated as a bool. Use an explicit comparison, "
            "`expect(...) == value`, or `.matches(predicate)`."
        )

    def __repr__(self) -> str:
        return f"Expectation({self._resolved()!r}, path={self._path!r})"


def expect(target: Any) -> Expectation:
    """Wrap a value in an :class:`Expectation` for fluent assertions.

    Special targets:

    - A scenario proxy → asserts on its most recent response.
    - A :class:`Response` → expectations start at ``.body``.
    - A :class:`PathValue` → expectations continue from there.
    """
    from causeway._testing.scenario import _It

    if isinstance(target, _It):
        resp = target.last
        if resp is None:
            if _is_collecting() or target.collecting:
                return Expectation(None)
            raise ScenarioAssertionError(message="no requests have been sent in this scenario yet")
        return Expectation(resp, response=resp)
    if isinstance(target, Response):
        return Expectation(target, response=target)
    if isinstance(target, PathValue):
        return Expectation(target, path=target.path, response=target.response)
    return Expectation(target)
