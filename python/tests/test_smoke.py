"""Smoke tests for LombokSerde Python."""

import math
from lombokserde import json, toml, msgpack
from lombokserde.value import DateTimeValue


class TestJsonParse:
    def test_null(self):
        assert json.parse("null") is None

    def test_bool(self):
        assert json.parse("true") is True
        assert json.parse("false") is False

    def test_integer(self):
        assert json.parse("42") == 42
        assert json.parse("-17") == -17

    def test_float(self):
        assert json.parse("3.14") == 3.14

    def test_string(self):
        assert json.parse('"hello"') == "hello"
        assert json.parse('"a\\nb"') == "a\nb"

    def test_unicode(self):
        assert json.parse('"\\u0041"') == "A"

    def test_surrogate_pair(self):
        result = json.parse('"\\uD83D\\uDE00"')
        assert result == "\U0001F600"

    def test_array(self):
        assert json.parse("[1, 2, 3]") == [1, 2, 3]
        assert json.parse("[]") == []

    def test_object(self):
        result = json.parse('{"a": 1, "b": "hello"}')
        assert result == {"a": 1, "b": "hello"}

    def test_nested(self):
        result = json.parse('{"arr": [1, [2]], "obj": {"x": true}}')
        assert result["arr"] == [1, [2]]
        assert result["obj"]["x"] is True


class TestJsonSerialize:
    def test_null(self):
        assert json.to_string(None) == "null"

    def test_bool(self):
        assert json.to_string(True) == "true"
        assert json.to_string(False) == "false"

    def test_integer(self):
        assert json.to_string(42) == "42"

    def test_string(self):
        assert json.to_string("hello") == '"hello"'

    def test_array(self):
        assert json.to_string([1, 2, 3]) == "[1,2,3]"

    def test_object(self):
        result = json.to_string({"a": 1})
        assert result == '{"a":1}'

    def test_nan_to_null(self):
        assert json.to_string(float('nan')) == "null"

    def test_inf_to_null(self):
        assert json.to_string(float('inf')) == "null"


class TestJsonRoundtrip:
    def test_roundtrip(self):
        original = '{"name":"test","values":[1,2,3],"nested":{"flag":true}}'
        parsed = json.parse(original)
        serialized = json.to_string(parsed)
        reparsed = json.parse(serialized)
        assert parsed == reparsed


class TestTomlParse:
    def test_basic(self):
        result = toml.parse('title = "Test"\ncount = 42\n')
        assert result["title"] == "Test"
        assert result["count"] == 42

    def test_table(self):
        result = toml.parse('[server]\nhost = "localhost"\nport = 8080\n')
        assert result["server"]["host"] == "localhost"
        assert result["server"]["port"] == 8080

    def test_array_of_tables(self):
        result = toml.parse('[[items]]\nname = "a"\n[[items]]\nname = "b"\n')
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "a"
        assert result["items"][1]["name"] == "b"

    def test_bool(self):
        result = toml.parse("flag = true\n")
        assert result["flag"] is True

    def test_datetime(self):
        result = toml.parse('dt = 2024-01-15T10:30:00Z\n')
        assert isinstance(result["dt"], DateTimeValue)
        assert result["dt"].kind == "offset"

    def test_inline_table(self):
        result = toml.parse('point = {x = 1, y = 2}\n')
        assert result["point"]["x"] == 1

    def test_hex_octal_binary(self):
        result = toml.parse("hex = 0xFF\noct = 0o77\nbin = 0b1010\n")
        assert result["hex"] == 255
        assert result["oct"] == 63
        assert result["bin"] == 10


class TestTomlSerialize:
    def test_basic(self):
        result = toml.stringify({"title": "Test", "count": 42})
        assert 'title = "Test"' in result
        assert "count = 42" in result


class TestMsgpackRoundtrip:
    def test_null(self):
        assert msgpack.decode(msgpack.encode(None)) is None

    def test_bool(self):
        assert msgpack.decode(msgpack.encode(True)) is True
        assert msgpack.decode(msgpack.encode(False)) is False

    def test_integer(self):
        assert msgpack.decode(msgpack.encode(0)) == 0
        assert msgpack.decode(msgpack.encode(42)) == 42
        assert msgpack.decode(msgpack.encode(-1)) == -1
        assert msgpack.decode(msgpack.encode(200)) == 200
        assert msgpack.decode(msgpack.encode(1000)) == 1000
        assert msgpack.decode(msgpack.encode(100000)) == 100000

    def test_float(self):
        result = msgpack.decode(msgpack.encode(3.14))
        assert abs(result - 3.14) < 1e-10

    def test_string(self):
        assert msgpack.decode(msgpack.encode("hello")) == "hello"
        assert msgpack.decode(msgpack.encode("")) == ""

    def test_bytes(self):
        data = b"\x01\x02\x03"
        result = msgpack.decode(msgpack.encode(data))
        assert result == data

    def test_array(self):
        assert msgpack.decode(msgpack.encode([1, 2, 3])) == [1, 2, 3]
        assert msgpack.decode(msgpack.encode([])) == []

    def test_map(self):
        original = {"a": 1, "b": "hello"}
        result = msgpack.decode(msgpack.encode(original))
        assert result == original

    def test_nested(self):
        original = {"arr": [1, 2], "obj": {"x": True}}
        result = msgpack.decode(msgpack.encode(original))
        assert result == original
