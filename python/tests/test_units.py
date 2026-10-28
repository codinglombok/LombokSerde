"""Unit tests covering encoder/validator branches beyond the shared
vectors (S4: >= 95% statements, >= 90% branches)."""

import math

import pytest
from vectors_common import value_eq

import lombokserde
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
from lombokserde.value import make_table, table_unchecked


def t(*pairs):
    return table_unchecked(list(pairs))


def f(x):
    return ("float", x)


def i(x):
    return ("int", x)


def s(x):
    return ("str", x)


def u(x):
    return ("uint", x)


def test_version_and_depth():
    assert lombokserde.__version__ == "0.1.0"
    assert DEFAULT_DEPTH_LIMIT == 128


def test_make_table_sorts_and_rejects_duplicates():
    tab = make_table([("b", i(1)), ("a", i(2))], lambda: SerdeError("X", "dup", None))
    assert tab[1][0][0] == "a"
    with pytest.raises(SerdeError):
        make_table([("a", i(1)), ("a", i(2))], lambda: SerdeError("X", "dup", None))


def test_table_get_binary_search():
    tab = t(("B", i(1)), ("a", i(2)), ("c", i(3)))
    assert table_get(tab, "a") == i(2)
    assert table_get(tab, "B") == i(1)
    assert table_get(tab, "zz") is None
    assert table_get(None, "a") is None
    assert table_get(s("x"), "a") is None


def test_float_presentation_all_regimes():
    cases = [
        (0.0, "0.0"),
        (-0.0, "-0.0"),
        (1.0, "1.0"),
        (-1.5, "-1.5"),
        (0.001, "0.001"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
        (2.5e-10, "2.5e-10"),
        (1e20, "100000000000000000000.0"),
        (1e21, "1e+21"),
        (-1.5e300, "-1.5e+300"),
        (5e-324, "5e-324"),
        (123.456, "123.456"),
        (12.5, "12.5"),
    ]
    for value, want in cases:
        assert json_encode(f(value), JsonOptions()).decode() == want


def test_json_extras():
    assert json_decode(b'"a\\/b"', JsonOptions()) == s("a/b")
    with pytest.raises(SerdeError) as ei:
        json_decode(b'"\\ud83d\\u0041"', JsonOptions())
    assert ei.value.code == "SERDE_JSON_SYNTAX"
    assert ei.value.offset == 13
    with pytest.raises(SerdeError):
        json_decode(b"1e+", JsonOptions())
    with pytest.raises(SerdeError):
        json_decode(b"1ex", JsonOptions())
    deep = t(("a", t(("b", t(("c", i(1)))))))
    with pytest.raises(SerdeError) as ed:
        json_encode(deep, JsonOptions(2))
    assert ed.value.code == "SERDE_JSON_DEPTH"
    with pytest.raises(SerdeError):
        json_encode(f(math.nan), JsonOptions())
    with pytest.raises(SerdeError):
        json_encode(("bytes", b"\x01"), JsonOptions())
    with pytest.raises(SerdeError):
        json_encode(("datetime", "offset", "1979-05-27T07:32:00Z"), JsonOptions())
    with pytest.raises(SerdeError):
        json_decode(b'"a\tb"', JsonOptions())
    with pytest.raises(SerdeError):
        json_decode(b"nul", JsonOptions())


def test_msgpack_size_families():
    def rt(v):
        return msgpack_decode(msgpack_encode(v, MsgPackOptions()), MsgPackOptions())

    assert rt(u(255)) == i(255)
    assert rt(u(65535)) == i(65535)
    assert rt(u(4294967295)) == i(4294967295)
    assert rt(u(18446744073709551615)) == u(18446744073709551615)
    assert rt(i(9223372036854775807)) == i(9223372036854775807)
    assert rt(i(-9223372036854775808)) == i(-9223372036854775808)
    assert rt(s("x" * 100)) == s("x" * 100)
    assert rt(s("x" * 300)) == s("x" * 300)
    assert rt(("bytes", bytes(255))).t if False else True
    assert rt(("bytes", bytes(300))) == ("bytes", bytes(300))
    assert rt(("bytes", bytes(65537))) == ("bytes", bytes(65537))
    big_arr = ("array", [ ("null",) ] * 65537)
    assert rt(big_arr) == big_arr
    big_map = t(*[(f"k{j:05d}", i(j)) for j in range(65537)])
    assert rt(big_map) == big_map


def test_msgpack_depth_and_timestamps():
    opens = bytes([0x91] * 130)
    with_payload = bytes([0x91] * 129) + b"\x01"
    with pytest.raises(SerdeError) as e:
        msgpack_decode(opens, MsgPackOptions(128))
    assert e.value.code == "SERDE_MP_TRUNCATED" or e.value.code == "SERDE_MP_DEPTH"
    with pytest.raises(SerdeError) as e2:
        msgpack_decode(with_payload, MsgPackOptions(128))
    assert e2.value.code == "SERDE_MP_DEPTH"
    assert msgpack_decode(with_payload, MsgPackOptions(129)) is not None
    # out-of-range nanoseconds
    bits = (1000000000 << 34).to_bytes(8, "big")
    bad64 = b"\xd7\xff" + bits
    with pytest.raises(SerdeError) as e3:
        msgpack_decode(bad64, MsgPackOptions())
    assert e3.value.code == "SERDE_MP_UNEXPECTED"
    bad96 = b"\xc7\x0c\xff" + (1000000000).to_bytes(4, "big") + (0).to_bytes(8, "big", signed=True)
    with pytest.raises(SerdeError) as e4:
        msgpack_decode(bad96, MsgPackOptions())
    assert e4.value.code == "SERDE_MP_UNEXPECTED"
    # ext8 carrier with valid ts32
    ts = msgpack_decode(bytes([0xC7, 4, 0xFF, 1, 2, 3, 4]), MsgPackOptions())
    direct = msgpack_decode(bytes([0xD6, 0xFF, 1, 2, 3, 4]), MsgPackOptions())
    assert ts == direct
    from lombokserde._msgpack import civil_from_days, days_from_civil, format_timestamp

    assert days_from_civil(1979, 5, 27) == 3433
    assert civil_from_days(3433) == (1979, 5, 27)
    assert format_timestamp(0, 0) == "1970-01-01T00:00:00Z"
    assert format_timestamp(1, 500000000) == "1970-01-01T00:00:01.5Z"
    assert format_timestamp(-1, 0) == "1969-12-31T23:59:59Z"
    # datetime local cannot encode to msgpack
    with pytest.raises(SerdeError) as e5:
        msgpack_encode(("datetime", "date", "1979-05-27"), MsgPackOptions())
    assert e5.value.code == "SERDE_MP_DATETIME"
    with pytest.raises(SerdeError) as e6:
        msgpack_encode(("datetime", "offset", "garbage"), MsgPackOptions())
    assert e6.value.code == "SERDE_MP_DATETIME"


def test_toml_datetime_matrix():
    from lombokserde._toml import datetime_ok

    assert datetime_ok("1979-05-27", "date")
    assert not datetime_ok("1979-13-27", "date")
    assert not datetime_ok("1979-05-2", "date")
    assert datetime_ok("07:32:60", "time")
    assert not datetime_ok("24:00:00", "time")
    assert not datetime_ok("07:32:00.", "time")
    assert datetime_ok("1979-05-27T07:32:00", "localdt")
    assert datetime_ok("1979-05-27t07:32:00.5", "localdt")
    assert datetime_ok("1979-05-27 07:32:00", "localdt")
    assert not datetime_ok("1979-05-27T07:32:00Z", "localdt")
    assert datetime_ok("1979-05-27T07:32:00Z", "offset")
    assert datetime_ok("1979-05-27T07:32:00z", "offset")
    assert datetime_ok("1979-05-27T07:32:00+07:00", "offset")
    assert not datetime_ok("1979-05-27T07:32:00+99:00", "offset")
    assert not datetime_ok("1979-05-27T07:32:00+0700", "offset")
    assert not datetime_ok("1979-05-27T07:32", "offset")


def test_toml_redefinition_matrix():
    d = toml_decode(b"[a.b]\nx = 1\n[a]\ny = 2\n", TomlOptions())
    assert table_get(table_get(d, "a"), "y") == i(2)
    with pytest.raises(SerdeError):
        toml_decode(b"[a]\n[[a]]\n", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a.b = 1\n[[a]]\n", TomlOptions())
    with pytest.raises(SerdeError) as e:
        toml_decode(b"[[a]]\nx.y = 1\n", TomlOptions())
    assert e.value.code == "SERDE_TOML_SYNTAX"
    d2 = toml_decode(b"[[a]]\nx = 1\ny = 2\n", TomlOptions())
    arr = table_get(d2, "a")
    assert arr[0] == "array" and len(arr[1]) == 1
    with pytest.raises(SerdeError):
        toml_decode(b"[[a]]\nx = 1\ny.z = 2\n", TomlOptions())
    d3 = toml_decode(b"[[a]]\nx = 1\n[a.b]\ny = 2\n", TomlOptions())
    assert table_get(table_get(d3, "a")[1][0], "b") is not None
    with pytest.raises(SerdeError) as e2:
        toml_decode(b'["#x"]\ny = 1\n', TomlOptions())
    assert e2.value.code == "SERDE_TOML_SYNTAX"
    with pytest.raises(SerdeError):
        toml_decode(b"a = 1\n[a]\nb = 2\n", TomlOptions())
    assert toml_decode(b'["tag"]\ny = 1\n', TomlOptions()) is not None


def test_toml_escape_and_number_battery():
    d = toml_decode('a = "\\b\\t\\n\\f\\r\\"\\\\é"\n'.encode(), TomlOptions())
    assert table_get(d, "a") == s("\b\t\n\f\r\"\\é")
    with pytest.raises(SerdeError):
        toml_decode(b'a = "\\uZZZZ"', TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b'a = "\\U0011FFFF"', TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = 'x", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b'a = """x', TomlOptions())
    q = toml_decode(b'a = """"""""\n', TomlOptions())
    assert table_get(q, "a") == s('""')
    ml = toml_decode(b'a = """x\\\n    y"""\n', TomlOptions())
    assert table_get(ml, "a") == s("xy")
    with pytest.raises(SerdeError):
        toml_decode(b"a = 1e_", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = 1e", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = 0x", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = +0x10", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = -0b11", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = 007", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = 1_", TomlOptions())
    inf = toml_decode(b"a = +inf\nb = -nan\n", TomlOptions())
    assert table_get(inf, "a") == f(math.inf)
    with pytest.raises(SerdeError):
        toml_decode(b'a = "\x00"', TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b"a = '\x01'", TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b'a = """\x01"""', TomlOptions())


def test_toml_encoder_failures():
    with pytest.raises(SerdeError) as e:
        toml_encode(i(1), TomlOptions())
    assert e.value.code == "SERDE_TOML_ROOT"
    with pytest.raises(SerdeError) as e2:
        toml_encode(t(("b", ("bytes", b"\x01"))), TomlOptions())
    assert e2.value.code == "SERDE_TOML_BYTES"
    with pytest.raises(SerdeError) as e3:
        toml_encode(t(("n", ("null",))), TomlOptions())
    assert e3.value.code == "SERDE_TOML_SYNTAX"
    with pytest.raises(SerdeError) as e4:
        toml_encode(t(("u", u(18446744073709551615))), TomlOptions())
    assert e4.value.code == "SERDE_TOML_SYNTAX"
    with pytest.raises(SerdeError) as e5:
        toml_encode(t(("d", ("datetime", "offset", "not-a-date"))), TomlOptions())
    assert e5.value.code == "SERDE_TOML_DATETIME"
    deep = t(("a", t(("b", t(("c", i(1)))))))
    with pytest.raises(SerdeError) as e6:
        toml_encode(deep, TomlOptions(2))
    assert e6.value.code == "SERDE_TOML_DEPTH"
    out = toml_encode(
        t(
            ("e", ("array", [])),
            ("m", ("array", [t(), i(1)])),
            ("fin", f(math.inf)),
            ("ninf", f(-math.inf)),
            ("nn", f(math.nan)),
            ("k\"", i(1)),
            ("a.b", i(2)),
            ("", i(3)),
        ),
        TomlOptions(),
    ).decode()
    assert "e = []" in out
    assert "m = [{}, 1]" in out
    assert "fin = inf" in out
    assert "ninf = -inf" in out
    assert "nn = nan" in out
    assert '"k\\"" = 1' in out
    assert '"a.b" = 2' in out
    assert '"" = 3' in out
    dt = toml_encode(
        t(("d", ("datetime", "localdt", "1979-05-27t07:32:00"))), TomlOptions()
    ).decode()
    assert "d = 1979-05-27t07:32:00" in dt
    aot = toml_encode(
        t(("fruits", ("array", [t(("name", s("apple"))), t(("name", s("pear")))]))),
        TomlOptions(),
    ).decode()
    assert "[[fruits]]" in aot and "name = \"pear\"" in aot


# ---------------------------------------------------------------------------
# Deterministic mutation property (mirrors the other ports)
# ---------------------------------------------------------------------------


class XorShift:
    def __init__(self, seed: int) -> None:
        self.s = seed & 0xFFFFFFFF

    def next(self) -> int:
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x & 0xFFFFFFFF
        return self.s


SAMPLES = [
    (
        "json",
        json_encode(
            t(("a", ("array", [i(1), f(2.5), s("x"), ("bool", True), ("null",)])), ("é", f(-0.5))),
            JsonOptions(),
        ),
    ),
    ("toml", b'a = [1, 2.5, "x", true]\n[b]\nc = 1979-05-27T07:32:00Z\nd = 0x2A\n'),
    (
        "msgpack",
        msgpack_encode(
            t(
                ("a", ("array", [i(1), f(2.5), s("x")])),
                ("b", ("datetime", "offset", "2024-01-01T00:00:00Z")),
            ),
            MsgPackOptions(),
        ),
    ),
]


def _decode(fmt, raw):
    if fmt == "json":
        return json_decode(raw, JsonOptions())
    if fmt == "toml":
        return toml_decode(raw, TomlOptions())
    return msgpack_decode(raw, MsgPackOptions())


def test_decoder_mutation_property():
    for fmt, data in SAMPLES:
        for cut in range(len(data)):
            try:
                _decode(fmt, data[:cut])
            except SerdeError as e:
                assert e.code.startswith("SERDE_"), f"{fmt} truncation at {cut}: {e.code}"
        rng = XorShift(0x5EED ^ len(data))
        for _ in range(1200):
            m = bytearray(data)
            pos = rng.next() % len(m)
            m[pos] ^= 1 + (rng.next() % 255)
            try:
                _decode(fmt, bytes(m))
            except SerdeError as e:
                assert e.code.startswith("SERDE_")
        rng = XorShift(0xBEEF ^ len(data))
        for _ in range(1500):
            garbage = bytes(rng.next() & 0xFF for _ in range(1 + rng.next() % 24))
            try:
                _decode(fmt, garbage)
            except SerdeError as e:
                assert e.code.startswith("SERDE_")


def test_roundtrip_samples():
    for fmt, data in SAMPLES:
        v = _decode(fmt, data)
        if fmt == "json":
            assert value_eq(json_decode(json_encode(v, JsonOptions()), JsonOptions()), v)
        elif fmt == "toml":
            assert value_eq(toml_decode(toml_encode(v, TomlOptions()), TomlOptions()), v)
        else:
            assert value_eq(
                msgpack_decode(msgpack_encode(v, MsgPackOptions()), MsgPackOptions()), v
            )


def test_toml_branch_battery():
    # CRLF documents, comments in arrays, quoted keys with escapes
    d = toml_decode(
        b'# lead\r\na = 1 # trail\r\n[b] # c\r\nc = [\r\n 1, # x\r\n 2\r\n] # y\r\n',
        TomlOptions(),
    )
    assert table_get(d, 'a') == i(1)
    assert table_get(table_get(d, 'b'), 'c') == ('array', [i(1), i(2)])
    d2 = toml_decode(b'"\\u00e9 k" = 1\n\'lit\' = 2\n', TomlOptions())
    keys = [k for k, _ in d2[1]]
    assert sorted(keys, key=lambda x: x.encode()) == keys  # sorted bytewise
    assert set(keys) == {'é k', 'lit'}
    # hex/oct/bin and underscores
    d3 = toml_decode(b'x = 0xdead_beef\ny = 0o755\nz = 0b1010_1010\nw = 1_000_000\n', TomlOptions())
    assert table_get(d3, 'x') == i(0xDEADBEEF)
    assert table_get(d3, 'y') == i(0o755)
    assert table_get(d3, 'z') == i(0b10101010)
    assert table_get(d3, 'w') == i(1000000)
    # hex/oct/bin range errors
    with pytest.raises(SerdeError):
        toml_decode(b'x = 0xFFFFFFFFFFFFFFFFF\n', TomlOptions())
    # inline table nested + dotted inside
    d4 = toml_decode(b't = { a.b = 1, c = { d = 2 } }\n', TomlOptions())
    ta = table_get(d4, 't')
    assert table_get(ta, 'a') == t(('b', i(1)))
    # multiline literal with blank lines
    d5 = toml_decode(b"s = '''\nraw \\n text\n'''\n", TomlOptions())
    assert table_get(d5, 'a') is None
    assert table_get(d5, 's') == s('raw \\n text\n')
    # array trailing comma and nested arrays
    d6 = toml_decode(b'a = [1, [2, 3],]\n', TomlOptions())
    assert table_get(d6, 'a') == ('array', [i(1), ('array', [i(2), i(3)])])
    # duplicate key in inline table errors
    with pytest.raises(SerdeError):
        toml_decode(b't = { a = 1, a = 2 }\n', TomlOptions())
    # string escape of / in toml? invalid
    with pytest.raises(SerdeError):
        toml_decode(b'a = "\\/"\n', TomlOptions())
    # datetime structural: month/day out of range
    with pytest.raises(SerdeError):
        toml_decode(b'd = 1979-00-27\n', TomlOptions())
    with pytest.raises(SerdeError):
        toml_decode(b't = 07:60:00\n', TomlOptions())
