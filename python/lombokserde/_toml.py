"""TOML v1.0 codec — canonical, byte-precise (see SPEC)."""

from __future__ import annotations

import math
from typing import Any

from ._float import render_float
from .error import SerdeError, syntax_err
from .value import INT64_MAX, INT64_MIN, DatetimeKind, make_table

E_SYNTAX = "SERDE_TOML_SYNTAX"
E_UTF8 = "SERDE_TOML_UTF8"
E_DUPLICATE = "SERDE_TOML_DUPLICATE"
E_DEPTH = "SERDE_TOML_DEPTH"
E_ROOT = "SERDE_TOML_ROOT"
E_BYTES = "SERDE_TOML_BYTES"
E_DATETIME = "SERDE_TOML_DATETIME"

BARE_KEY = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)
DIGITS = set("0123456789")


class TomlOptions:
    """Options for the TOML codec."""

    def __init__(self, depth_limit: int = 128) -> None:
        self.depth_limit = depth_limit


def _err(offset: int, detail: str) -> SerdeError:
    return syntax_err(E_SYNTAX, offset, detail)


def toml_decode(data: bytes, opts: TomlOptions | None = None) -> Any:
    """Decode a TOML document into a table value."""
    limit = opts.depth_limit if opts else 128
    bad = _utf8_first_bad_offset(data)
    if bad != -1:
        raise syntax_err(E_UTF8, bad, "invalid UTF-8")
    p = _TomlParser(data, limit)
    return p.parse()


def toml_encode(v: Any, opts: TomlOptions | None = None) -> bytes:
    """Encode a table value as canonical TOML. The root must be a table."""
    limit = opts.depth_limit if opts else 128
    out: list[str] = []
    if not (isinstance(v, tuple) and v and v[0] == "table"):
        raise SerdeError(E_ROOT, "TOML documents encode from a table root", None)
    _emit_table(v, (), out, 1, limit)
    return "".join(out).encode("utf-8")


def _utf8_first_bad_offset(b: bytes) -> int:
    from ._json import _utf8_first_bad_offset as f

    return f(b)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# node states: 'implicit' | 'explicit' | 'dotted' | 'aot'


class _TomlParser:
    def __init__(self, b: bytes, limit: int) -> None:
        self.b = b
        self.i = 0
        self.limit = limit
        self.root: dict[tuple[Any, ...], dict[str, Any]] = {
            (): {"state": "explicit", "pairs": {}, "elems": None}
        }
        self.cur: tuple[Any, ...] = ()

    def fail(self, detail: str = "syntax error") -> SerdeError:
        return _err(self.i, detail)

    def dup(self) -> SerdeError:
        return syntax_err(E_DUPLICATE, self.i, "duplicate key or table definition")

    def peek(self) -> int | None:
        return self.b[self.i] if self.i < len(self.b) else None

    def skip_inline_ws(self) -> None:
        while self.i < len(self.b) and self.b[self.i] in (0x20, 0x09):
            self.i += 1

    def skip_comment(self) -> None:
        if self.i < len(self.b) and self.b[self.i] == 0x23:
            while self.i < len(self.b) and self.b[self.i] not in (0x0A, 0x0D):
                self.i += 1

    def expect_line_end(self) -> None:
        self.skip_inline_ws()
        self.skip_comment()
        if self.i >= len(self.b):
            return
        c = self.b[self.i]
        if c == 0x0A:
            self.i += 1
        elif c == 0x0D:
            self.i += 1
            if self.i < len(self.b) and self.b[self.i] == 0x0A:
                self.i += 1
        else:
            raise self.fail("expected end of line")

    def parse(self) -> Any:
        while True:
            self.skip_inline_ws()
            if self.i >= len(self.b):
                break
            c = self.b[self.i]
            if c == 0x0A:
                self.i += 1
                continue
            if c == 0x0D:
                self.i += 1
                if self.i < len(self.b) and self.b[self.i] == 0x0A:
                    self.i += 1
                continue
            if c == 0x23:
                self.skip_comment()
                continue
            if c == 0x5B:
                if self.i + 1 < len(self.b) and self.b[self.i + 1] == 0x5B:
                    self.parse_aot_header()
                else:
                    self.parse_table_header()
            else:
                self.parse_keyval()
            self.expect_line_end()
        return self.to_value((), 1)

    # --- headers -----------------------------------------------------------

    def parse_table_header(self) -> None:
        start = self.i
        self.i += 1  # [
        path = self.parse_key_path()
        self.skip_inline_ws()
        if self.peek() != 0x5D:
            raise self.fail("expected ']'") from None
        self.i += 1
        if len(path) + 1 > self.limit:
            raise syntax_err(E_DEPTH, start, "depth limit exceeded")
        self.define_table(path)
        self.cur = path

    def parse_aot_header(self) -> None:
        start = self.i
        self.i += 2  # [[
        path = self.parse_key_path()
        self.skip_inline_ws()
        if self.peek() != 0x5D or self.i + 1 >= len(self.b) or self.b[self.i + 1] != 0x5D:
            raise self.fail("expected ']]'") from None
        self.i += 2
        if len(path) + 1 > self.limit:
            raise syntax_err(E_DEPTH, start, "depth limit exceeded")
        self.define_aot(path)
        self.cur = path

    def resolve(self, path: tuple[Any, ...]) -> tuple[Any, ...]:
        """Expand aot segments into their last-element pseudo-paths (#n)."""
        out: list[str] = []
        for seg in path:
            node = self.root.get(tuple(out))
            if node is not None and node["state"] == "aot":
                out.append("#" + str(len(node["elems"]) - 1))
            out.append(seg)
        return tuple(out)

    @staticmethod
    def is_pseudo(seg: str) -> bool:
        return isinstance(seg, str) and seg.startswith("#")

    def define_table(self, path: tuple[Any, ...]) -> None:
        concrete = self.resolve(path)
        for j in range(1, len(concrete) + 1):
            if self.is_pseudo(concrete[j - 1]):
                continue
            sp = concrete[:j]
            node = self.root.get(sp)
            if node is None:
                self.root[sp] = {"state": "implicit", "pairs": {}, "elems": None}
            elif node["state"] == "dotted":
                raise syntax_err(
                    E_DUPLICATE, self.i, "dotted-key table redefined by header"
                )
        target = self.root.get(concrete)
        if target is None:
            self.root[concrete] = {"state": "explicit", "pairs": {}, "elems": None}
        elif target["state"] == "implicit":
            target["state"] = "explicit"
        else:
            raise self.dup()

    def define_aot(self, path: tuple[Any, ...]) -> None:
        concrete = self.resolve(path)
        for j in range(1, len(concrete) + 1):
            if self.is_pseudo(concrete[j - 1]):
                continue
            sp = concrete[:j]
            node = self.root.get(sp)
            if node is None:
                self.root[sp] = {"state": "implicit", "pairs": {}, "elems": None}
            elif node["state"] == "dotted":
                raise syntax_err(
                    E_DUPLICATE, self.i, "dotted-key table redefined by header"
                )
        target = self.root.get(concrete)
        if target is not None and target["state"] == "aot":
            target["elems"].append({"pairs": {}})
        elif target is not None and target["state"] == "implicit":
            target["state"] = "aot"
            target["elems"] = [{"pairs": {}}]
        else:
            raise self.dup()

    # --- keys ---------------------------------------------------------------

    def parse_key_path(self) -> tuple[Any, ...]:
        keys: list[str] = []
        self.skip_inline_ws()
        while True:
            keys.append(self.parse_single_key())
            self.skip_inline_ws()
            if self.peek() == 0x2E:
                self.i += 1
                self.skip_inline_ws()
                continue
            break
        return tuple(keys)

    def parse_single_key(self) -> str:
        c = self.peek()
        if c is None:
            raise self.fail("expected key")
        if c == 0x22:
            k = self.parse_basic_string()
            self._check_reserved(k)
            return k
        if c == 0x27:
            k = self.parse_literal_string()
            self._check_reserved(k)
            return k
        s = self.i
        while self.i < len(self.b) and chr(self.b[self.i]) in BARE_KEY:
            self.i += 1
        if self.i == s:
            raise self.fail("invalid key") from None
        return self.b[s : self.i].decode("utf-8")

    def _check_reserved(self, key: str) -> None:
        if key.startswith("#"):
            raise _err(self.i, "keys starting with '#' are reserved")

    # --- keyval ---------------------------------------------------------------

    def parse_keyval(self) -> None:
        keys = self.parse_key_path()
        self.skip_inline_ws()
        if self.peek() != 0x3D:
            raise self.fail("expected '='") from None
        self.i += 1
        self.skip_inline_ws()
        v = self.parse_value(len(self.cur) + len(keys) + 1)
        base = self.resolve(self.cur)
        inter = keys[:-1]
        base_node = self.root.get(base)
        if inter and base_node is not None and base_node["state"] == "aot":
            raise self.fail("dotted keys cannot extend array-of-tables elements")
        for j in range(1, len(inter) + 1):
            sp = base + inter[:j]
            node = self.root.get(sp)
            if node is None:
                self.root[sp] = {"state": "dotted", "pairs": {}, "elems": None}
            elif node["state"] == "explicit":
                raise syntax_err(
                    E_DUPLICATE,
                    self.i,
                    "dotted key extends a header-defined table",
                )
            elif node["state"] == "aot":
                raise self.fail("dotted keys cannot extend array-of-tables elements")
        parent_path = base + inter
        last = keys[-1]
        leaf = parent_path + (last,)
        if leaf in self.root:
            raise self.dup()
        parent = self.root.get(parent_path)
        if parent is not None and parent["state"] == "aot":
            target_pairs = parent["elems"][-1]["pairs"]
        else:
            if parent is None:
                parent = {"state": "dotted", "pairs": {}, "elems": None}
                self.root[parent_path] = parent
            target_pairs = parent["pairs"]
        if last in target_pairs:
            raise self.dup()
        target_pairs[last] = ("value", v)

    # --- values ---------------------------------------------------------------

    def parse_value(self, depth: int) -> Any:
        if depth > self.limit:
            raise syntax_err(E_DEPTH, self.i, "depth limit exceeded")
        c = self.peek()
        if c is None:
            raise self.fail("expected value")
        if c == 0x22:
            if self.b[self.i : self.i + 3] == b'"""':
                return ("str", self.parse_ml_basic())
            return ("str", self.parse_basic_string())
        if c == 0x27:
            if self.b[self.i : self.i + 3] == b"'''":
                return ("str", self.parse_ml_literal())
            return ("str", self.parse_literal_string())
        if c == 0x5B:
            return self.parse_array(depth)
        if c == 0x7B:
            return self.parse_inline_table(depth)
        if self.b[self.i : self.i + 4] == b"true":
            self.i += 4
            return ("bool", True)
        if self.b[self.i : self.i + 5] == b"false":
            self.i += 5
            return ("bool", False)
        return self.parse_number_or_datetime()

    def parse_array(self, depth: int) -> Any:
        self.i += 1  # [
        items: list[Any] = []
        while True:
            self.skip_array_ws()
            if self.i >= len(self.b):
                raise self.fail("unterminated array")
            if self.b[self.i] == 0x5D:
                self.i += 1
                return ("array", items)
            items.append(self.parse_value(depth + 1))
            self.skip_array_ws()
            if self.i < len(self.b) and self.b[self.i] == 0x2C:
                self.i += 1
                continue
            if self.i < len(self.b) and self.b[self.i] == 0x5D:
                self.i += 1
                return ("array", items)
            raise self.fail("expected ',' or ']'")

    def skip_array_ws(self) -> None:
        while self.i < len(self.b):
            c = self.b[self.i]
            if c in (0x20, 0x09, 0x0A, 0x0D):
                self.i += 1
            elif c == 0x23:
                while self.i < len(self.b) and self.b[self.i] not in (0x0A, 0x0D):
                    self.i += 1
            else:
                break

    def parse_inline_table(self, depth: int) -> Any:
        self.i += 1  # {
        pairs: list[tuple[str, Any]] = []
        self.skip_inline_ws()
        if self.peek() == 0x7D:
            self.i += 1
            return make_table(pairs, lambda: _err(self.i, "duplicate key in inline table"))
        while True:
            self.skip_inline_ws()
            keys = self.parse_key_path()
            self.skip_inline_ws()
            if self.peek() != 0x3D:
                raise self.fail("expected '='") from None
            self.i += 1
            self.skip_inline_ws()
            v = self.parse_value(depth + 1)
            if len(keys) > 1:
                pairs.append((keys[0], self.nest_dotted(keys[1:], v)))
            else:
                pairs.append((keys[0], v))
            self.skip_inline_ws()
            if self.peek() == 0x2C:
                self.i += 1
                continue
            if self.peek() == 0x7D:
                self.i += 1
                return make_table(
                    pairs, lambda: _err(self.i - 1, "duplicate key in inline table")
                )
            raise self.fail("expected ',' or '}' in inline table")

    def nest_dotted(self, keys: tuple[Any, ...], v: Any) -> Any:
        inner = v
        for k in reversed(keys):
            inner = make_table([(k, inner)], lambda: _err(0, "duplicate"))
        return inner

    def parse_basic_string(self) -> str:
        self.i += 1
        out: list[str] = []
        b = self.b
        while True:
            if self.i >= len(b):
                raise self.fail("unterminated string")
            c = b[self.i]
            if c == 0x22:
                self.i += 1
                return "".join(out)
            if c == 0x0A or c == 0x0D:
                raise self.fail("newline in basic string")
            if c == 0x5C:
                self.i += 1
                self.parse_escape_into(out)
                continue
            if c < 0x20 and c != 0x09:
                raise self.fail("raw control character in string")
            out.append(self.take_utf8_char())

    def parse_escape_into(self, out: list[str]) -> None:
        if self.i >= len(self.b):
            raise self.fail("unterminated escape")
        e = self.b[self.i]
        simple = {0x62: "\b", 0x74: "\t", 0x6E: "\n", 0x66: "\f", 0x72: "\r", 0x22: '"', 0x5C: "\\"}
        if e in simple:
            self.i += 1
            out.append(simple[e])
            return
        if e == 0x75:
            self.i += 1
            if self.i + 4 > len(self.b):
                raise self.fail("truncated unicode escape")
            h = self.b[self.i : self.i + 4]
            try:
                cp = int(h.decode("ascii"), 16)
            except (UnicodeDecodeError, ValueError) as err:
                raise self.fail("invalid unicode escape") from err
            out.append(chr(cp))
            self.i += 4
            return
        if e == 0x55:
            self.i += 1
            if self.i + 8 > len(self.b):
                raise self.fail("truncated unicode escape")
            h = self.b[self.i : self.i + 8]
            try:
                cp = int(h.decode("ascii"), 16)
            except (UnicodeDecodeError, ValueError) as err:
                raise self.fail("invalid unicode escape") from err
            if cp > 0x10FFFF:
                raise self.fail("invalid scalar value")
            out.append(chr(cp))
            self.i += 8
            return
        if e in (0x0A, 0x0D, 0x20, 0x09):
            # line-ending backslash: \ + whitespace* + >= 1 newline
            j = self.i
            saw_nl = False
            while j < len(self.b) and self.b[j] in (0x20, 0x09, 0x0D, 0x0A):
                if self.b[j] in (0x0A, 0x0D):
                    saw_nl = True
                j += 1
            if saw_nl:
                self.i = j
                return
            raise self.fail("invalid escape") from None
        raise self.fail("invalid escape")

    def take_utf8_char(self) -> str:
        c = self.b[self.i]
        if c < 0x80:
            self.i += 1
            return chr(c)
        n = 2 if c < 0xE0 else 3 if c < 0xF0 else 4
        ch = self.b[self.i : self.i + n].decode("utf-8")
        self.i += n
        return ch

    def parse_literal_string(self) -> str:
        self.i += 1
        s = self.i
        b = self.b
        while True:
            if self.i >= len(b):
                raise self.fail("unterminated string")
            c = b[self.i]
            if c == 0x27:
                r = b[s : self.i].decode("utf-8")
                self.i += 1
                return r
            if (c < 0x20 and c != 0x09) or c == 0x7F:
                raise self.fail("raw control character in literal string") from None
            self.i += 1

    def parse_ml_basic(self) -> str:
        self.i += 3
        if self.i < len(self.b) and self.b[self.i] == 0x0A:
            self.i += 1
        elif self.b[self.i : self.i + 2] == b"\r\n":
            self.i += 2
        out: list[str] = []
        b = self.b
        while True:
            if self.i >= len(b):
                raise self.fail("unterminated multiline string")
            if b[self.i : self.i + 3] == b'"""':
                self.i += 3
                extra = 0
                while self.i < len(b) and b[self.i] == 0x22 and extra < 2:
                    out.append('"')
                    self.i += 1
                    extra += 1
                return "".join(out)
            if b[self.i] == 0x5C:
                self.i += 1
                self.parse_escape_into(out)
                continue
            if b[self.i] < 0x20 and b[self.i] not in (0x09, 0x0A, 0x0D):
                raise self.fail("raw control character in multiline string")
            out.append(self.take_utf8_char())

    def parse_ml_literal(self) -> str:
        self.i += 3
        if self.i < len(self.b) and self.b[self.i] == 0x0A:
            self.i += 1
        elif self.b[self.i : self.i + 2] == b"\r\n":
            self.i += 2
        s = self.i
        b = self.b
        while True:
            if self.i >= len(b):
                raise self.fail("unterminated multiline string")
            if b[self.i : self.i + 3] == b"'''":
                r = b[s : self.i].decode("utf-8")
                self.i += 3
                return r
            if b[self.i] < 0x20 and b[self.i] not in (0x09, 0x0A, 0x0D):
                raise self.fail("raw control character in multiline string") from None
            self.i += 1

    # --- numbers & datetimes --------------------------------------------------

    def parse_number_or_datetime(self) -> Any:
        start = self.i
        scanned = self.scan_datetime()
        if scanned.error is not None:
            raise scanned.error
        if scanned.kind is not None:
            raw = self.b[start : scanned.end].decode("ascii")
            self.i = scanned.end
            return ("datetime", scanned.kind, raw)
        b = self.b
        sign = 1
        sign_used = False
        if b[self.i] in (0x2B, 0x2D):
            if b[self.i] == 0x2D:
                sign = -1
            sign_used = True
            self.i += 1
        if b[self.i : self.i + 3] == b"inf":
            self.i += 3
            return ("float", math.inf * sign)
        if b[self.i : self.i + 3] == b"nan":
            self.i += 3
            return ("float", math.nan)
        digits_start = self.i
        self.read_digits(10)
        base = 10
        if (
            self.i - digits_start == 1
            and b[digits_start] == 0x30
            and self.i < len(b)
            and b[self.i] == 0x78
        ):
            base = 16
        elif (
            self.i - digits_start == 1
            and b[digits_start] == 0x30
            and self.i < len(b)
            and b[self.i] == 0x6F
        ):
            base = 8
        elif (
            self.i - digits_start == 1
            and b[digits_start] == 0x30
            and self.i < len(b)
            and b[self.i] == 0x62
        ):
            base = 2
        if base != 10:
            if sign_used:
                raise self.fail("signs are not allowed on hex/oct/bin integers") from None
            self.i += 1
            self.read_digits(base)
            text = b[digits_start + 2 : self.i].decode("ascii").replace("_", "")
            n = sign * int(text, base)
            if n < INT64_MIN or n > INT64_MAX:
                raise syntax_err(
                    E_SYNTAX, start, "integer out of 64-bit range"
                )
            return ("int", n)
        is_float = False
        if self.i < len(b) and b[self.i] == 0x2E:
            is_float = True
            self.i += 1
            self.read_digits(10)
        if self.i < len(b) and b[self.i] in (0x65, 0x45):
            is_float = True
            self.i += 1
            if self.i < len(b) and b[self.i] in (0x2B, 0x2D):
                self.i += 1
            if self.i >= len(b) or chr(b[self.i]) not in DIGITS:
                raise self.fail("expected digit in exponent")
            self.read_digits(10)
        text = b[digits_start : self.i].decode("ascii").replace("_", "")
        if not is_float:
            if len(text) > 1 and text.startswith("0"):
                raise self.fail("leading zero in integer")
            n = int(text) * sign
            if n < INT64_MIN or n > INT64_MAX:
                raise syntax_err(E_SYNTAX, start, "integer out of 64-bit range") from None
            return ("int", n)
        return ("float", float(text))

    def read_digits(self, base: int) -> None:
        if base == 10:
            digits_set = DIGITS
        elif base == 16:
            digits_set = set("0123456789abcdefABCDEF")
        elif base == 8:
            digits_set = set("01234567")
        else:
            digits_set = set("01")

        def allowed(c: int) -> bool:
            return chr(c) in digits_set

        count = 0
        while self.i < len(self.b):
            c = self.b[self.i]
            if allowed(c):
                count += 1
                self.i += 1
            elif c == 0x5F:
                if count == 0:
                    raise self.fail("leading underscore")
                nxt = self.b[self.i + 1] if self.i + 1 < len(self.b) else None
                if nxt is None or not allowed(nxt):
                    raise self.fail("trailing underscore") from None
                self.i += 1
            else:
                break
        if count == 0:
            raise self.fail("expected digit")

    def scan_datetime(self) -> _Scan:
        """Scan a TOML datetime. Returns (kind, end) or error at start."""
        b = self.b
        i = self.i
        n = len(b)
        j = i
        while j < n and chr(b[j]) in "0123456789-:":
            j += 1
        seg = b[i:j].decode("ascii")
        has_dash = "-" in seg
        has_colon = ":" in seg
        if not has_dash and not has_colon:
            return _Scan(None, i, None)
        if has_dash and not has_colon:
            if j - i != 10:
                return _Scan(None, i, None)
            if j < n and b[j] in (0x54, 0x74, 0x20):
                m = j + 1
                k = m
                while k < n and chr(b[k]) in "0123456789:":
                    k += 1
                tseg = b[m:k].decode("ascii")
                if ":" not in tseg:
                    return self.validate_datetime(i, j, DatetimeKind('date'))
                end, had_zone = self.scan_frac_zone(k)
                if end is None:
                    return _Scan(None, i, None)
                kind = DatetimeKind('offset' if had_zone else 'localdt')
                return self.validate_datetime(i, end, kind)
            return self.validate_datetime(i, j, DatetimeKind('date'))
        if has_colon and not has_dash:
            k = j
            if k < n and b[k] == 0x2E:
                k += 1
                if k < n and chr(b[k]) in "0123456789":
                    while k < n and chr(b[k]) in "0123456789":
                        k += 1
                else:
                    return _Scan(None, i, None)
            return self.validate_datetime(i, k, DatetimeKind('time'))
        return _Scan(None, i, None)

    def scan_frac_zone(self, k: int) -> tuple[int | None, bool]:
        b = self.b
        n = len(b)
        end = k
        if end < n and b[end] == 0x2E:
            end += 1
            if end < n and chr(b[end]) in "0123456789":
                while end < n and chr(b[end]) in "0123456789":
                    end += 1
            else:
                return (None, False)
        if end < n and b[end] in (0x5A, 0x7A):
            return (end + 1, True)
        if end + 6 <= n and b[end] in (0x2B, 0x2D) and chr(b[end + 3]) == ":":
            return (end + 6, True)
        return (end, False)

    def validate_datetime(self, s: int, end: int, kind: Any) -> _Scan:
        text = self.b[s:end].decode("ascii")
        if datetime_ok(text, str(kind)):
            return _Scan(kind, end, None)
        # the token has datetime shape but is invalid: fail at its start
        return _Scan(None, s, _err(s, "invalid datetime"))

    # --- tree -> Value -----------------------------------------------------------

    def to_value(self, path: tuple[Any, ...], depth: int) -> Any:
        node = self.root[path]
        if node["state"] == "aot":
            elems = []
            for idx, el in enumerate(node["elems"]):
                elems.append(self.collect(el["pairs"], path + ("#" + str(idx),), depth))
            return ("array", elems)
        return self.collect(node["pairs"], path, depth)

    def collect(self, pairs: dict[str, Any], base_path: tuple[Any, ...], depth: int) -> Any:
        out: list[tuple[str, Any]] = []
        for k, (_kind, v) in pairs.items():
            out.append((k, v))
        for p in sorted(self.root.keys()):
            if not p or len(p) != len(base_path) + 1:
                continue
            if p[:-1] != base_path:
                continue
            k = p[-1]
            if self.is_pseudo(k):
                continue
            if any(pk == k for pk, _ in out):
                raise syntax_err(E_DUPLICATE, self.i, "table and value share a key")
            out.append((k, self.to_value(p, depth + 1)))
        return make_table(out, lambda: _err(self.i, "duplicate table key"))


class _Scan:
    __slots__ = ("kind", "end", "error")

    def __init__(self, kind: Any, end: int, error: SerdeError | None) -> None:
        self.kind = kind
        self.end = end
        self.error = error
        self.kind = kind
        self.end = end
        self.error = error


# ---------------------------------------------------------------------------
# datetime validation (structural only; see SPEC)
# ---------------------------------------------------------------------------


def datetime_ok(text: str, kind: str) -> bool:
    import re


    if kind == "date":
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        if not m:
            return False
        mo, d = int(m.group(2)), int(m.group(3))
        return 1 <= mo <= 12 and 1 <= d <= 31
    if kind == "time":
        m = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})(\.\d+)?", text)
        if not m:
            return False
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return h <= 23 and mi <= 59 and se <= 60
    if kind == "localdt":
        m = re.fullmatch(
            r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?", text
        )
        if not m:
            return False
        mo, d = int(m.group(2)), int(m.group(3))
        h, mi, se = int(m.group(4)), int(m.group(5)), int(m.group(6))
        return 1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59 and se <= 60
    if kind == "offset":
        m = re.fullmatch(
            r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})",
            text,
        )
        if not m:
            return False
        mo, d = int(m.group(2)), int(m.group(3))
        h, mi, se = int(m.group(4)), int(m.group(5)), int(m.group(6))
        zone = m.group(8)
        if not (1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59 and se <= 60):
            return False
        if zone not in ("Z", "z"):
            zh, zm = int(zone[1:3]), int(zone[4:6])
            if zh > 23 or zm > 59:
                return False
        return True
    return False


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def _is_aot(v: Any) -> bool:
    return (
        isinstance(v, tuple)
        and v[0] == "array"
        and len(v[1]) > 0
        and all(isinstance(x, tuple) and x[0] == "table" for x in v[1])
    )


def _emit_table(tbl: Any, path: tuple[Any, ...], out: list[str], depth: int, limit: int) -> None:
    if depth > limit:
        raise SerdeError(E_DEPTH, "depth limit exceeded", None)
    scalars, subtables, aots = [], [], []
    for k, x in tbl[1]:
        if isinstance(x, tuple) and x[0] == "table":
            subtables.append((k, x))
        elif _is_aot(x):
            aots.append((k, x))
        else:
            scalars.append((k, x))
    prefix = ".".join(toml_key(seg) for seg in path)
    for k, x in scalars:
        out.append(f"{toml_key(k)} = {_inline(x, depth, limit)}\n")
    for k, x in subtables:
        hp = f"{prefix}.{toml_key(k)}" if prefix else toml_key(k)
        out.append(f"[{hp}]\n")
        _emit_table(x, path + (k,), out, depth + 1, limit)
    for k, x in aots:
        hp = f"{prefix}.{toml_key(k)}" if prefix else toml_key(k)
        for el in x[1]:
            out.append(f"[[{hp}]]\n")
            _emit_table(el, path + (k,), out, depth + 1, limit)


def toml_key(k: str) -> str:
    if k and all(ch in BARE_KEY for ch in k):
        return str(k)
    return toml_quote(k)


_ESCAPES = {
    0x22: '\\"',
    0x5C: "\\\\",
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
}


def toml_quote(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if o in _ESCAPES:
            out.append(_ESCAPES[o])
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _inline(v: Any, depth: int, limit: int) -> str:
    t = v[0]
    if t == "null":
        raise SerdeError(E_SYNTAX, "null is not a TOML value", None)
    if t == "bool":
        return "true" if v[1] else "false"
    if t in ("int", "uint"):
        if v[1] < INT64_MIN or v[1] > INT64_MAX:
            raise SerdeError(
                E_SYNTAX, "unsigned value out of TOML 64-bit signed range", None
            )
        return str(v[1])
    if t == "float":
        f = v[1]
        if f != f:
            return "nan"
        if f == math.inf:
            return "inf"
        if f == -math.inf:
            return "-inf"
        return render_float(f)
    if t == "str":
        return toml_quote(v[1])
    if t == "datetime":
        if not datetime_ok(v[2], str(v[1])):
            raise SerdeError(E_DATETIME, "invalid datetime raw text", None)
        return str(v[2])
    if t == "bytes":
        raise SerdeError(E_BYTES, "Bytes values cannot be encoded as TOML", None)
    if t == "array":
        if depth > limit:
            raise SerdeError(E_DEPTH, "depth limit exceeded", None)
        return "[" + ", ".join(_inline(x, depth + 1, limit) for x in v[1]) + "]"
    if t == "table":
        if depth > limit:
            raise SerdeError(E_DEPTH, "depth limit exceeded", None)
        if not v[1]:
            return "{}"
        inner = ", ".join(
            f"{toml_key(k)} = {_inline(x, depth + 1, limit)}" for k, x in v[1]
        )
        return "{ " + inner + " }"
    raise ValueError(t)  # pragma: no cover - defensive
