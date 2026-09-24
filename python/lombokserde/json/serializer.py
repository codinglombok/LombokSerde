"""JSON serializer."""

import math
from ..value import DateTimeValue


def to_string(value) -> str:
    """Serialize a value to compact JSON."""
    return _write_value(value)


def to_string_pretty(value, indent: str = "  ") -> str:
    """Serialize a value to pretty-printed JSON."""
    return _write_pretty(value, indent, 0)


def _write_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "null"
        s = repr(value)
        # Ensure consistent formatting
        return s
    if isinstance(value, str):
        return _write_string(value)
    if isinstance(value, (bytes, bytearray)):
        return "[" + ",".join(str(b) for b in value) + "]"
    if isinstance(value, DateTimeValue):
        return _write_string(value.value)
    if isinstance(value, list):
        return "[" + ",".join(_write_value(v) for v in value) + "]"
    if isinstance(value, dict):
        pairs = []
        for k, v in value.items():
            pairs.append(_write_string(str(k)) + ":" + _write_value(v))
        return "{" + ",".join(pairs) + "}"
    return _write_string(str(value))


def _write_pretty(value, indent: str, depth: int) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "null"
        return repr(value)
    if isinstance(value, str):
        return _write_string(value)
    if isinstance(value, (bytes, bytearray)):
        items = [str(b) for b in value]
        if not items:
            return "[]"
        inner = indent * (depth + 1)
        outer = indent * depth
        return "[\n" + ",\n".join(inner + i for i in items) + "\n" + outer + "]"
    if isinstance(value, DateTimeValue):
        return _write_string(value.value)
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = indent * (depth + 1)
        outer = indent * depth
        items = [inner + _write_pretty(v, indent, depth + 1) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + outer + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent * (depth + 1)
        outer = indent * depth
        pairs = []
        for k, v in value.items():
            pairs.append(inner + _write_string(str(k)) + ": " + _write_pretty(v, indent, depth + 1))
        return "{\n" + ",\n".join(pairs) + "\n" + outer + "}"
    return _write_string(str(value))


def _write_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\b':
            out.append('\\b')
        elif ch == '\f':
            out.append('\\f')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif ord(ch) < 0x20:
            out.append(f'\\u{ord(ch):04X}')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)
