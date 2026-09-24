"""TOML serializer — outputs normalized TOML v1.0."""

import math
from ..value import DateTimeValue


def stringify(value: dict) -> str:
    """Serialize a dict to a TOML string."""
    return _write_table(value, [])


def _write_table(m: dict, path: list) -> str:
    out = []

    # Simple key-value pairs first
    for key, value in m.items():
        if not _is_table_or_array_of_tables(value):
            out.append(f"{_write_key(key)} = {_write_value(value)}\n")

    # Sub-tables
    for key, value in m.items():
        if isinstance(value, dict) and not isinstance(value, DateTimeValue.__class__) and not _is_inline_table(value):
            new_path = path + [key]
            out.append(f"\n[{'.'.join(_write_key(k) for k in new_path)}]\n")
            out.append(_write_table(value, new_path))
        elif isinstance(value, list) and _is_array_of_tables(value):
            new_path = path + [key]
            for item in value:
                if isinstance(item, dict):
                    out.append(f"\n[[{'.'.join(_write_key(k) for k in new_path)}]]\n")
                    out.append(_write_table(item, new_path))

    return ''.join(out)


def _is_table_or_array_of_tables(value) -> bool:
    if isinstance(value, dict) and not _is_inline_table(value):
        return True
    if isinstance(value, list) and _is_array_of_tables(value):
        return True
    return False


def _is_inline_table(m: dict) -> bool:
    if len(m) > 4:
        return False
    return all(
        v is None or isinstance(v, (bool, int, float, str, bytes, bytearray, DateTimeValue))
        for v in m.values()
    )


def _is_array_of_tables(arr: list) -> bool:
    return len(arr) > 0 and all(isinstance(v, dict) for v in arr)


def _write_key(key: str) -> str:
    if _is_bare_key(key):
        return key
    return _write_basic_string(key)


def _is_bare_key(key: str) -> bool:
    return len(key) > 0 and all(c.isalnum() or c in ('_', '-') for c in key)


def _write_value(value) -> str:
    if value is None:
        return '"null"'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return 'nan'
        if math.isinf(value):
            return '-inf' if value < 0 else 'inf'
        s = str(value)
        if '.' not in s and 'e' not in s and 'E' not in s:
            return s + '.0'
        return s
    if isinstance(value, str):
        return _write_basic_string(value)
    if isinstance(value, (bytes, bytearray)):
        return '[' + ', '.join(str(b) for b in value) + ']'
    if isinstance(value, DateTimeValue):
        return value.value
    if isinstance(value, list):
        return '[' + ', '.join(_write_value(v) for v in value) + ']'
    if isinstance(value, dict):
        # Inline table
        entries = list(value.items())
        return '{' + ', '.join(f"{_write_key(k)} = {_write_value(v)}" for k, v in entries) + '}'
    return _write_basic_string(str(value))


def _write_basic_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\b':
            out.append('\\b')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\f':
            out.append('\\f')
        elif ch == '\r':
            out.append('\\r')
        elif ord(ch) < 0x20:
            out.append(f'\\u{ord(ch):04X}')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)
