"""MessagePack codec — canonical, byte-precise (see SPEC)."""

from __future__ import annotations

import struct
from typing import Any

from .error import SerdeError, syntax_err
from .value import INT64_MAX, make_table

E_TRUNCATED = "SERDE_MP_TRUNCATED"
E_UNEXPECTED = "SERDE_MP_UNEXPECTED"
E_TRAILING = "SERDE_MP_TRAILING"
E_UTF8 = "SERDE_MP_UTF8"
E_EXT = "SERDE_MP_EXT"
E_DEPTH = "SERDE_MP_DEPTH"
E_DUPLICATE = "SERDE_MP_DUPLICATE"
E_DATETIME = "SERDE_MP_DATETIME"


class MsgPackOptions:
    """Options for the MessagePack codec."""

    def __init__(self, depth_limit: int = 128) -> None:
        self.depth_limit = depth_limit


def msgpack_decode(data: bytes, opts: MsgPackOptions | None = None) -> Any:
    """Decode exactly one MessagePack value; trailing bytes are an error."""
    limit = opts.depth_limit if opts else 128
    p = _MpParser(data, limit)
    v = p.read_value(1)
    if p.i != len(data):
        raise syntax_err(
            E_TRAILING, p.i, "trailing bytes after the top-level value"
        )
    return v


def msgpack_encode(v: Any, opts: MsgPackOptions | None = None) -> bytes:
    """Encode a value with the canonical (minimal) encoding rules."""
    limit = opts.depth_limit if opts else 128
    out = bytearray()
    _write(out, v, 1, limit)
    return bytes(out)


class _MpParser:
    def __init__(self, b: bytes, limit: int) -> None:
        self.b = b
        self.i = 0
        self.limit = limit

    def need(self, n: int) -> None:
        if self.i + n > len(self.b):
            raise syntax_err(E_TRUNCATED, len(self.b), "unexpected end of input")

    def take(self, n: int) -> bytes:
        self.need(n)
        s = self.b[self.i : self.i + n]
        self.i += n
        return s

    def read_value(self, depth: int) -> Any:
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
            raise syntax_err(
                E_UNEXPECTED, self.i - 1, "reserved type code 0xc1"
            )
        if m == 0xC2:
            return ("bool", False)
        if m == 0xC3:
            return ("bool", True)
        if m in (0xC4, 0xC5, 0xC6):
            n = self.read_len(m - 0xC4, 1)
            return ("bytes", self.take(n))
        if m in (0xC7, 0xC8, 0xC9):
            n = self.read_len(m - 0xC7, 1)
            return self.read_ext(n)
        if m == 0xCA:
            raw = self.take(4)
            return ("float", struct.unpack(">f", raw)[0])
        if m == 0xCB:
            raw = self.take(8)
            return ("float", struct.unpack(">d", raw)[0])
        if 0xCC <= m <= 0xCF:
            n = 1 << (m - 0xCC)
            raw = self.take(n)
            v = int.from_bytes(raw, "big")
            return self.int_or_uint(v)
        if 0xD0 <= m <= 0xD3:
            n = 1 << (m - 0xD0)
            raw = self.take(n)
            v = int.from_bytes(raw, "big", signed=True)
            return ("int", v)
        if 0xD4 <= m <= 0xD8:
            n = 1 << (m - 0xD4)
            return self.read_ext(n)
        if m in (0xD9, 0xDA, 0xDB):
            n = self.read_len(m - 0xD9, 1)
            return ("str", self.read_str(n))
        if m in (0xDC, 0xDD):
            n = self.read_len(m - 0xDB, 2)
            return self.read_array(n, depth)
        if m in (0xDE, 0xDF):
            n = self.read_len(m - 0xDD, 2)
            return self.read_map(n, depth)
        # every one of the 256 first bytes is matched above
        raise syntax_err(E_UNEXPECTED, self.i - 1, "invalid type code")  # pragma: no cover

    def read_len(self, size_class: int, min_bytes: int) -> int:
        if size_class == 0:
            self.need(1)
            n = self.b[self.i]
            self.i += 1
        elif size_class == 1:
            self.need(2)
            n = int.from_bytes(self.take(2), "big")
        else:
            self.need(4)
            n = int.from_bytes(self.take(4), "big")
        if n < min_bytes:
            raise syntax_err(
                E_UNEXPECTED,
                self.i,
                "length field below the minimum for this type",
            )
        return n

    def int_or_uint(self, v: int) -> Any:
        if v <= INT64_MAX:
            return ("int", v)
        return ("uint", v)

    def read_str(self, n: int) -> str:
        self.need(n)
        start = self.i
        raw = self.take(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as err:
            raise syntax_err(E_UTF8, start, "invalid UTF-8 in string") from err

    def read_array(self, n: int, depth: int) -> Any:
        if depth > self.limit:
            raise syntax_err(E_DEPTH, self.i, "depth limit exceeded")
        items = [self.read_value(depth + 1) for _ in range(n)]
        return ("array", items)

    def read_map(self, n: int, depth: int) -> Any:
        if depth > self.limit:
            raise syntax_err(E_DEPTH, self.i, "depth limit exceeded")
        pairs = []
        for _ in range(n):
            k = self.read_value(depth + 1)
            if not (isinstance(k, tuple) and k and k[0] == "str"):
                raise syntax_err(E_UNEXPECTED, self.i, "map key is not a string")
            v = self.read_value(depth + 1)
            pairs.append((k[1], v))
        try:
            return make_table(pairs, lambda: syntax_err(E_DUPLICATE, self.i, "duplicate map key"))
        except SerdeError:
            raise

    def read_ext(self, n: int) -> Any:
        self.need(n + 1)
        etype = self.b[self.i]
        if etype >= 0x80:
            etype -= 0x100
        self.i += 1
        if etype != -1:
            raise syntax_err(E_EXT, self.i - 1, "unsupported extension type")
        if n == 4:
            sec = int.from_bytes(self.take(4), "big")
            return self.datetime_from_timestamp(sec, 0)
        if n == 8:
            bits = int.from_bytes(self.take(8), "big")
            ns = bits >> 34
            sec = bits & ((1 << 34) - 1)
            if ns > 999_999_999:
                raise syntax_err(
                    E_UNEXPECTED, self.i - 8, "nanoseconds out of range"
                )
            return self.datetime_from_timestamp(sec, ns)
        if n == 12:
            raw = self.take(12)
            ns = int.from_bytes(raw[0:4], "big")
            sec = int.from_bytes(raw[4:12], "big", signed=True)
            if ns > 999_999_999:
                raise syntax_err(
                    E_UNEXPECTED, self.i - 12, "nanoseconds out of range"
                )
            return self.datetime_from_timestamp(sec, ns)
        raise syntax_err(
            E_EXT, self.i - 1, "unsupported timestamp payload length"
        )

    @staticmethod
    def datetime_from_timestamp(sec: int, ns: int) -> Any:
        from .value import DatetimeKind

        return ("datetime", DatetimeKind("offset"), format_timestamp(sec, ns))


def _write(out: bytearray, v: Any, depth: int, limit: int) -> None:
    t = v[0]
    if t == "null":
        out.append(0xC0)
    elif t == "bool":
        out.append(0xC3 if v[1] else 0xC2)
    elif t == "int":
        _write_int(out, v[1])
    elif t == "uint":
        n = v[1]
        if n <= 0x7F:
            out.append(n)
        elif n <= 0xFF:
            out.append(0xCC)
            out.append(n)
        elif n <= 0xFFFF:
            out.append(0xCD)
            out += n.to_bytes(2, "big")
        elif n <= 0xFFFFFFFF:
            out.append(0xCE)
            out += n.to_bytes(4, "big")
        elif n <= 0xFFFFFFFFFFFFFFFF:
            out.append(0xCF)
            out += n.to_bytes(8, "big")
        else:  # pragma: no cover - defensive
            raise SerdeError(E_UNEXPECTED, "uint out of 64-bit range", None)
    elif t == "float":
        out.append(0xCB)
        out += struct.pack(">d", v[1])
    elif t == "str":
        s = v[1].encode("utf-8")
        n = len(s)
        if n <= 31:
            out.append(0xA0 | n)
        elif n <= 0xFF:
            out.append(0xD9)
            out.append(n)
        elif n <= 0xFFFF:
            out.append(0xDA)
            out += n.to_bytes(2, "big")
        else:
            out.append(0xDB)
            out += n.to_bytes(4, "big")
        out += s
    elif t == "bytes":
        n = len(v[1])
        if n <= 0xFF:
            out.append(0xC4)
            out.append(n)
        elif n <= 0xFFFF:
            out.append(0xC5)
            out += n.to_bytes(2, "big")
        else:
            out.append(0xC6)
            out += n.to_bytes(4, "big")
        out += v[1]
    elif t == "array":
        if depth > limit:
            raise SerdeError(E_DEPTH, "depth limit exceeded", None)
        n = len(v[1])
        if n <= 15:
            out.append(0x90 | n)
        elif n <= 0xFFFF:
            out.append(0xDC)
            out += n.to_bytes(2, "big")
        else:
            out.append(0xDD)
            out += n.to_bytes(4, "big")
        for x in v[1]:
            _write(out, x, depth + 1, limit)
    elif t == "table":
        if depth > limit:
            raise SerdeError(E_DEPTH, "depth limit exceeded", None)
        n = len(v[1])
        if n <= 15:
            out.append(0x80 | n)
        elif n <= 0xFFFF:
            out.append(0xDE)
            out += n.to_bytes(2, "big")
        else:
            out.append(0xDF)
            out += n.to_bytes(4, "big")
        for k, x in v[1]:
            _write(out, ("str", k), depth, limit)
            _write(out, x, depth + 1, limit)
    elif t == "datetime":
        _write_datetime(out, v)
    else:  # pragma: no cover - defensive
        raise ValueError(t)


def _write_int(out: bytearray, n: int) -> None:
    if 0 <= n <= 0x7F:
        out.append(n)
    elif n > 0:
        if n <= 0xFF:
            out.append(0xCC)
            out.append(n)
        elif n <= 0xFFFF:
            out.append(0xCD)
            out += n.to_bytes(2, "big")
        elif n <= 0xFFFFFFFF:
            out.append(0xCE)
            out += n.to_bytes(4, "big")
        else:
            out.append(0xCF)
            out += n.to_bytes(8, "big")
    elif -32 <= n < 0:
        out.append(0xE0 | (n + 32))
    elif -128 <= n < 0:
        out.append(0xD0)
        out += (n & 0xFF).to_bytes(1, "big")
    elif -32768 <= n < 0:
        out.append(0xD1)
        out += (n & 0xFFFF).to_bytes(2, "big")
    elif -(2**31) <= n < 0:
        out.append(0xD2)
        out += (n & 0xFFFFFFFF).to_bytes(4, "big")
    else:
        out.append(0xD3)
        out += (n & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")


def _write_datetime(out: bytearray, v: Any) -> None:

    kind, raw = str(v[1]), v[2]
    if kind != "offset":
        raise SerdeError(
            E_DATETIME,
            "only Offset datetimes map to MessagePack timestamps",
            None,
        )
    parsed = parse_offset_datetime(raw)
    if parsed is None:
        raise SerdeError(
            E_DATETIME,
            "datetime raw text is not a valid RFC 3339 offset datetime",
            None,
        )
    sec, ns = parsed
    if ns == 0 and 0 <= sec <= 0xFFFFFFFF:
        out.append(0xD6)
        out.append(0xFF)
        out += sec.to_bytes(4, "big")
    elif 0 <= sec <= 2**34 - 1:
        bits = (ns << 34) | sec
        out.append(0xD7)
        out.append(0xFF)
        out += bits.to_bytes(8, "big")
    else:
        if ns < 0 or ns > 999_999_999:
            raise SerdeError(E_DATETIME, "nanoseconds out of range", None)
        out.append(0xC7)
        out.append(12)
        out.append(0xFF)
        out += ns.to_bytes(4, "big")
        out += (sec & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")


# ---------------------------------------------------------------------------
# Calendar math (identical integer arithmetic in every port)
# ---------------------------------------------------------------------------


def days_from_civil(y: int, m: int, d: int) -> int:
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = m + (-3 if m > 2 else 9)
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (1 if m <= 2 else 0), m, d)


def parse_offset_datetime(raw: str) -> tuple[int, int] | None:
    """RFC 3339 offset datetime -> (epoch seconds, nanoseconds) or None."""
    import re

    pattern = (
        r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})"
        r"(?:\.(\d+))?(?:([Zz])|([+-])(\d{2}):(\d{2}))"
    )
    m = re.fullmatch(pattern, raw)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h, mi, s = int(m.group(4)), int(m.group(5)), int(m.group(6))
    frac = m.group(7) or ""
    ns = int((frac + "000000000")[:9]) if frac else 0
    if s == 60:  # leap seconds are not representable in MessagePack
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


def format_timestamp(sec: int, ns: int) -> str:
    """Epoch seconds + nanoseconds -> canonical `...Z` text."""
    days, rem = divmod(sec, 86400)
    y, mo, d = civil_from_days(days)
    h, rem = divmod(rem, 3600)
    mi, s = divmod(rem, 60)
    frac = ""
    if ns:
        frac = ("." + f"{ns:09d}").rstrip("0")
    return f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{frac}Z"
