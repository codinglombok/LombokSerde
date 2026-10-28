"""Shared vector runner + VVE helpers (mirrors rust/tests/vectors.rs)."""

from __future__ import annotations

import math
import pathlib
from typing import Any

from lombokserde import (
    DEFAULT_DEPTH_LIMIT,
    JsonOptions,
    MsgPackOptions,
    SerdeError,
    TomlOptions,
    json_decode,
    json_encode,
    msgpack_decode,
    msgpack_encode,
    table_get,
    toml_decode,
    toml_encode,
)
from lombokserde.value import table_unchecked

VECTORS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "vectors"
    / "lombokserde-vectors-v1.json"
)


_TAGS = {"null", "bool", "int", "uint", "float", "str", "bytes", "array", "table", "datetime"}


def _is_value(v: Any) -> bool:
    return (
        isinstance(v, tuple)
        and len(v) >= 1
        and isinstance(v[0], str)
        and v[0] in _TAGS
    )


def value_eq(a: Any, b: Any) -> bool:
    """Bit-identical comparison (NaN == NaN, -0 != 0)."""
    if not _is_value(a) or not _is_value(b):
        return a == b and type(a) is type(b)
    if a[0] != b[0]:
        return False
    tag = a[0]
    if tag == "null":
        return True
    if tag in ("bool", "int", "uint", "str"):
        return a[1] == b[1]
    if tag == "float":
        import struct

        return struct.pack(">d", a[1]) == struct.pack(">d", b[1])
    if tag == "bytes":
        return a[1] == b[1]
    if tag == "datetime":
        return str(a[1]) == str(b[1]) and a[2] == b[2]
    if tag == "array":
        return len(a[1]) == len(b[1]) and all(value_eq(x, y) for x, y in zip(a[1], b[1]))
    if tag == "table":
        return len(a[1]) == len(b[1]) and all(
            ka == kb and value_eq(va, vb) for (ka, va), (kb, vb) in zip(a[1], b[1])
        )
    return False


def vve_parse(v: Any) -> Any:
    """Parse the VVE (vector value encoding) into a Value."""
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, str):
        return ("str", v)
    if isinstance(v, list):
        return ("array", [vve_parse(x) for x in v])
    if isinstance(v, dict):
        if len(v) != 1:
            raise ValueError("VVE object must have exactly one key")
        tag, payload = next(iter(v.items()))
        if tag == "$i":
            return ("int", int(payload))
        if tag == "$u":
            return ("uint", int(payload))
        if tag == "$f":
            if payload == "inf":
                return ("float", math.inf)
            if payload == "-inf":
                return ("float", -math.inf)
            if payload == "nan":
                return ("float", math.nan)
            return ("float", float(payload))
        if tag == "$b":
            return ("bytes", bytes.fromhex(payload))
        if tag == "$d":
            return ("datetime", payload[0], payload[1])
        if tag == "$t":
            pairs = []
            for kv in payload:
                if not isinstance(kv, list) or len(kv) != 2:
                    raise ValueError("table entries must be [key, value] pairs")
                pairs.append((kv[0], vve_parse(kv[1])))
            return table_unchecked(pairs)
        raise ValueError(f"unknown VVE tag {tag}")
    raise ValueError(f"unexpected VVE node {v!r}")


def hex_decode(s: str) -> bytes:
    return bytes.fromhex(s)


def hex_encode(b: bytes) -> str:
    return b.hex()


def _text_input(case: dict) -> bytes:
    if "input" in case:
        return case["input"].encode("utf-8")
    if "input_hex" in case:
        return hex_decode(case["input_hex"])
    raise KeyError("case has neither input nor input_hex")


def run_case(c: dict) -> dict:
    depth = c.get("options", {}).get("depth", DEFAULT_DEPTH_LIMIT)
    fmt = c["format"]
    if c["op"] == "decode":
        raw = _text_input(c)
        if fmt == "json":
            v = json_decode(raw, JsonOptions(depth))
            enc = json_encode(v, JsonOptions(depth)).decode("utf-8")
        elif fmt == "toml":
            v = toml_decode(raw, TomlOptions(depth))
            enc = toml_encode(v, TomlOptions(depth)).decode("utf-8")
        else:
            v = msgpack_decode(raw, MsgPackOptions(depth))
            enc = msgpack_encode(v, MsgPackOptions(depth)).hex()
        return {"value": v, "encoding": enc}
    v = vve_parse(c["value"])
    if fmt == "json":
        raw = json_encode(v, JsonOptions(depth))
        return {
            "value": json_decode(raw, JsonOptions(depth)),
            "encoding": raw.decode("utf-8"),
        }
    if fmt == "toml":
        raw = toml_encode(v, TomlOptions(depth))
        return {
            "value": toml_decode(raw, TomlOptions(depth)),
            "encoding": raw.decode("utf-8"),
        }
    enc = msgpack_encode(v, MsgPackOptions(depth))
    return {
        "value": msgpack_decode(enc, MsgPackOptions(depth)),
        "encoding": enc.hex(),
    }


def check_case(c: dict) -> str | None:
    """Run one vector case; return a failure description or None."""
    ident = c["id"]
    expect = c["expect"]
    try:
        got = run_case(c)
    except SerdeError as e:
        exp_err = expect.get("error")
        if exp_err is None:
            return f"{ident}: operation failed but no error expected: {e}"
        if e.code != exp_err["code"]:
            return f"{ident}: error code mismatch: got {e.code} want {exp_err['code']}"
        want_offset = exp_err.get("offset")
        if e.offset != want_offset:
            return f"{ident}: error offset mismatch: got {e.offset} want {want_offset}"
        return None
    if expect.get("error") is not None:
        return f"{ident}: expected an error but the operation succeeded"
    if "value" in expect:
        want = vve_parse(expect["value"])
        if not value_eq(got["value"], want):
            return f"{ident}: value mismatch\n  got:  {got['value']!r}\n  want: {want!r}"
    if "encoding" in expect:
        if got["encoding"] != expect["encoding"]:
            return (
                f"{ident}: encoding mismatch\n  got:  {got['encoding']!r}\n"
                f"  want: {expect['encoding']!r}"
            )
    return None


def load_cases() -> list:
    raw = VECTORS_PATH.read_bytes()
    # dogfood: the vector file is parsed with this port's own JSON decoder
    doc = json_decode(raw, JsonOptions(DEFAULT_DEPTH_LIMIT))
    cases = table_get(doc, "cases")
    if cases is None or cases[0] != "array":
        raise ValueError("vector file has no cases array")
    out = []
    for cv in cases[1]:
        # convert the decoded Value tree into plain dicts for the harness
        out.append(_value_to_plain(cv))
    return out


def _value_to_plain(v: Any) -> Any:
    if not isinstance(v, tuple) or not v:
        return v
    tag = v[0]
    if tag == "null":
        return None
    if tag in ("bool", "int", "uint", "float", "str"):
        return v[1]
    if tag == "bytes":
        return {"$b": v[1].hex()}
    if tag == "datetime":
        return {"$d": [str(v[1]), v[2]]}
    if tag == "array":
        return [_value_to_plain(x) for x in v[1]]
    if tag == "table":
        return {k: _value_to_plain(x) for k, x in v[1]}
    raise ValueError(tag)
