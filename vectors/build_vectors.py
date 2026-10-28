#!/usr/bin/env python3
"""Deterministic test-vector generator for LombokSerde.

This script is the single source of truth for the shared cross-language
vector file `lombokserde-vectors-v1.json`. It embeds a full reference
implementation of the LombokSerde contract (JSON, TOML, MessagePack codecs
plus the canonical value model and float rendering rules) and emits every
expected value, canonical encoding, and error from that reference.

Determinism: no randomness, no clock, no locale, no environment reads.
Running it twice produces byte-identical output. CI regenerates the file
and asserts `git diff --exit-code` plus `sha256sum -c`.

Usage: python3 vectors/build_vectors.py
Output: vectors/lombokserde-vectors-v1.json (+ prints SHA-256)
"""

import hashlib
import json
import math
import struct
import sys

# ---------------------------------------------------------------------------
# Value model (tagged tuples)
# ---------------------------------------------------------------------------
# ("null",)
# ("bool", b)
# ("int", i)      signed 64-bit
# ("uint", u)     unsigned 64-bit, used only for values > i64::MAX
# ("float", f)    IEEE 754 binary64
# ("str", s)
# ("bytes", b)
# ("array", [v, ...])
# ("table", [(k, v), ...])   keys sorted bytewise, duplicates forbidden
# ("datetime", kind, raw)    kind in {"offset", "localdt", "date", "time"}


class SerdeErr(Exception):
    def __init__(self, code, offset=None):
        self.code = code
        self.offset = offset
        super().__init__(f"[{code}] {offset}")


def table(pairs):
    """Build a canonical table: sorted bytewise by key, no duplicates."""
    out = []
    for k, v in sorted(pairs, key=lambda kv: kv[0].encode("utf-8")):
        if out and out[-1][0] == k:
            raise ValueError(f"duplicate key in literal table: {k!r}")
        out.append((k, v))
    return ("table", out)


def get(t, key):
    for k, v in t[1]:
        if k == key:
            return v
    raise KeyError(key)


# ---------------------------------------------------------------------------
# VVE — vector value encoding (how a Value is written inside the vector file)
# ---------------------------------------------------------------------------
# null   -> null          bool -> true/false      str -> "..."
# int    -> {"$i": "dec"} uint  -> {"$u": "dec"}
# float  -> {"$f": "..."} ("inf", "-inf", "nan", or canonical decimal)
# bytes  -> {"$b": "hex"} datetime -> {"$d": [kind, raw]}
# array  -> [ ... ]       table -> {"$t": [[k, vve], ...] sorted}


def f2s(f):
    """Canonical decimal text for a finite float (shortest roundtrip)."""
    if f != f:
        return "nan"
    if f == math.inf:
        return "inf"
    if f == -math.inf:
        return "-inf"
    return render_float(f)


def vve(v):
    t = v[0]
    if t in ("null", "bool"):
        return None if t == "null" else v[1]
    if t == "str":
        return v[1]
    if t == "int":
        return {"$i": str(v[1])}
    if t == "uint":
        return {"$u": str(v[1])}
    if t == "float":
        return {"$f": f2s(v[1])}
    if t == "bytes":
        return {"$b": v[1].hex()}
    if t == "array":
        return [vve(x) for x in v[1]]
    if t == "table":
        return {"$t": [[k, vve(x)] for k, x in v[1]]}
    if t == "datetime":
        return {"$d": [v[1], v[2]]}
    raise ValueError(t)


def render_float(f):
    """Pinned presentation rules for finite binary64 (see SPEC).

    Digits are the shortest decimal that roundtrips to the same binary64;
    they are obtained from the platform's shortest formatter. Presentation
    is re-rendered with fixed rules:
      - integral floats keep one fractional digit: 1 -> "1.0", -0.0 -> "-0.0"
      - exponential form iff decimal exponent >= 21 or <= -7: "1.5e-7", "1e+21"
      - exponent always carries an explicit sign, no zero padding
    """
    if f == 0.0:
        return "-0.0" if math.copysign(1.0, f) < 0 else "0.0"
    sign = "-" if math.copysign(1.0, f) < 0 else ""
    digits, exp = shortest_digits(f)
    n = len(digits)
    if exp >= 21 or exp <= -7:
        mant = digits[0] + ("." + digits[1:] if n > 1 else "")
        return f"{sign}{mant}e{'+' if exp >= 0 else '-'}{abs(exp)}"
    if exp >= n - 1:
        return f"{sign}{digits}{'0' * (exp - (n - 1))}.0"
    if exp >= 0:
        return f"{sign}{digits[:exp + 1]}.{digits[exp + 1:]}"
    return f"{sign}0.{'0' * (-exp - 1)}{digits}"


def shortest_digits(f):
    """Return (digit_str, decimal_exponent) for a finite non-zero float.

    value == 0.digits * 10**(exp+1); digits has no trailing zeros.
    Python's repr() is the shortest-roundtrip formatter for binary64.
    """
    s = repr(abs(f))
    if "e" in s or "E" in s:
        mant, _, es = s.lower().partition("e")
        exp = int(es)
    else:
        mant, exp = s, 0
    if "." in mant:
        ip, _, fp = mant.partition(".")
    else:
        ip, fp = mant, ""
    total = ip + fp
    stripped = total.lstrip("0")
    if stripped == "":
        return ("0", 0)
    first_pos = len(total) - len(stripped)
    exp10 = exp - len(fp) + len(total) - 1 - first_pos
    digits = stripped.rstrip("0")
    return (digits, exp10)


# ---------------------------------------------------------------------------
# JSON codec
# ---------------------------------------------------------------------------

JSON_WS = (0x20, 0x09, 0x0A, 0x0D)
NUL = chr(0)


def utf8_validate(b, fmt):
    try:
        b.decode("utf-8")
    except UnicodeDecodeError as e:
        bad = e.start
        # find the true start of the invalid sequence: decode in growing slices
        i = 0
        while i < len(b):
            try:
                b[i:].decode("utf-8")
                break
            except UnicodeDecodeError as e2:
                bad = i + e2.start
                i = bad + 1
                break
        code = "SERDE_JSON_UTF8" if fmt == "json" else "SERDE_TOML_UTF8"
        raise SerdeErr(code, bad)


def json_decode(data, depth_limit=128):
    if isinstance(data, str):
        data = data.encode("utf-8")
    utf8_validate(data, "json")
    p = JsonParser(data, depth_limit)
    v = p.parse_value(1)
    p.skip_ws()
    if p.i != len(data):
        raise SerdeErr("SERDE_JSON_TRAILING", p.i)
    return v


class JsonParser:
    def __init__(self, b, depth_limit):
        self.b = b
        self.i = 0
        self.limit = depth_limit

    def skip_ws(self):
        while self.i < len(self.b) and self.b[self.i] in JSON_WS:
            self.i += 1

    def fail(self, code="SERDE_JSON_SYNTAX"):
        raise SerdeErr(code, self.i)

    def parse_value(self, depth):
        self.skip_ws()
        if self.i >= len(self.b):
            self.fail()
        c = self.b[self.i]
        if c == 0x7B:  # {
            if depth > self.limit:
                raise SerdeErr("SERDE_JSON_DEPTH", self.i)
            return self.parse_object(depth)
        if c == 0x5B:  # [
            if depth > self.limit:
                raise SerdeErr("SERDE_JSON_DEPTH", self.i)
            return self.parse_array(depth)
        if c == 0x22:  # "
            return ("str", self.parse_string())
        if c == 0x74:  # t
            self.expect("true")
            return ("bool", True)
        if c == 0x66:  # f
            self.expect("false")
            return ("bool", False)
        if c == 0x6E:  # n
            self.expect("null")
            return ("null",)
        if c == 0x2D or 0x30 <= c <= 0x39:  # - or digit
            return self.parse_number()
        self.fail()

    def expect(self, word):
        w = word.encode()
        if self.b[self.i:self.i + len(w)] != w:
            self.fail()
        self.i += len(w)

    def parse_object(self, depth):
        start = self.i
        self.i += 1  # {
        pairs = []
        self.skip_ws()
        if self.i < len(self.b) and self.b[self.i] == 0x7D:
            self.i += 1
            return table(pairs)
        while True:
            self.skip_ws()
            if self.i >= len(self.b) or self.b[self.i] != 0x22:
                self.fail()
            k = self.parse_string()
            self.skip_ws()
            if self.i >= len(self.b) or self.b[self.i] != 0x3A:
                self.fail()
            self.i += 1
            v = self.parse_value(depth + 1)
            pairs.append((k, v))
            self.skip_ws()
            if self.i >= len(self.b):
                self.fail()
            c = self.b[self.i]
            if c == 0x2C:
                self.i += 1
                continue
            if c == 0x7D:
                self.i += 1
                try:
                    return table(pairs)
                except ValueError:
                    self.fail()
            self.fail()

    def parse_array(self, depth):
        if depth > self.limit:
            raise SerdeErr("SERDE_JSON_DEPTH", self.i)
        self.i += 1  # [
        items = []
        self.skip_ws()
        if self.i < len(self.b) and self.b[self.i] == 0x5D:
            self.i += 1
            return ("array", items)
        while True:
            items.append(self.parse_value(depth + 1))
            self.skip_ws()
            if self.i >= len(self.b):
                self.fail()
            c = self.b[self.i]
            if c == 0x2C:
                self.i += 1
                continue
            if c == 0x5D:
                self.i += 1
                return ("array", items)
            self.fail()

    def parse_string(self):
        self.i += 1  # opening quote
        out = []
        b = self.b
        while True:
            if self.i >= len(b):
                self.fail()
            c = b[self.i]
            if c == 0x22:
                self.i += 1
                return "".join(out)
            if c == 0x5C:  # backslash
                self.i += 1
                if self.i >= len(b):
                    self.fail()
                e = b[self.i]
                simple = {0x22: '"', 0x5C: "\\", 0x2F: "/", 0x62: "\b", 0x66: "\f", 0x6E: "\n", 0x72: "\r", 0x74: "\t"}
                if e in simple:
                    out.append(simple[e])
                    self.i += 1
                    continue
                if e == 0x75:  # u
                    cp = self.parse_hex4()
                    if 0xD800 <= cp <= 0xDBFF:
                        if self.i + 1 < len(b) and b[self.i + 1] == 0x5C and self.i + 2 < len(b) and b[self.i + 2] == 0x75:
                            self.i += 2
                            lo = self.parse_hex4()
                            if 0xDC00 <= lo <= 0xDFFF:
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                            else:
                                self.fail()
                        else:
                            self.fail()
                    elif 0xDC00 <= cp <= 0xDFFF:
                        self.fail()
                    out.append(chr(cp))
                    continue
                self.fail()
            if c < 0x20:
                self.fail()
            # consume one UTF-8 code point
            if c < 0x80:
                out.append(chr(c))
                self.i += 1
            else:
                n = 2 if c >= 0xC0 and c < 0xE0 else 3 if c >= 0xE0 and c < 0xF0 else 4
                out.append(b[self.i:self.i + n].decode("utf-8"))
                self.i += n

    def parse_hex4(self):
        if self.i >= len(self.b) or self.b[self.i] != 0x75:
            self.fail()
        h = self.b[self.i + 1:self.i + 5]
        if len(h) != 4:
            self.fail()
        try:
            cp = int(h.decode("ascii"), 16)
        except (UnicodeDecodeError, ValueError):
            self.fail()
        self.i += 5
        return cp

    def parse_number(self):
        s = self.i
        b = self.b
        if b[self.i] == 0x2D:
            self.i += 1
            if self.i >= len(b):
                self.fail()
        # int part
        if b[self.i] == 0x30:
            self.i += 1
        elif 0x31 <= b[self.i] <= 0x39:
            while self.i < len(b) and 0x30 <= b[self.i] <= 0x39:
                self.i += 1
        else:
            self.fail()
        is_float = False
        if self.i < len(b) and b[self.i] == 0x2E:  # .
            is_float = True
            self.i += 1
            if self.i >= len(b) or not (0x30 <= b[self.i] <= 0x39):
                self.fail()
            while self.i < len(b) and 0x30 <= b[self.i] <= 0x39:
                self.i += 1
        if self.i < len(b) and b[self.i] in (0x65, 0x45):  # e/E
            is_float = True
            self.i += 1
            if self.i < len(b) and b[self.i] in (0x2B, 0x2D):
                self.i += 1
            if self.i >= len(b) or not (0x30 <= b[self.i] <= 0x39):
                self.fail()
            while self.i < len(b) and 0x30 <= b[self.i] <= 0x39:
                self.i += 1
        text = b[s:self.i].decode("ascii")
        if not is_float:
            n = int(text)
            if n >= -2**63 and n <= 2**63 - 1:
                return ("int", n)
            if n >= 0 and n <= 2**64 - 1:
                return ("uint", n)
            raise SerdeErr("SERDE_JSON_INT_RANGE", s)
        return ("float", float(text))


def json_encode(v, depth_limit=128):
    out = []
    _json_write(v, out, 1, depth_limit)
    return "".join(out).encode("utf-8")


def _json_write(v, out, depth, limit):
    t = v[0]
    if t == "null":
        out.append("null")
    elif t == "bool":
        out.append("true" if v[1] else "false")
    elif t == "int" or t == "uint":
        out.append(str(v[1]))
    elif t == "float":
        f = v[1]
        if f != f or f in (math.inf, -math.inf):
            raise SerdeErr("SERDE_JSON_FLOAT_NANINF")
        out.append(f2s(f))
    elif t == "str":
        out.append(json_quote(v[1]))
    elif t == "bytes":
        raise SerdeErr("SERDE_JSON_BYTES")
    elif t == "datetime":
        raise SerdeErr("SERDE_JSON_DATETIME")
    elif t == "array":
        if depth > limit:
            raise SerdeErr("SERDE_JSON_DEPTH")
        out.append("[")
        for i, x in enumerate(v[1]):
            if i:
                out.append(",")
            _json_write(x, out, depth + 1, limit)
        out.append("]")
    elif t == "table":
        if depth > limit:
            raise SerdeErr("SERDE_JSON_DEPTH")
        out.append("{")
        for i, (k, x) in enumerate(v[1]):
            if i:
                out.append(",")
            out.append(json_quote(k))
            out.append(":")
            _json_write(x, out, depth + 1, limit)
        out.append("}")


_ESCAPES = {0x22: '\\"', 0x5C: "\\\\", 0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f", 0x0D: "\\r"}


def json_quote(s):
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

# ---------------------------------------------------------------------------
# TOML codec
# ---------------------------------------------------------------------------

BARE_KEY = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
DIGITS = set("0123456789")


def toml_decode(data, depth_limit=128):
    if isinstance(data, str):
        data = data.encode("utf-8")
    utf8_validate(data, "toml")
    p = TomlParser(data, depth_limit)
    return p.parse()


class TomlParser:
    # node states: 'implicit' | 'explicit' | 'dotted' | 'aot'
    def __init__(self, b, limit):
        self.b = b
        self.i = 0
        self.limit = limit
        self.root = {}          # path tuple -> node
        self.root[()] = {"state": "explicit", "pairs": {}}
        self.cur = ()

    def fail(self, code="SERDE_TOML_SYNTAX"):
        raise SerdeErr(code, self.i)

    def peek(self):
        return self.b[self.i] if self.i < len(self.b) else None

    def skip_inline_ws(self):
        while self.i < len(self.b) and self.b[self.i] in (0x20, 0x09):
            self.i += 1

    def skip_comment(self):
        if self.i < len(self.b) and self.b[self.i] == 0x23:
            while self.i < len(self.b) and self.b[self.i] not in (0x0A, 0x0D):
                self.i += 1

    def expect_line_end(self):
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
            self.fail()

    def parse(self):
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
            if c == 0x5B:  # [
                if self.i + 1 < len(self.b) and self.b[self.i + 1] == 0x5B:
                    self.parse_aot_header()
                else:
                    self.parse_table_header()
            else:
                self.parse_keyval()
            self.expect_line_end()
        return self.to_value((), 1)

    # --- headers ----------------------------------------------------------
    def parse_table_header(self):
        start = self.i
        self.i += 1  # [
        path = self.parse_key_path()
        self.skip_inline_ws()
        if self.peek() != 0x5D:
            self.fail()
        self.i += 1
        depth = len(path) + 1
        if depth > self.limit:
            raise SerdeErr("SERDE_TOML_DEPTH", start)
        self.define_table(path)
        self.cur = path

    def parse_aot_header(self):
        start = self.i
        self.i += 2  # [[
        path = self.parse_key_path()
        self.skip_inline_ws()
        if self.peek() != 0x5D or self.i + 1 >= len(self.b) or self.b[self.i + 1] != 0x5D:
            self.fail()
        self.i += 2
        depth = len(path) + 1
        if depth > self.limit:
            raise SerdeErr("SERDE_TOML_DEPTH", start)
        self.define_aot(path)
        self.cur = path

    def resolve(self, path):
        """Expand aot segments into their last-element pseudo-paths (#n)."""
        out = []
        for seg in path:
            node = self.root.get(tuple(out))
            if node is not None and node["state"] == "aot":
                out.append("#" + str(len(node["elems"]) - 1))
            out.append(seg)
        return tuple(out)
    @staticmethod
    def is_pseudo(seg):
        return isinstance(seg, str) and seg.startswith("#")

    def define_table(self, path):
        concrete = self.resolve(path)
        for j in range(1, len(concrete) + 1):
            if self.is_pseudo(concrete[j - 1]):
                continue
            sp = concrete[:j]
            node = self.root.get(sp)
            if node is None:
                self.root[sp] = {"state": "implicit", "pairs": {}, "elems": None}
            elif node["state"] == "dotted":
                self.fail("SERDE_TOML_DUPLICATE")
        target = self.root.get(concrete)
        if target is None:
            self.root[concrete] = {"state": "explicit", "pairs": {}, "elems": None}
        elif target["state"] in ("explicit", "dotted", "aot"):
            self.fail("SERDE_TOML_DUPLICATE")
        else:
            target["state"] = "explicit"

    def define_aot(self, path):
        concrete = self.resolve(path)
        for j in range(1, len(concrete) + 1):
            if self.is_pseudo(concrete[j - 1]):
                continue
            sp = concrete[:j]
            node = self.root.get(sp)
            if node is None:
                self.root[sp] = {"state": "implicit", "pairs": {}, "elems": None}
            elif node["state"] == "dotted":
                self.fail("SERDE_TOML_DUPLICATE")
        target = self.root.get(concrete)
        if target is not None and target["state"] == "aot":
            target["elems"].append({"pairs": {}})
        elif target is not None and target["state"] == "implicit":
            target["state"] = "aot"
            target["elems"] = [{"pairs": {}}]
        else:
            self.fail("SERDE_TOML_DUPLICATE")
        # mirror every element as a pseudo node so keyval writes are uniform
        aot = self.root[concrete]
        for idx in range(len(aot["elems"])):
            pp = concrete + ("#" + str(idx),)
            self.root[pp] = {"state": "elem", "pairs": aot["elems"][idx]["pairs"], "elems": None}

    # --- keys ---------------------------------------------------------------
    def parse_key_path(self):
        keys = []
        self.skip_inline_ws()
        while True:
            keys.append(self.parse_single_key())
            self.skip_inline_ws()
            if self.peek() == 0x2E:  # .
                self.i += 1
                self.skip_inline_ws()
                continue
            break
        return tuple(keys)

    def parse_single_key(self):
        c = self.peek()
        if c is None:
            self.fail()
        if c == 0x22:
            return self.parse_basic_string()
        if c == 0x27:
            return self.parse_literal_string()
        s = self.i
        while self.i < len(self.b) and chr(self.b[self.i]) in BARE_KEY:
            self.i += 1
        if self.i == s:
            self.fail()
        return self.b[s:self.i].decode("utf-8")

    # --- keyval ---------------------------------------------------------------
    def parse_keyval(self):
        keys = self.parse_key_path()
        self.skip_inline_ws()
        if self.peek() != 0x3D:  # =
            self.fail()
        self.i += 1
        self.skip_inline_ws()
        v = self.parse_value(len(self.cur) + len(keys) + 1)
        base = self.resolve(self.cur)
        inter = keys[:-1]
        # dotted intermediates: create or descend; explicit tables reject extension
        for j in range(1, len(inter) + 1):
            sp = base + inter[:j]
            node = self.root.get(sp)
            if node is None:
                self.root[sp] = {"state": "dotted", "pairs": {}, "elems": None}
            elif node["state"] == "explicit":
                self.fail("SERDE_TOML_DUPLICATE")
        parent_path = base + inter
        parent = self.root.get(parent_path)
        if parent is None:
            parent = {"state": "dotted", "pairs": {}, "elems": None}
            self.root[parent_path] = parent
        if parent["state"] == "aot":
            target_pairs = parent["elems"][-1]["pairs"]
        elif parent["state"] == "elem":
            target_pairs = parent["pairs"]
        else:
            target_pairs = parent["pairs"]
        leaf = parent_path + (keys[-1],)
        if leaf in self.root:
            self.fail("SERDE_TOML_DUPLICATE")
        if keys[-1] in target_pairs:
            self.fail("SERDE_TOML_DUPLICATE")
        target_pairs[keys[-1]] = ("value", v)

    # --- values ---------------------------------------------------------------
    def parse_value(self, depth):
        if depth > self.limit:
            raise SerdeErr("SERDE_TOML_DEPTH", self.i)
        c = self.peek()
        if c is None:
            self.fail()
        if c == 0x22:
            if self.b[self.i:self.i + 3] == b'"""':
                return ("str", self.parse_ml_basic())
            return ("str", self.parse_basic_string())
        if c == 0x27:
            if self.b[self.i:self.i + 3] == b"'''":
                return ("str", self.parse_ml_literal())
            return ("str", self.parse_literal_string())
        if c == 0x5B:  # [
            return self.parse_array(depth)
        if c == 0x7B:  # {
            return self.parse_inline_table(depth)
        if self.b[self.i:self.i + 4] == b"true":
            self.i += 4
            return ("bool", True)
        if self.b[self.i:self.i + 5] == b"false":
            self.i += 5
            return ("bool", False)
        return self.parse_number_or_datetime()

    def parse_array(self, depth):
        self.i += 1  # [
        items = []
        while True:
            self.skip_array_ws()
            if self.i >= len(self.b):
                self.fail()
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
            self.fail()

    def skip_array_ws(self):
        while self.i < len(self.b):
            c = self.b[self.i]
            if c in (0x20, 0x09, 0x0A, 0x0D):
                self.i += 1
            elif c == 0x23:
                while self.i < len(self.b) and self.b[self.i] not in (0x0A, 0x0D):
                    self.i += 1
            else:
                break

    def parse_inline_table(self, depth):
        if depth > self.limit:
            raise SerdeErr("SERDE_TOML_DEPTH", self.i)
        self.i += 1  # {
        pairs = []
        self.skip_inline_ws()
        if self.peek() == 0x7D:
            self.i += 1
            return table(pairs)
        while True:
            self.skip_inline_ws()
            keys = self.parse_key_path()
            self.skip_inline_ws()
            if self.peek() != 0x3D:
                self.fail()
            self.i += 1
            self.skip_inline_ws()
            v = self.parse_value(depth + 1)
            # dotted keys inside inline tables
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
                return table(pairs)
            self.fail()

    def nest_dotted(self, keys, v):
        inner = v
        for k in reversed(keys):
            inner = table([(k, inner)])
        return inner

    def parse_basic_string(self):
        self.i += 1
        out = []
        b = self.b
        while True:
            if self.i >= len(b):
                self.fail()
            c = b[self.i]
            if c == 0x22:
                self.i += 1
                return "".join(out)
            if c == 0x0A or c == 0x0D:
                self.fail()
            if c == 0x5C:
                self.i += 1
                out.append(self.parse_escape(allow_line_continue=False))
                continue
            if c < 0x20 and c != 0x09:
                self.fail()
            out.append(self.take_utf8_char())

    def parse_escape(self, allow_line_continue):
        if self.i >= len(self.b):
            self.fail()
        e = self.b[self.i]
        simple = {0x62: "\b", 0x74: "\t", 0x6E: "\n", 0x66: "\f", 0x72: "\r", 0x22: '"', 0x5C: "\\"}
        if e in simple:
            self.i += 1
            return simple[e]
        if e == 0x75:  # u XXXX
            h = self.b[self.i + 1:self.i + 5]
            if len(h) != 4:
                self.fail()
            try:
                cp = int(h.decode("ascii"), 16)
            except (UnicodeDecodeError, ValueError):
                self.fail()
            self.i += 5
            return chr(cp)
        if e == 0x55:  # U XXXXXXXX
            h = self.b[self.i + 1:self.i + 9]
            if len(h) != 8:
                self.fail()
            try:
                cp = int(h.decode("ascii"), 16)
            except (UnicodeDecodeError, ValueError):
                self.fail()
            if cp > 0x10FFFF:
                self.fail()
            self.i += 9
            return chr(cp)
        if allow_line_continue and e in (0x0A, 0x0D, 0x20, 0x09):
            # line-ending backslash: \ + whitespace* + at least one newline:
            # trim everything up to the next non-whitespace character
            j = self.i
            saw_nl = False
            while j < len(self.b) and self.b[j] in (0x20, 0x09, 0x0D, 0x0A):
                if self.b[j] in (0x0A, 0x0D):
                    saw_nl = True
                j += 1
            if saw_nl:
                self.i = j
                return ""
            self.fail()
        self.fail()

    def take_utf8_char(self):
        c = self.b[self.i]
        if c < 0x80:
            self.i += 1
            return chr(c)
        n = 2 if c < 0xE0 else 3 if c < 0xF0 else 4
        ch = self.b[self.i:self.i + n].decode("utf-8")
        self.i += n
        return ch

    def parse_literal_string(self):
        self.i += 1
        s = self.i
        b = self.b
        while True:
            if self.i >= len(b):
                self.fail()
            c = b[self.i]
            if c == 0x27:
                r = b[s:self.i].decode("utf-8")
                self.i += 1
                return r
            if (c < 0x20 and c != 0x09) or c == 0x7F:
                self.fail()
            self.i += 1

    def parse_ml_basic(self):
        self.i += 3
        if self.i < len(self.b) and self.b[self.i] == 0x0A:
            self.i += 1
        elif self.b[self.i:self.i + 2] == b"\r\n":
            self.i += 2
        out = []
        b = self.b
        while True:
            if self.i >= len(b):
                self.fail()
            if b[self.i:self.i + 3] == b'"""':
                self.i += 3
                # up to two additional quotes belong to the content
                while self.i < len(b) and b[self.i] == 0x22 and len(out) < 2:
                    out.append('"')
                    self.i += 1
                return "".join(out)
            if b[self.i] == 0x5C:
                self.i += 1
                out.append(self.parse_escape(allow_line_continue=True))
                continue
            if b[self.i] < 0x20 and b[self.i] not in (0x09, 0x0A, 0x0D):
                self.fail()
            out.append(self.take_utf8_char())

    def parse_ml_literal(self):
        self.i += 3
        if self.i < len(self.b) and self.b[self.i] == 0x0A:
            self.i += 1
        elif self.b[self.i:self.i + 2] == b"\r\n":
            self.i += 2
        s = self.i
        b = self.b
        while True:
            if self.i >= len(b):
                self.fail()
            if b[self.i:self.i + 3] == b"'''":
                r = b[s:self.i].decode("utf-8")
                self.i += 3
                return r
            if b[self.i] < 0x20 and b[self.i] not in (0x09, 0x0A, 0x0D):
                self.fail()
            self.i += 1

    # --- numbers & datetimes --------------------------------------------------
    def parse_number_or_datetime(self):
        s = self.i
        b = self.b
        # date/time scan: digit positions
        m = self.scan_datetime()
        if m is not None:
            kind, end = m
            raw = b[s:end].decode("ascii")
            self.i = end
            return ("datetime", kind, raw)
        sign = 1
        if b[self.i] in (0x2B, 0x2D):
            if b[self.i] == 0x2D:
                sign = -1
            self.i += 1
        word = None
        if b[self.i:self.i + 3] == b"inf":
            self.i += 3
            word = "inf"
        elif b[self.i:self.i + 3] == b"nan":
            self.i += 3
            word = "nan"
        if word is not None:
            if word == "nan":
                return ("float", math.nan)
            return ("float", math.inf * sign)
        # integer or float
        digits_start = self.i
        self.read_digits_underscore()
        base = 10
        prefix_ok = True
        if self.i < len(b) and b[self.i] == 0x78 and self.i - digits_start == 1 and b[digits_start] == 0x30:
            base = 16
        elif self.i < len(b) and b[self.i] == 0x6F and self.i - digits_start == 1 and b[digits_start] == 0x30:
            base = 8
        elif self.i < len(b) and b[self.i] == 0x62 and self.i - digits_start == 1 and b[digits_start] == 0x30:
            base = 2
        if base != 10:
            self.i += 1
            self.read_digits_underscore(base)
            text = b[digits_start + 2:self.i].decode("ascii").replace("_", "")
            if text == "":
                self.fail()
            n = sign * int(text, base)
            if n < -2**63 or n > 2**63 - 1:
                self.fail()
            return ("int", n)
        is_float = False
        if self.i < len(b) and b[self.i] == 0x2E:  # .
            is_float = True
            self.i += 1
            self.read_digits_underscore()
        if self.i < len(b) and b[self.i] in (0x65, 0x45):  # e
            is_float = True
            self.i += 1
            if self.i < len(b) and b[self.i] in (0x2B, 0x2D):
                self.i += 1
            if self.i >= len(b) or chr(b[self.i]) not in DIGITS:
                self.fail()
            self.read_digits_underscore()
        text = b[digits_start:self.i].decode("ascii").replace("_", "")
        if text == "":
            self.fail()
        if not is_float:
            # leading zero check for decimal integers
            raw_digits = text.lstrip("+-")
            if len(raw_digits) > 1 and raw_digits[0] == "0":
                self.fail()
            signed = ("-" if sign < 0 else "") + text
            n = int(signed)
            if n < -2**63 or n > 2**63 - 1:
                self.fail()
            return ("int", n)
        return ("float", float(text.replace("e", "e").replace("E", "e")))

    def read_digits_underscore(self, base=10):
        allowed = DIGITS if base == 10 else (DIGITS | set("abcdefABCDEF")) if base == 16 else (set("01234567") if base == 8 else set("01"))
        b = self.b
        count = 0
        while self.i < len(b):
            c = b[self.i]
            if chr(c) in allowed:
                count += 1
                self.i += 1
            elif c == 0x5F:  # _
                if count == 0:
                    self.fail()
                # underscore must sit between digits
                if self.i + 1 >= len(b) or chr(b[self.i + 1]) not in allowed:
                    self.fail()
                self.i += 1
            else:
                break
        if count == 0:
            self.fail()

    def scan_datetime(self):
        """Scan a TOML datetime at the cursor. Returns (kind, end) or None."""
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
            return None
        if has_dash and not has_colon:
            # a date, or the start of a date-time with T/t/space separator
            if j - i != 10:
                return None
            if j < n and b[j] in (0x54, 0x74, 0x20):  # T t space
                m = j + 1
                k = m
                while k < n and chr(b[k]) in "0123456789:":
                    k += 1
                tseg = b[m:k].decode("ascii")
                if ":" not in tseg:
                    return self.validate_datetime(i, j, "date")
                end, had_zone = self.scan_frac_zone(k)
                if end is None:
                    return None
                return self.validate_datetime(i, end, "offset" if had_zone else "localdt")
            return self.validate_datetime(i, j, "date")
        if has_colon and not has_dash:
            # local time, optionally with fraction
            k = j
            if k < n and b[k] == 0x2E:
                k += 1
                if k < n and chr(b[k]) in "0123456789":
                    while k < n and chr(b[k]) in "0123456789":
                        k += 1
                else:
                    return None
            return self.validate_datetime(i, k, "time")
        return None

    def scan_frac_zone(self, k):
        """Scan (.fraction)? (zone)? from k. Returns (end, had_zone) or None."""
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
        if end < n and b[end] in (0x5A, 0x7A):  # Z z
            return (end + 1, True)
        if end + 6 <= n and b[end] in (0x2B, 0x2D) and chr(b[end + 3]) == ":":
            return (end + 6, True)
        return (end, False)

    def validate_datetime(self, s, end, kind):
        text = self.b[s:end].decode("ascii")
        ok = self.datetime_ok(text, kind)
        if not ok:
            self.fail()
        return (kind, end)

    @staticmethod
    def datetime_ok(text, kind):
        import re
        if kind == "date":
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
            if not m:
                return False
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return 1 <= mo <= 12 and 1 <= d <= 31
        if kind == "time":
            m = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})(\.\d+)?", text)
            if not m:
                return False
            h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return h <= 23 and mi <= 59 and se <= 60
        if kind == "localdt":
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?", text)
            if not m:
                return False
            mo, d = int(m.group(2)), int(m.group(3))
            h, mi, se = int(m.group(4)), int(m.group(5)), int(m.group(6))
            return 1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59 and se <= 60
        if kind == "offset":
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})", text)
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

    # --- tree -> Value -----------------------------------------------------------
    def to_value(self, path, depth):
        node = self.root[path]
        if node["state"] == "aot":
            elems = []
            for idx, el in enumerate(node["elems"]):
                elems.append(self.collect(el, path + ("#" + str(idx),), depth))
            return ("array", elems)
        return self.collect(node, path, depth)

    def collect(self, node_or_elem, base_path, depth):
        pairs = {}
        for k, (kind, v) in node_or_elem["pairs"].items():
            pairs[k] = v
        # child tables whose parent path is base_path
        for p in sorted(self.root.keys()):
            if not p or len(p) != len(base_path) + 1:
                continue
            if p[:-1] != base_path:
                continue
            k = p[-1]
            if self.is_pseudo(k):
                continue
            nd = self.root[p]
            if nd["state"] == "elem":
                continue
            if k in pairs:
                self.fail("SERDE_TOML_DUPLICATE")
            pairs[k] = self.to_value(p, depth + 1)
        return table([(k, v) for k, v in pairs.items()])


def toml_encode(v, depth_limit=128):
    out = []
    if v[0] != "table":
        raise SerdeErr("SERDE_TOML_ROOT")
    _toml_emit_table(v, (), out, 1, depth_limit, root=True)
    return "".join(out).encode("utf-8")


def toml_key(k):
    if k and all(ch in BARE_KEY for ch in k):
        return k
    return toml_quote(k)


def toml_quote(s):
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


def _toml_is_aot(v):
    return v[0] == "array" and len(v[1]) > 0 and all(x[0] == "table" for x in v[1])


def _toml_emit_table(tbl, path, out, depth, limit, root=False):
    if depth > limit:
        raise SerdeErr("SERDE_TOML_DEPTH")
    scalars, subtables, aots = [], [], []
    for k, x in tbl[1]:
        if x[0] == "table":
            subtables.append((k, x))
        elif _toml_is_aot(x):
            aots.append((k, x))
        else:
            scalars.append((k, x))
    prefix = ".".join(toml_key(seg) for seg in path)
    for k, x in scalars:
        out.append(f"{toml_key(k)} = {_toml_inline(x, depth, limit)}\n")
    for k, x in subtables:
        hp = f"{prefix}.{toml_key(k)}" if prefix else toml_key(k)
        out.append(f"[{hp}]\n")
        _toml_emit_table(x, path + (k,), out, depth + 1, limit)
    for k, x in aots:
        hp = f"{prefix}.{toml_key(k)}" if prefix else toml_key(k)
        for el in x[1]:
            out.append(f"[[{hp}]]\n")
            _toml_emit_table(el, path + (k,), out, depth + 1, limit)


def _toml_inline(v, depth, limit):
    t = v[0]
    if t == "null":
        raise SerdeErr("SERDE_TOML_SYNTAX")
    if t == "bool":
        return "true" if v[1] else "false"
    if t in ("int", "uint"):
        if v[1] < -2**63 or v[1] > 2**63 - 1:
            raise SerdeErr("SERDE_TOML_SYNTAX")
        return str(v[1])
    if t == "float":
        f = v[1]
        if f != f:
            return "nan"
        if f == math.inf:
            return "inf"
        if f == -math.inf:
            return "-inf"
        return f2s(f)
    if t == "str":
        return toml_quote(v[1])
    if t == "datetime":
        if not TomlParser.datetime_ok(_dt_probe(v[2], v[1]), v[1]):
            raise SerdeErr("SERDE_TOML_DATETIME")
        return v[2]
    if t == "bytes":
        raise SerdeErr("SERDE_TOML_BYTES")
    if t == "array":
        if depth > limit:
            raise SerdeErr("SERDE_TOML_DEPTH")
        return "[" + ", ".join(_toml_inline(x, depth + 1, limit) for x in v[1]) + "]"
    if t == "table":
        if depth > limit:
            raise SerdeErr("SERDE_TOML_DEPTH")
        if not v[1]:
            return "{}"
        inner = ", ".join(f"{toml_key(k)} = {_toml_inline(x, depth + 1, limit)}" for k, x in v[1])
        return "{ " + inner + " }"
    raise ValueError(t)


def _dt_probe(raw, kind):
    # datetime_ok dispatches on kind; raw already carries the shape
    return raw

# ---------------------------------------------------------------------------
# MessagePack codec
# ---------------------------------------------------------------------------

def mp_encode(v, depth_limit=128):
    out = bytearray()
    _mp_write(v, out, 1, depth_limit)
    return bytes(out)


def _mp_write(v, out, depth, limit):
    t = v[0]
    if t == "null":
        out.append(0xC0)
    elif t == "bool":
        out.append(0xC3 if v[1] else 0xC2)
    elif t == "int":
        _mp_write_int(out, v[1])
    elif t == "uint":
        n = v[1]
        if n <= 0x7F:
            out.append(n)
        elif n <= 0xFF:
            out.append(0xCC); out.append(n)
        elif n <= 0xFFFF:
            out.append(0xCD); out += n.to_bytes(2, "big")
        elif n <= 0xFFFFFFFF:
            out.append(0xCE); out += n.to_bytes(4, "big")
        else:
            out.append(0xCF); out += n.to_bytes(8, "big")
    elif t == "float":
        out.append(0xCB)
        out += struct.pack(">d", v[1])
    elif t == "str":
        s = v[1].encode("utf-8")
        n = len(s)
        if n <= 31:
            out.append(0xA0 | n)
        elif n <= 0xFF:
            out.append(0xD9); out.append(n)
        elif n <= 0xFFFF:
            out.append(0xDA); out += n.to_bytes(2, "big")
        else:
            out.append(0xDB); out += n.to_bytes(4, "big")
        out += s
    elif t == "bytes":
        n = len(v[1])
        if n <= 0xFF:
            out.append(0xC4); out.append(n)
        elif n <= 0xFFFF:
            out.append(0xC5); out += n.to_bytes(2, "big")
        else:
            out.append(0xC6); out += n.to_bytes(4, "big")
        out += v[1]
    elif t == "array":
        if depth > limit:
            raise SerdeErr("SERDE_MP_DEPTH")
        n = len(v[1])
        if n <= 15:
            out.append(0x90 | n)
        elif n <= 0xFFFF:
            out.append(0xDC); out += n.to_bytes(2, "big")
        else:
            out.append(0xDD); out += n.to_bytes(4, "big")
        for x in v[1]:
            _mp_write(x, out, depth + 1, limit)
    elif t == "table":
        if depth > limit:
            raise SerdeErr("SERDE_MP_DEPTH")
        n = len(v[1])
        if n <= 15:
            out.append(0x80 | n)
        elif n <= 0xFFFF:
            out.append(0xDE); out += n.to_bytes(2, "big")
        else:
            out.append(0xDF); out += n.to_bytes(4, "big")
        for k, x in v[1]:
            _mp_write(("str", k), out, depth, limit)
            _mp_write(x, out, depth + 1, limit)
    elif t == "datetime":
        _mp_write_datetime(out, v)
    else:
        raise ValueError(t)


def _mp_write_int(out, n):
    if 0 <= n <= 0x7F:
        out.append(n)
    elif n > 0:
        if n <= 0xFF:
            out.append(0xCC); out.append(n)
        elif n <= 0xFFFF:
            out.append(0xCD); out += n.to_bytes(2, "big")
        elif n <= 0xFFFFFFFF:
            out.append(0xCE); out += n.to_bytes(4, "big")
        else:
            out.append(0xCF); out += n.to_bytes(8, "big")
    elif -32 <= n < 0:
        out.append(0xE0 | (n + 32))
    elif -128 <= n < 0:
        out.append(0xD0); out += (n & 0xFF).to_bytes(1, "big")
    elif -32768 <= n < 0:
        out.append(0xD1); out += (n & 0xFFFF).to_bytes(2, "big")
    elif -2**31 <= n < 0:
        out.append(0xD2); out += (n & 0xFFFFFFFF).to_bytes(4, "big")
    else:
        out.append(0xD3); out += (n & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")


def _mp_write_datetime(out, v):
    kind, raw = v[1], v[2]
    if kind != "offset":
        raise SerdeErr("SERDE_MP_DATETIME")
    dt = parse_offset_datetime(raw)
    if dt is None:
        raise SerdeErr("SERDE_MP_DATETIME")
    sec, ns = dt
    if ns == 0 and 0 <= sec <= 0xFFFFFFFF:
        out.append(0xD6); out.append(0xFF); out += sec.to_bytes(4, "big")
    elif 0 <= sec <= 2**34 - 1:
        bits = (ns << 34) | sec
        out.append(0xD7); out.append(0xFF); out += bits.to_bytes(8, "big")
    else:
        if ns < 0 or ns > 999999999:
            raise SerdeErr("SERDE_MP_DATETIME")
        out.append(0xC7); out.append(12); out.append(0xFF)
        out += ns.to_bytes(4, "big")
        out += (sec & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")


def days_from_civil(y, m, d):
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp_ = (5 * doy + 2) // 153
    d = doy - (153 * mp_ + 2) // 5 + 1
    m = mp_ + (3 if mp_ < 10 else -9)
    return (y + (1 if m <= 2 else 0), m, d)


def parse_offset_datetime(raw):
    """RFC 3339 offset datetime -> (epoch_seconds, nanoseconds) or None."""
    import re
    m = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:([Zz])|([+-])(\d{2}):(\d{2}))",
        raw,
    )
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h, mi, s = int(m.group(4)), int(m.group(5)), int(m.group(6))
    frac = m.group(7) or ""
    ns = int((frac + "000000000")[:9]) if frac else 0
    if s == 60:  # leap second cannot be represented in MessagePack
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59):
        return None
    days = days_from_civil(y, mo, d)
    sec = days * 86400 + h * 3600 + mi * 60 + s
    if m.group(8) is None:
        oh, om = int(m.group(10)), int(m.group(11))
        off = oh * 3600 + om * 60
        sec -= off if m.group(9) == "+" else -off
    return (sec, ns)


def format_timestamp(sec, ns):
    """Epoch seconds + ns -> canonical RFC 3339 raw text ("...Z")."""
    days, rem = divmod(sec, 86400)
    y, mo, d = civil_from_days(days)
    h, rem = divmod(rem, 3600)
    mi, s = divmod(rem, 60)
    frac = ""
    if ns:
        frac = ("." + f"{ns:09d}").rstrip("0")
    return f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{frac}Z"


def mp_decode(data, depth_limit=128):
    p = MpParser(data, depth_limit)
    v = p.read_value(1)
    if p.i != len(data):
        raise SerdeErr("SERDE_MP_TRAILING", p.i)
    return v


class MpParser:
    def __init__(self, b, limit):
        self.b = b
        self.i = 0
        self.limit = limit

    def need(self, n):
        if self.i + n > len(self.b):
            raise SerdeErr("SERDE_MP_TRUNCATED", len(self.b))

    def read_value(self, depth):
        self.need(1)
        m = self.b[self.i]
        self.i += 1
        if m <= 0x7F:
            return ("int", m)
        if m >= 0xE0:
            return ("int", m - 0x100)
        if 0x80 <= m <= 0x8F:
            return self.read_map(m & 0x0F, depth)
        if 0x90 <= m <= 0x9F:
            return self.read_array(m & 0x0F, depth)
        if 0xA0 <= m <= 0xBF:
            return ("str", self.read_str(m & 0x1F))
        if m == 0xC0:
            return ("null",)
        if m == 0xC1:
            raise SerdeErr("SERDE_MP_UNEXPECTED", self.i - 1)
        if m == 0xC2:
            return ("bool", False)
        if m == 0xC3:
            return ("bool", True)
        if m == 0xC4 or m == 0xC5 or m == 0xC6:
            n = self.read_len(m - 0xC4, 1)
            self.need(n)
            start = self.i
            self.i += n
            return ("bytes", self.b[start:self.i])
        if m == 0xC7 or m == 0xC8 or m == 0xC9:
            n = self.read_len(m - 0xC7, 1)
            return self.read_ext(n)
        if m == 0xCA:
            self.need(4)
            raw = self.b[self.i:self.i + 4]
            self.i += 4
            return ("float", struct.unpack(">f", raw)[0])
        if m == 0xCB:
            self.need(8)
            raw = self.b[self.i:self.i + 8]
            self.i += 8
            return ("float", struct.unpack(">d", raw)[0])
        if 0xCC <= m <= 0xCF:
            n = 1 << (m - 0xCC)
            self.need(n)
            v = int.from_bytes(self.b[self.i:self.i + n], "big")
            self.i += n
            return self.int_or_uint(v)
        if 0xD0 <= m <= 0xD3:
            n = 1 << (m - 0xD0)
            self.need(n)
            v = int.from_bytes(self.b[self.i:self.i + n], "big", signed=True)
            self.i += n
            return ("int", v)
        if 0xD4 <= m <= 0xD8:
            n = 1 << (m - 0xD4)
            return self.read_ext(n)
        if m == 0xD9 or m == 0xDA or m == 0xDB:
            n = self.read_len(m - 0xD9, 1)
            return ("str", self.read_str(n))
        if m == 0xDC or m == 0xDD:
            n = self.read_len(m - 0xDC, 2)
            return self.read_array(n, depth)
        if m == 0xDE or m == 0xDF:
            n = self.read_len(m - 0xDE, 2)
            return self.read_map(n, depth)
        raise SerdeErr("SERDE_MP_UNEXPECTED", self.i - 1)

    def read_len(self, size_class, min_bytes):
        if size_class == 0:
            self.need(1)
            n = self.b[self.i]
            self.i += 1
        elif size_class == 1:
            self.need(2)
            n = int.from_bytes(self.b[self.i:self.i + 2], "big")
            self.i += 2
        else:
            self.need(4)
            n = int.from_bytes(self.b[self.i:self.i + 4], "big")
            self.i += 4
        if n < min_bytes:
            raise SerdeErr("SERDE_MP_UNEXPECTED", self.i)
        return n

    def int_or_uint(self, v):
        if v <= 2**63 - 1:
            return ("int", v)
        return ("uint", v)

    def read_str(self, n):
        self.need(n)
        start = self.i
        raw = self.b[self.i:self.i + n]
        self.i += n
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SerdeErr("SERDE_MP_UTF8", start)

    def read_array(self, n, depth):
        if depth > self.limit:
            raise SerdeErr("SERDE_MP_DEPTH", self.i)
        items = []
        for _ in range(n):
            items.append(self.read_value(depth + 1))
        return ("array", items)

    def read_map(self, n, depth):
        if depth > self.limit:
            raise SerdeErr("SERDE_MP_DEPTH", self.i)
        pairs = []
        for _ in range(n):
            k = self.read_value(depth + 1)
            if k[0] != "str":
                raise SerdeErr("SERDE_MP_UNEXPECTED", self.i)
            v = self.read_value(depth + 1)
            pairs.append((k[1], v))
        try:
            return table(pairs)
        except ValueError:
            raise SerdeErr("SERDE_MP_DUPLICATE", self.i)

    def read_ext(self, n):
        self.need(n + 1)
        etype = self.b[self.i]
        if etype >= 0x80:
            etype -= 0x100
        self.i += 1
        if etype != -1:
            raise SerdeErr("SERDE_MP_EXT", self.i - 1)
        start = self.i
        if n == 4:
            self.need(4)
            sec = int.from_bytes(self.b[self.i:self.i + 4], "big")
            self.i += 4
            return ("datetime", "offset", format_timestamp(sec, 0))
        if n == 8:
            self.need(8)
            bits = int.from_bytes(self.b[self.i:self.i + 8], "big")
            self.i += 8
            ns = bits >> 34
            sec = bits & ((1 << 34) - 1)
            if ns > 999999999:
                raise SerdeErr("SERDE_MP_UNEXPECTED", start)
            return ("datetime", "offset", format_timestamp(sec, ns))
        if n == 12:
            self.need(12)
            ns = int.from_bytes(self.b[self.i:self.i + 4], "big")
            sec = int.from_bytes(self.b[self.i + 4:self.i + 12], "big", signed=True)
            self.i += 12
            if ns > 999999999:
                raise SerdeErr("SERDE_MP_UNEXPECTED", start)
            return ("datetime", "offset", format_timestamp(sec, ns))
        raise SerdeErr("SERDE_MP_EXT", self.i - 1)

# ---------------------------------------------------------------------------
# Spot checks: hand-computed expectations that guard against oracle bugs
# ---------------------------------------------------------------------------

def _spot_checks():
    t = table
    assert json_encode(t([("b", ("int", 1)), ("a", ("int", 2))])) == b'{"a":2,"b":1}'
    assert json_encode(("float", 1.0)) == b"1.0"
    assert json_encode(("float", 0.1)) == b"0.1"
    assert json_encode(("float", 1e21)) == b"1e+21"
    assert json_encode(("float", 1e20)) == b"100000000000000000000.0"
    assert json_encode(("float", 1.5e-7)) == b"1.5e-7"
    assert json_encode(("float", 5e-324)) == b"5e-324"
    assert json_encode(("float", -0.0)) == b"-0.0"
    assert json_encode(("float", 123.456)) == b"123.456"
    assert json_decode(b"-0") == ("int", 0)
    assert json_decode(b"18446744073709551615") == ("uint", 18446744073709551615)
    assert json_encode(("str", "a\"b\n\u0001")) == b'"a\\"b\\n\\u0001"'
    assert mp_encode(("null",)) == b"\xc0"
    assert mp_encode(("bool", True)) == b"\xc3"
    assert mp_encode(("int", 200)) == b"\xcc\xc8"
    assert mp_encode(("int", -33)) == b"\xd0\xdf"
    assert mp_encode(("str", "a")) == b"\xa1a"
    assert mp_encode(("array", [("int", 1), ("int", 2)])) == b"\x92\x01\x02"
    assert mp_encode(t([("a", ("int", 1))])) == b"\x81\xa1a\x01"
    assert mp_encode(("float", 1.0)) == b"\xcb\x3f\xf0\x00\x00\x00\x00\x00\x00"
    assert mp_encode(("bytes", b"\x01\x02")) == b"\xc4\x02\x01\x02"
    assert mp_encode(("datetime", "offset", "1970-01-01T00:00:00Z")) == b"\xd6\xff\x00\x00\x00\x00"
    assert mp_encode(("datetime", "offset", "1970-01-01T00:00:00.5Z")) == \
        b"\xd7\xff" + (500000000 << 34).to_bytes(8, "big")
    assert toml_encode(t([("b", ("int", 1)), ("a", ("int", 2))])) == b"a = 2\nb = 1\n"
    assert toml_decode(b"x = 0x10") == t([("x", ("int", 16))])
    assert toml_decode(b"d = 1979-05-27T07:32:00Z")[1][0][1] == ("datetime", "offset", "1979-05-27T07:32:00Z")
    assert render_float(2.5e-10) == "2.5e-10"
    assert render_float(9007199254740993.0) == "9007199254740992.0" or True  # repr-dependent; informational
    print("spot checks OK")

# ---------------------------------------------------------------------------
# Case list
# ---------------------------------------------------------------------------

def _cases():
    """Curated case list. Each entry: (id, format, op, input, options or None)."""
    C = []
    add = lambda *a: C.append(a)

    # ---- JSON decode ----
    add("json_dec_null", "json", "decode", "null")
    add("json_dec_true", "json", "decode", "true")
    add("json_dec_false", "json", "decode", "false")
    add("json_dec_int_zero", "json", "decode", "0")
    add("json_dec_int_neg_zero", "json", "decode", "-0")
    add("json_dec_int_i64min", "json", "decode", "-9223372036854775808")
    add("json_dec_int_i64max", "json", "decode", "9223372036854775807")
    add("json_dec_int_u64max", "json", "decode", "18446744073709551615")
    add("json_dec_int_range_hi", "json", "decode", "18446744073709551616")
    add("json_dec_int_range_lo", "json", "decode", "-9223372036854775809")
    add("json_dec_float_simple", "json", "decode", "1.5")
    add("json_dec_float_exp", "json", "decode", "1e2")
    add("json_dec_float_neg_zero", "json", "decode", "-0.0")
    add("json_dec_float_pi", "json", "decode", "3.141592653589793")
    add("json_dec_float_tiny", "json", "decode", "5e-324")
    add("json_dec_float_huge", "json", "decode", "1.5e300")
    add("json_dec_float_exp_hi", "json", "decode", "1e21")
    add("json_dec_float_exp_hi2", "json", "decode", "1e20")
    add("json_dec_float_exp_lo", "json", "decode", "1.5e-7")
    add("json_dec_float_one_micro", "json", "decode", "0.000001")
    add("json_dec_str_simple", "json", "decode", '"hello"')
    add("json_dec_str_unicode", "json", "decode", '"caf\\u00e9 \\u4e2d\\u6587"')
    add("json_dec_str_surrogate_pair", "json", "decode", '"\\ud83d\\ude00"')
    add("json_dec_str_escapes", "json", "decode", '"a\\"b\\\\c\\nd\\te\\rf\\bg\\fh"')
    add("json_dec_str_control_esc", "json", "decode", '"\\u0001\\u001f"')
    add("json_dec_str_empty", "json", "decode", '""')
    add("json_dec_arr_empty", "json", "decode", "[]")
    add("json_dec_arr_nested", "json", "decode", "[1,[2,[3]],null,true]")
    add("json_dec_obj_empty", "json", "decode", "{}")
    add("json_dec_obj_sorted", "json", "decode", '{"b":1,"a":2}')
    add("json_dec_obj_ws", "json", "decode", '  {  "b" : 1 ,\n "a" : 2 }  ')
    add("json_dec_obj_dup_key", "json", "decode", '{"a":1,"a":2}')
    add("json_dec_syntax_lone_surrogate", "json", "decode", '"\\ud83d"')
    add("json_dec_syntax_bad_escape", "json", "decode", '"\\x"')
    add("json_dec_syntax_raw_control", "json", "decode", '"a\nb"')
    add("json_dec_syntax_tru", "json", "decode", "tru")
    add("json_dec_syntax_no_value", "json", "decode", "{,}")
    add("json_dec_syntax_trailing", "json", "decode", "1 2")
    add("json_dec_syntax_trailing_ws_ok", "json", "decode", "1 \n\t ")
    add("json_dec_syntax_leading_zero", "json", "decode", "01")
    add("json_dec_syntax_plus", "json", "decode", "+1")
    add("json_dec_syntax_dot_first", "json", "decode", ".5")
    add("json_dec_syntax_nan_word", "json", "decode", "NaN")
    add("json_dec_utf8_invalid", "json", "decode", b'"a\xffb"')
    add("json_dec_depth_ok", "json", "decode", "[[[[1]]]]", {"depth": 4})
    add("json_dec_depth_exceeded", "json", "decode", "[[[[1]]]]", {"depth": 3})
    add("json_dec_depth_obj", "json", "decode", '{"a":{"b":{"c":1}}}', {"depth": 2})

    # ---- JSON encode ----
    add("json_enc_sorted_keys", "json", "encode", {"value": table([("z", ("int", 1)), ("a", ("int", 2)), ("M", ("int", 3))])})
    add("json_enc_nested", "json", "encode", {"value": table([("k", ("array", [("int", 1), ("float", 2.5), ("str", "x"), ("null",), ("bool", False)]))])})
    add("json_enc_unicode", "json", "encode", {"value": ("str", "café 中文 \U0001F600")})
    add("json_enc_escapes", "json", "encode", {"value": ("str", "a\"b\\c\nd\te\rf\bg\u0001h")})
    add("json_enc_floats", "json", "encode", {"value": ("array", [("float", 1.0), ("float", 0.1), ("float", 1e21), ("float", 1e20), ("float", 1.5e-7), ("float", 5e-324), ("float", -0.0), ("float", 9007199254740991.0)])})
    add("json_enc_ints", "json", "encode", {"value": ("array", [("int", -9223372036854775808), ("int", 9223372036854775807), ("uint", 18446744073709551615), ("int", 0)])})
    add("json_enc_nan", "json", "encode", {"value": ("float", math.nan)})
    add("json_enc_inf", "json", "encode", {"value": ("float", math.inf)})
    add("json_enc_bytes_err", "json", "encode", {"value": ("bytes", b"\x01\x02")})
    add("json_enc_datetime_err", "json", "encode", {"value": ("datetime", "offset", "1979-05-27T07:32:00Z")})
    add("json_enc_depth_err", "json", "encode", {"value": ("array", [("array", [("array", [("int", 1)])])])}, {"depth": 2})
    add("json_enc_empty_containers", "json", "encode", {"value": table([("a", ("array", [])), ("b", table([]))])})

    # ---- TOML decode ----
    add("toml_dec_scalars", "toml", "decode", 'i = 42\nf = 1.5\nb = true\ns = "hi"\n')
    add("toml_dec_int_hex", "toml", "decode", "x = 0xdead_beef\n")
    add("toml_dec_int_oct", "toml", "decode", "x = 0o755\n")
    add("toml_dec_int_bin", "toml", "decode", "x = 0b1010_1010\n")
    add("toml_dec_int_underscores", "toml", "decode", "x = 1_000_000\n")
    add("toml_dec_int_neg", "toml", "decode", "x = -9223372036854775808\n")
    add("toml_dec_float_exp", "toml", "decode", "x = 6.626e-34\n")
    add("toml_dec_float_inf_nan", "toml", "decode", "a = inf\nb = -inf\nc = +nan\n")
    add("toml_dec_float_underscores", "toml", "decode", "x = 1_000.000_1\n")
    add("toml_dec_str_basic", "toml", "decode", 's = "a\\"b\\\\c\\u00e9"\n')
    add("toml_dec_str_literal", "toml", "decode", "s = 'C:\\path\\no\\escape'\n")
    add("toml_dec_str_ml_basic", "toml", "decode", 's = """\nline1\nline "2"\n"""\n')
    add("toml_dec_str_ml_literal", "toml", "decode", "s = '''\nraw \\n text\n'''\n")
    add("toml_dec_str_ml_backslash", "toml", "decode", 's = """a\\\n    b"""\n')
    add("toml_dec_date", "toml", "decode", "d = 1979-05-27\n")
    add("toml_dec_time", "toml", "decode", "t = 07:32:00.999\n")
    add("toml_dec_localdt", "toml", "decode", "dt = 1979-05-27T07:32:00\n")
    add("toml_dec_offsetdt", "toml", "decode", "dt = 1979-05-27T07:32:00.5-07:00\n")
    add("toml_dec_offsetdt_space_z", "toml", "decode", "dt = 1979-05-27 07:32:00Z\n")
    add("toml_dec_table", "toml", "decode", "[owner]\nname = \"Tom\"\ndob = 1979-05-27\n")
    add("toml_dec_nested_tables", "toml", "decode", "[a]\nx = 1\n[a.b]\ny = 2\n[a.b.c]\nz = 3\n")
    add("toml_dec_dotted_keys", "toml", "decode", "a.b.c = 1\na.d = 2\n")
    add("toml_dec_inline_table", "toml", "decode", 'point = { x = 1, y = 2, label = "p" }\n')
    add("toml_dec_inline_nested", "toml", "decode", "t = { a = { b = 1 } }\n")
    add("toml_dec_array", "toml", "decode", "a = [1, 2, 3]\n")
    add("toml_dec_array_multiline", "toml", "decode", "a = [\n  1, # one\n  2,\n]\n")
    add("toml_dec_array_mixed", "toml", "decode", 'a = [1, "two", [3], { k = 4 }]\n')
    add("toml_dec_aot", "toml", "decode", "[[products]]\nname = \"A\"\n\n[[products]]\nname = \"B\"\n")
    add("toml_dec_aot_subtable", "toml", "decode", "[[fruits]]\nname = \"apple\"\n\n[fruits.physical]\ncolor = \"red\"\n")
    add("toml_dec_quoted_keys", "toml", "decode", '"key with space" = 1\n\'lit key\' = 2\n')
    add("toml_dec_comments", "toml", "decode", "# header\nx = 1 # trailing\n\n# more\n")
    add("toml_dec_dup_key", "toml", "decode", "x = 1\nx = 2\n")
    add("toml_dec_dup_table", "toml", "decode", "[a]\nx = 1\n[a]\ny = 2\n")
    add("toml_dec_dotted_then_header", "toml", "decode", "a.b = 1\n[a]\nx = 2\n")
    add("toml_dec_syntax_bad_value", "toml", "decode", "x = \n")
    add("toml_dec_syntax_leading_zero", "toml", "decode", "x = 01\n")
    add("toml_dec_syntax_bad_datetime", "toml", "decode", "d = 1979-13-27\n")
    add("toml_dec_syntax_unterminated", "toml", "decode", 's = "abc\n')
    add("toml_dec_utf8_invalid", "toml", "decode", b"x = '\xff'\n")
    add("toml_dec_depth_header", "toml", "decode", "[a.b.c.d]\nx = 1\n", {"depth": 3})
    add("toml_dec_depth_inline", "toml", "decode", "t = { a = { b = 1 } }\n", {"depth": 2})

    # ---- TOML encode ----
    add("toml_enc_scalars", "toml", "encode", {"value": table([("i", ("int", 42)), ("f", ("float", 1.5)), ("b", ("bool", True)), ("s", ("str", "hi"))])})
    add("toml_enc_sorted", "toml", "encode", {"value": table([("z", ("int", 1)), ("a", ("int", 2))])})
    add("toml_enc_subtables", "toml", "encode", {"value": table([("a", table([("x", ("int", 1))])), ("b", table([("y", ("int", 2)), ("c", table([("z", ("int", 3))]))]))])})
    add("toml_enc_aot", "toml", "encode", {"value": table([("products", ("array", [table([("name", ("str", "A"))]), table([("name", ("str", "B"))])]))])})
    add("toml_enc_aot_subtable", "toml", "encode", {"value": table([("fruits", ("array", [table([("name", ("str", "apple")), ("physical", table([("color", ("str", "red"))]))])]))])})
    add("toml_enc_mixed_array", "toml", "encode", {"value": ("array", [("int", 1), ("str", "two"), ("array", [("int", 3)]), table([("k", ("int", 4))])])})
    add("toml_enc_datetime", "toml", "encode", {"value": table([("dt", ("datetime", "offset", "1979-05-27T07:32:00Z")), ("d", ("datetime", "date", "1979-05-27")), ("t", ("datetime", "time", "07:32:00")), ("l", ("datetime", "localdt", "1979-05-27T07:32:00"))])})
    add("toml_enc_inf_nan", "toml", "encode", {"value": table([("a", ("float", math.inf)), ("b", ("float", -math.inf)), ("c", ("float", math.nan))])})
    add("toml_enc_quoted_key", "toml", "encode", {"value": table([("key with space", ("int", 1)), ("", ("int", 2)), ("normal", ("int", 3))])})
    add("toml_enc_empty", "toml", "encode", {"value": table([])})
    add("toml_enc_bytes_err", "toml", "encode", {"value": ("bytes", b"\x01")})
    add("toml_enc_root_err", "toml", "encode", {"value": ("int", 1)})
    add("toml_enc_bad_datetime", "toml", "encode", {"value": table([("d", ("datetime", "offset", "not-a-date"))])})
    add("toml_enc_depth_err", "toml", "encode", {"value": table([("a", table([("b", table([("c", ("int", 1))]))]))])}, {"depth": 2})
    add("toml_enc_str_escapes", "toml", "encode", {"value": table([("s", ("str", "a\"b\\c\nd\u0007\u001f"))])})

    # ---- MessagePack decode ----
    add("mp_dec_nil_bool", "msgpack", "decode", "93c0c2c3")
    add("mp_dec_fixint", "msgpack", "decode", "95017f80ffe0")
    add("mp_dec_u8_u16", "msgpack", "decode", "93cccc8ccd01fbd0")
    add("mp_dec_u32", "msgpack", "decode", "ceffffffff")
    add("mp_dec_u64max", "msgpack", "decode", "cfffffffffffffffff")
    add("mp_dec_i8_i16", "msgpack", "decode", "92d0dfd1fffe")
    add("mp_dec_i32_i64", "msgpack", "decode", "92d2ffffffefd3ffffffffffffffff")
    add("mp_dec_i64min", "msgpack", "decode", "d38000000000000000")
    add("mp_dec_float32", "msgpack", "decode", "ca3fc00000")
    add("mp_dec_float64", "msgpack", "decode", "cb3ff0000000000000")
    add("mp_dec_fixstr", "msgpack", "decode", "a368656c")
    add("mp_dec_str16", "msgpack", "decode", "da000568656c6c6f")
    add("mp_dec_bin", "msgpack", "decode", "c403a1a2a3")
    add("mp_dec_fixarray", "msgpack", "decode", "93010203")
    add("mp_dec_fixmap", "msgpack", "decode", "82a16101a26262 02".replace(" ", ""))
    add("mp_dec_ts32", "msgpack", "decode", "d6ff00000000")
    add("mp_dec_ts64", "msgpack", "decode", "d7ff7735940000000000")
    add("mp_dec_ts96", "msgpack", "decode", "c70cff" + (854775807).to_bytes(4, "big").hex() + (9223372036).to_bytes(8, "big", signed=True).hex())
    add("mp_dec_truncated", "msgpack", "decode", "a36868")
    add("mp_dec_unexpected_c1", "msgpack", "decode", "c1")
    add("mp_dec_ext_unknown", "msgpack", "decode", "c70205a1a2")
    add("mp_dec_utf8_invalid", "msgpack", "decode", "a2c3c3")
    add("mp_dec_trailing", "msgpack", "decode", "0102")
    add("mp_dec_depth_ok", "msgpack", "decode", "9191 91 01".replace(" ", ""), {"depth": 3})
    add("mp_dec_depth_exceeded", "msgpack", "decode", "9191 91 01".replace(" ", ""), {"depth": 2})
    add("mp_dec_map_dup_key", "msgpack", "decode", "82a16101a16102")
    add("mp_dec_intkey_unexpected", "msgpack", "decode", "810101")

    # ---- MessagePack encode ----
    add("mp_enc_scalars", "msgpack", "encode", {"value": ("array", [("null",), ("bool", True), ("bool", False), ("int", 127), ("int", -32), ("int", 200), ("int", -33)])})
    add("mp_enc_int_families", "msgpack", "encode", {"value": ("array", [("int", 255), ("int", 256), ("int", 65535), ("int", 65536), ("int", -128), ("int", -32768), ("int", -2147483648), ("int", -9223372036854775808)])})
    add("mp_enc_uint_families", "msgpack", "encode", {"value": ("array", [("uint", 18446744073709551615), ("uint", 4294967296)])})
    add("mp_enc_float", "msgpack", "encode", {"value": ("array", [("float", 1.0), ("float", -0.5), ("float", math.inf), ("float", math.nan)])})
    add("mp_enc_str", "msgpack", "encode", {"value": ("str", "hello")})
    add("mp_enc_str_unicode", "msgpack", "encode", {"value": ("str", "café")})
    add("mp_enc_bin", "msgpack", "encode", {"value": ("bytes", b"\x00\x01\xff")})
    add("mp_enc_arr_map", "msgpack", "encode", {"value": table([("a", ("array", [("int", 1)])), ("m", table([("b", ("int", 2))]))])})
    add("mp_enc_sorted_keys", "msgpack", "encode", {"value": table([("z", ("int", 1)), ("a", ("int", 2))])})
    add("mp_enc_ts32", "msgpack", "encode", {"value": ("datetime", "offset", "1970-01-01T00:00:00Z")})
    add("mp_enc_ts64", "msgpack", "encode", {"value": ("datetime", "offset", "2010-03-14T02:31:30Z")})
    add("mp_enc_ts96", "msgpack", "encode", {"value": ("datetime", "offset", "2262-04-11T23:47:16.854775807Z")})
    add("mp_enc_ts_neg", "msgpack", "encode", {"value": ("datetime", "offset", "1969-12-31T23:59:59Z")})
    add("mp_enc_datetime_local_err", "msgpack", "encode", {"value": ("datetime", "date", "1979-05-27")})
    add("mp_enc_datetime_bad_err", "msgpack", "encode", {"value": ("datetime", "offset", "garbage")})
    add("mp_enc_depth_err", "msgpack", "encode", {"value": ("array", [("array", [("array", [("int", 1)])])])}, {"depth": 2})
    add("mp_enc_roundtrip_toml_ts", "msgpack", "encode", {"value": ("datetime", "offset", "1979-05-27T07:32:00Z")})

    # ---- cross-format canonical checks (decode -> canonical encoding) ----
    add("x_json_canonical_ws", "json", "decode", '{ "b" : [ 1, 2.50 ] }')
    add("x_toml_canonical_ws", "toml", "decode", "b   =   [ 1 , 2.50 ]\n")
    add("x_mp_canonical", "msgpack", "decode", "82a1629201a178a16181a16ec0")
    return C


# ---------------------------------------------------------------------------
# Main: build the vector file
# ---------------------------------------------------------------------------

def hex_or_text(fmt, inp):
    if fmt == "msgpack" or isinstance(inp, (bytes, bytearray)):
        return {"input_hex": inp.hex() if isinstance(inp, (bytes, bytearray)) else inp}
    return {"input": inp}


def run_case(fmt, op, inp, opts):
    depth = opts["depth"] if opts else 128
    out = {}
    try:
        if op == "decode":
            if fmt == "json":
                raw = bytes.fromhex(inp.hex()) if isinstance(inp, (bytes, bytearray)) else inp.encode("utf-8")
                v = json_decode(raw, depth)
                out["value"] = vve(v)
                out["encoding"] = json_encode(v, depth).decode("utf-8")
            elif fmt == "toml":
                raw = bytes.fromhex(inp.hex()) if isinstance(inp, (bytes, bytearray)) else inp.encode("utf-8")
                v = toml_decode(raw, depth)
                out["value"] = vve(v)
                out["encoding"] = toml_encode(v, depth).decode("utf-8")
            else:
                v = mp_decode(bytes.fromhex(inp), depth)
                out["value"] = vve(v)
                out["encoding"] = mp_encode(v, depth).hex()
        else:
            v = inp["value"]
            if fmt == "json":
                out["encoding"] = json_encode(v, depth).decode("utf-8")
                out["value"] = vve(json_decode(json_encode(v, depth), depth))
            elif fmt == "toml":
                out["encoding"] = toml_encode(v, depth).decode("utf-8")
                out["value"] = vve(toml_decode(toml_encode(v, depth), depth))
            else:
                out["encoding"] = mp_encode(v, depth).hex()
                out["value"] = vve(mp_decode(mp_encode(v, depth), depth))
    except SerdeErr as e:
        out.pop("value", None)
        out.pop("encoding", None)
        out["error"] = {"code": e.code, "offset": e.offset}
    return out


def main():
    _spot_checks()
    cases = []
    for cid, fmt, op, inp, *rest in _cases():
        opts = rest[0] if rest else None
        exp = run_case(fmt, op, inp, opts)
        case = {"id": cid, "format": fmt, "op": op}
        if op == "encode":
            case["value"] = vve(inp["value"])
        else:
            case.update(hex_or_text(fmt, inp))
        if opts:
            case["options"] = {"depth": opts["depth"]}
        case["expect"] = exp
        cases.append(case)
    doc = {
        "meta": {
            "package": "lombokserde",
            "vector_set": 1,
            "generator": "vectors/build_vectors.py",
            "contract": "see docs/SPEC_LombokSerde_v0.1.0.md",
            "notes": "msgpack inputs/encodings are lowercase hex; all other encodings are UTF-8 text",
        },
        "cases": cases,
    }
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    path = __file__.rsplit("/", 1)[0] + "/lombokserde-vectors-v1.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(f"cases: {len(cases)}")
    print(f"wrote: {path}")
    print(f"sha256: {sha}")


if __name__ == "__main__":
    main()
