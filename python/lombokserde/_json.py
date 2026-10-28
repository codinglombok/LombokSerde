"""JSON codec (RFC 8259) — canonical, byte-precise (see SPEC)."""

from __future__ import annotations

from typing import Any

from ._float import render_float
from .error import SerdeError, syntax_err
from .value import INT64_MAX, INT64_MIN, UINT64_MAX, make_table

E_SYNTAX = "SERDE_JSON_SYNTAX"
E_UTF8 = "SERDE_JSON_UTF8"
E_DEPTH = "SERDE_JSON_DEPTH"
E_TRAILING = "SERDE_JSON_TRAILING"
E_INT_RANGE = "SERDE_JSON_INT_RANGE"
E_FLOAT_NANINF = "SERDE_JSON_FLOAT_NANINF"
E_BYTES = "SERDE_JSON_BYTES"
E_DATETIME = "SERDE_JSON_DATETIME"

JSON_WS = (0x20, 0x09, 0x0A, 0x0D)


class JsonOptions:
    """Options for the JSON codec."""

    def __init__(self, depth_limit: int = 128) -> None:
        self.depth_limit = depth_limit


def _err(offset: int, detail: str) -> SerdeError:
    return syntax_err(E_SYNTAX, offset, detail)


def json_decode(data: bytes, opts: JsonOptions | None = None) -> Any:
    """Decode exactly one JSON value; trailing non-whitespace is an error."""
    limit = opts.depth_limit if opts else 128
    bad = _utf8_first_bad_offset(data)
    if bad != -1:
        raise syntax_err(E_UTF8, bad, "invalid UTF-8")
    p = _Parser(data, limit)
    v = p.parse_value(1)
    p.skip_ws()
    if p.i != len(data):
        raise syntax_err(
            E_TRAILING, p.i, "trailing characters after the top-level value"
        )
    return v


def json_encode(v: Any, opts: JsonOptions | None = None) -> bytes:
    """Encode a value as canonical compact JSON (UTF-8 bytes)."""
    limit = opts.depth_limit if opts else 128
    out: list[str] = []
    _write(v, out, 1, limit)
    return "".join(out).encode("utf-8")


def _utf8_first_bad_offset(b: bytes) -> int:
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if c < 0x80:
            i += 1
            continue
        if 0xC2 <= c <= 0xDF:
            ln, lo, hi = 2, 0x80, 0xBF
        elif c == 0xE0:
            ln, lo, hi = 3, 0xA0, 0xBF
        elif 0xE1 <= c <= 0xEC:
            ln, lo, hi = 3, 0x80, 0xBF
        elif c == 0xED:
            ln, lo, hi = 3, 0x80, 0x9F
        elif 0xEE <= c <= 0xEF:
            ln, lo, hi = 3, 0x80, 0xBF
        elif c == 0xF0:
            ln, lo, hi = 4, 0x90, 0xBF
        elif 0xF1 <= c <= 0xF3:
            ln, lo, hi = 4, 0x80, 0xBF
        elif c == 0xF4:
            ln, lo, hi = 4, 0x80, 0x8F
        else:
            return i
        if i + ln > n:
            return i
        for j in range(1, ln):
            cc = b[i + j]
            l2 = lo if j == 1 else 0x80
            h2 = hi if j == 1 else 0xBF
            if cc < l2 or cc > h2:
                return i
        i += ln
    return -1


class _Parser:
    def __init__(self, b: bytes, limit: int) -> None:
        self.b = b
        self.i = 0
        self.limit = limit

    def skip_ws(self) -> None:
        while self.i < len(self.b) and self.b[self.i] in JSON_WS:
            self.i += 1

    def fail(self, detail: str) -> SerdeError:
        return _err(self.i, detail)

    def parse_value(self, depth: int) -> Any:
        self.skip_ws()
        if self.i >= len(self.b):
            raise self.fail("unexpected end of input")
        c = self.b[self.i]
        if c == 0x7B:
            if depth > self.limit:
                raise syntax_err(E_DEPTH, self.i, "depth limit exceeded") from None
            return self.parse_object(depth)
        if c == 0x5B:
            if depth > self.limit:
                raise syntax_err(E_DEPTH, self.i, "depth limit exceeded") from None
            return self.parse_array(depth)
        if c == 0x22:
            return ("str", self.parse_string())
        if c == 0x74:
            self.expect("true")
            return ("bool", True)
        if c == 0x66:
            self.expect("false")
            return ("bool", False)
        if c == 0x6E:
            self.expect("null")
            return ("null",)
        if c == 0x2D or 0x30 <= c <= 0x39:
            return self.parse_number()
        raise self.fail("unexpected character")

    def expect(self, word: str) -> None:
        w = word.encode()
        if self.b[self.i : self.i + len(w)] != w:
            raise self.fail("invalid literal") from None
        self.i += len(w)

    def parse_object(self, depth: int) -> Any:
        self.i += 1  # {
        pairs: list[tuple[str, Any]] = []
        self.skip_ws()
        if self.i < len(self.b) and self.b[self.i] == 0x7D:
            self.i += 1
            return make_table(pairs, lambda: _err(self.i, "duplicate object key"))
        while True:
            self.skip_ws()
            if self.i >= len(self.b) or self.b[self.i] != 0x22:
                raise self.fail("expected object key")
            k = self.parse_string()
            self.skip_ws()
            if self.i >= len(self.b) or self.b[self.i] != 0x3A:
                raise self.fail("expected ':'") from None
            self.i += 1
            v = self.parse_value(depth + 1)
            pairs.append((k, v))
            self.skip_ws()
            if self.i >= len(self.b):
                raise self.fail("unterminated object")
            c = self.b[self.i]
            if c == 0x2C:
                self.i += 1
                continue
            if c == 0x7D:
                self.i += 1
                try:
                    return make_table(
                        pairs, lambda: _err(self.i, "duplicate object key")
                    )
                except SerdeError:
                    raise
            raise self.fail("expected ',' or '}'")

    def parse_array(self, depth: int) -> Any:
        self.i += 1  # [
        items: list[Any] = []
        self.skip_ws()
        if self.i < len(self.b) and self.b[self.i] == 0x5D:
            self.i += 1
            return ("array", items)
        while True:
            items.append(self.parse_value(depth + 1))
            self.skip_ws()
            if self.i >= len(self.b):
                raise self.fail("unterminated array")
            c = self.b[self.i]
            if c == 0x2C:
                self.i += 1
                continue
            if c == 0x5D:
                self.i += 1
                return ("array", items)
            raise self.fail("expected ',' or ']'")

    def parse_string(self) -> str:
        self.i += 1  # opening quote
        out: list[str] = []
        b = self.b
        while True:
            if self.i >= len(b):
                raise self.fail("unterminated string")
            c = b[self.i]
            if c == 0x22:
                self.i += 1
                return "".join(out)
            if c == 0x5C:
                self.i += 1
                if self.i >= len(b):
                    raise self.fail("unterminated escape")
                e = b[self.i]
                simple = {
                    0x22: '"',
                    0x5C: "\\",
                    0x2F: "/",
                    0x62: "\b",
                    0x66: "\f",
                    0x6E: "\n",
                    0x72: "\r",
                    0x74: "\t",
                }
                if e in simple:
                    out.append(simple[e])
                    self.i += 1
                    continue
                if e == 0x75:
                    cp = self.parse_hex4()
                    if 0xD800 <= cp <= 0xDBFF:
                        # after parse_hex4 the cursor sits on the next char:
                        # a trailing pair escape starts here
                        if self.i + 1 < len(b) and b[self.i] == 0x5C and b[self.i + 1] == 0x75:
                            self.i += 1  # land on the 'u' of the low escape
                            lo = self.parse_hex4()
                            if 0xDC00 <= lo <= 0xDFFF:
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                            else:
                                raise self.fail("invalid low surrogate")
                        else:
                            raise self.fail("lone high surrogate")
                    elif 0xDC00 <= cp <= 0xDFFF:
                        raise self.fail("lone low surrogate")
                    out.append(chr(cp))
                    continue
                raise self.fail("invalid escape")
            if c < 0x20:
                raise self.fail("raw control character in string")
            if c < 0x80:
                out.append(chr(c))
                self.i += 1
            else:
                n = 2 if c < 0xE0 else 3 if c < 0xF0 else 4
                out.append(b[self.i : self.i + n].decode("utf-8"))
                self.i += n

    def parse_hex4(self) -> int:
        if self.i >= len(self.b) or self.b[self.i] != 0x75:
            raise self.fail("expected \\u")
        if self.i + 4 >= len(self.b):
            raise self.fail("truncated \\u escape")
        h = self.b[self.i + 1 : self.i + 5]
        try:
            cp = int(h.decode("ascii"), 16)
        except (UnicodeDecodeError, ValueError):
            raise self.fail("invalid \\u escape") from None
        self.i += 5
        return cp

    def parse_number(self) -> Any:
        s = self.i
        b = self.b
        if b[self.i] == 0x2D:
            self.i += 1
            if self.i >= len(b):
                raise self.fail("unexpected end of input")
        if b[self.i] == 0x30:
            self.i += 1
        elif 0x31 <= b[self.i] <= 0x39:
            while self.i < len(b) and 0x30 <= b[self.i] <= 0x39:
                self.i += 1
        else:
            raise self.fail("invalid number")
        is_float = False
        if self.i < len(b) and b[self.i] == 0x2E:
            is_float = True
            self.i += 1
            if self.i >= len(b) or not (0x30 <= b[self.i] <= 0x39):
                raise self.fail("expected digit after '.'")
            while self.i < len(b) and 0x30 <= b[self.i] <= 0x39:
                self.i += 1
        if self.i < len(b) and b[self.i] in (0x65, 0x45):
            is_float = True
            self.i += 1
            if self.i < len(b) and b[self.i] in (0x2B, 0x2D):
                self.i += 1
            if self.i >= len(b) or not (0x30 <= b[self.i] <= 0x39):
                raise self.fail("expected digit in exponent")
            while self.i < len(b) and 0x30 <= b[self.i] <= 0x39:
                self.i += 1
        text = b[s : self.i].decode("ascii")
        if not is_float:
            n = int(text)
            if INT64_MIN <= n <= INT64_MAX:
                return ("int", n)
            if 0 <= n <= UINT64_MAX:
                return ("uint", n)
            raise syntax_err(E_INT_RANGE, s, "integer out of 64-bit range") from None
        return ("float", float(text))


_ESCAPES = {
    0x22: '\\"',
    0x5C: "\\\\",
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
}


def _write(v: Any, out: list[str], depth: int, limit: int) -> None:
    tag = v[0]
    if tag == "null":
        out.append("null")
    elif tag == "bool":
        out.append("true" if v[1] else "false")
    elif tag in ("int", "uint"):
        out.append(str(v[1]))
    elif tag == "float":
        f = v[1]
        if f != f or f in (float("inf"), float("-inf")):
            raise SerdeError(
                E_FLOAT_NANINF, "non-finite float is not valid JSON", None
            )
        out.append(render_float(f))
    elif tag == "str":
        out.append(_quote(v[1]))
    elif tag == "bytes":
        raise SerdeError(E_BYTES, "Bytes values cannot be encoded as JSON", None)
    elif tag == "datetime":
        raise SerdeError(
            E_DATETIME, "Datetime values cannot be encoded as JSON", None
        )
    elif tag == "array":
        if depth > limit:
            raise SerdeError(E_DEPTH, "depth limit exceeded", None)
        out.append("[")
        for i, x in enumerate(v[1]):
            if i:
                out.append(",")
            _write(x, out, depth + 1, limit)
        out.append("]")
    elif tag == "table":
        if depth > limit:
            raise SerdeError(E_DEPTH, "depth limit exceeded", None)
        out.append("{")
        for i, (k, x) in enumerate(v[1]):
            if i:
                out.append(",")
            out.append(_quote(k))
            out.append(":")
            _write(x, out, depth + 1, limit)
        out.append("}")
    else:  # pragma: no cover - defensive
        raise ValueError(tag)


def _quote(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if o in _ESCAPES:
            out.append(_ESCAPES[o])
        elif o < 0x20:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)
