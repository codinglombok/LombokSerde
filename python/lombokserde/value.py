"""Value type definitions for LombokSerde."""

from typing import Any, Dict, List, Optional, Union


class DateTimeValue:
    """Represents a TOML datetime value."""
    __slots__ = ('kind', 'value')

    def __init__(self, kind: str, value: str):
        self.kind = kind  # 'offset', 'local-datetime', 'local-date', 'local-time'
        self.value = value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DateTimeValue):
            return NotImplemented
        return self.kind == other.kind and self.value == other.value

    def __repr__(self) -> str:
        return f"DateTimeValue(kind={self.kind!r}, value={self.value!r})"


# Value = None | bool | int | float | str | bytes | DateTimeValue | List[Value] | Dict[str, Value]
Value = Any


def is_datetime(v: Any) -> bool:
    return isinstance(v, DateTimeValue)


def is_map(v: Any) -> bool:
    return isinstance(v, dict)


def type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, bytes):
        return "bytes"
    if isinstance(v, bytearray):
        return "bytes"
    if isinstance(v, DateTimeValue):
        return "datetime"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "map"
    return "unknown"
