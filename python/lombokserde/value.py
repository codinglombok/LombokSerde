"""The canonical value model shared by all formats and all ports (SPEC)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_DEPTH_LIMIT = 128

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
UINT64_MAX = 2**64 - 1


class DatetimeKind(str):
    """Datetime kind tag; a plain string ('offset', 'localdt', 'date', 'time')."""


OFFSET = DatetimeKind("offset")
LOCAL_DATETIME = DatetimeKind("localdt")
LOCAL_DATE = DatetimeKind("date")
LOCAL_TIME = DatetimeKind("time")


@dataclass(frozen=True)
class Datetime:
    """Convenience constructor payload: ``("datetime", kind, raw)``."""

    kind: DatetimeKind
    raw: str

    def to_value(self) -> tuple[Any, ...]:
        return ("datetime", DatetimeKind(self.kind), self.raw)


# Tagged tuples keep the model exact and cross-language faithful:
# ("null",) ("bool", b) ("int", i) ("uint", u) ("float", f) ("str", s)
# ("bytes", b) ("array", [v...]) ("table", [(k, v)...]) ("datetime", dt)
Value = Any  # tagged tuple: ("null",) | ("bool", b) | ... (see module docstring)

TablePair = tuple[str, Any]


def _bytewise_key(k: str) -> bytes:
    return k.encode("utf-8")


def make_table(
    pairs: Iterable[tuple[str, Any]], dup_error: Callable[[], Exception]
) -> Any:
    """Build a table: sorted bytewise by key, duplicates are an error."""
    out: list[TablePair] = []
    for k, v in sorted(pairs, key=lambda kv: _bytewise_key(kv[0])):
        if out and out[-1][0] == k:
            raise dup_error()
        out.append((k, v))
    return ("table", out)


def table_unchecked(pairs: Iterable[TablePair]) -> Any:
    """Build a table from pairs known to be duplicate-free."""
    return ("table", sorted(pairs, key=lambda kv: _bytewise_key(kv[0])))


def table_get(v: Any, key: str) -> Any | None:
    """Look up a key in a table value (binary search, bytewise order)."""
    if not (isinstance(v, tuple) and v and v[0] == "table"):
        return None
    pairs = v[1]
    kb = key.encode("utf-8")
    lo, hi = 0, len(pairs)
    while lo < hi:
        mid = (lo + hi) // 2
        c = _cmp(pairs[mid][0].encode("utf-8"), kb)
        if c == 0:
            return pairs[mid][1]
        if c < 0:
            lo = mid + 1
        else:
            hi = mid
    return None


def _cmp(a: bytes, b: bytes) -> int:
    return (a > b) - (a < b)
