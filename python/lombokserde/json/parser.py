"""RFC 8259 JSON parser."""

import math
from ..error import SerdeError, SerdeErrorCode


def parse(input_str: str, max_depth: int = 128):
    """Parse a JSON string into a Value."""
    p = _JsonParser(input_str, max_depth)
    val = p._parse_value(0)
    p._skip_ws()
    if p._pos < len(p._input):
        raise p._error("trailing data")
    return val


class _JsonParser:
    def __init__(self, input_str: str, max_depth: int):
        self._input = input_str
        self._pos = 0
        self._max_depth = max_depth

    def _parse_value(self, depth: int):
        if depth > self._max_depth:
            raise SerdeError(SerdeErrorCode.DEPTH_EXCEEDED, "max depth exceeded")
        self._skip_ws()
        if self._pos >= len(self._input):
            raise self._eof()
        ch = self._input[self._pos]
        if ch == '"':
            return self._parse_string()
        if ch == '{':
            return self._parse_object(depth)
        if ch == '[':
            return self._parse_array(depth)
        if ch == 't':
            return self._expect_literal("true", True)
        if ch == 'f':
            return self._expect_literal("false", False)
        if ch == 'n':
            return self._expect_literal("null", None)
        if ch == '-' or ch.isdigit():
            return self._parse_number()
        raise self._error(f"unexpected character '{ch}'")

    def _parse_object(self, depth: int) -> dict:
        self._pos += 1  # skip '{'
        obj = {}
        self._skip_ws()
        if self._pos < len(self._input) and self._input[self._pos] == '}':
            self._pos += 1
            return obj
        while True:
            self._skip_ws()
            if self._pos >= len(self._input) or self._input[self._pos] != '"':
                raise self._error("expected string key")
            key = self._parse_string()
            if key in obj:
                raise SerdeError(SerdeErrorCode.DUPLICATE_KEY, f"duplicate key: {key}")
            self._skip_ws()
            if self._pos >= len(self._input) or self._input[self._pos] != ':':
                raise self._error("expected ':'")
            self._pos += 1
            val = self._parse_value(depth + 1)
            obj[key] = val
            self._skip_ws()
            if self._pos >= len(self._input):
                raise self._eof()
            if self._input[self._pos] == '}':
                self._pos += 1
                return obj
            if self._input[self._pos] != ',':
                raise self._error("expected ',' or '}'")
            self._pos += 1

    def _parse_array(self, depth: int) -> list:
        self._pos += 1  # skip '['
        arr = []
        self._skip_ws()
        if self._pos < len(self._input) and self._input[self._pos] == ']':
            self._pos += 1
            return arr
        while True:
            arr.append(self._parse_value(depth + 1))
            self._skip_ws()
            if self._pos >= len(self._input):
                raise self._eof()
            if self._input[self._pos] == ']':
                self._pos += 1
                return arr
            if self._input[self._pos] != ',':
                raise self._error("expected ',' or ']'")
            self._pos += 1

    def _parse_string(self) -> str:
        self._pos += 1  # skip '"'
        parts = []
        start = self._pos
        while True:
            if self._pos >= len(self._input):
                raise self._eof()
            ch = self._input[self._pos]
            if ch == '"':
                parts.append(self._input[start:self._pos])
                self._pos += 1
                return ''.join(parts)
            if ch == '\\':
                parts.append(self._input[start:self._pos])
                self._pos += 1
                parts.append(self._parse_escape())
                start = self._pos
            else:
                self._pos += 1

    def _parse_escape(self) -> str:
        if self._pos >= len(self._input):
            raise self._eof()
        ch = self._input[self._pos]
        self._pos += 1
        if ch == '"': return '"'
        if ch == '\\': return '\\'
        if ch == '/': return '/'
        if ch == 'b': return '\b'
        if ch == 'f': return '\f'
        if ch == 'n': return '\n'
        if ch == 'r': return '\r'
        if ch == 't': return '\t'
        if ch == 'u':
            cp = self._parse_hex4()
            # Handle surrogate pairs
            if 0xD800 <= cp <= 0xDBFF:
                if (self._pos + 1 < len(self._input)
                        and self._input[self._pos] == '\\'
                        and self._input[self._pos + 1] == 'u'):
                    self._pos += 2
                    lo = self._parse_hex4()
                    if 0xDC00 <= lo <= 0xDFFF:
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                    else:
                        raise SerdeError(SerdeErrorCode.INVALID_UNICODE, "invalid surrogate pair")
                else:
                    raise SerdeError(SerdeErrorCode.INVALID_UNICODE, "lone high surrogate")
            elif 0xDC00 <= cp <= 0xDFFF:
                raise SerdeError(SerdeErrorCode.INVALID_UNICODE, "lone low surrogate")
            return chr(cp)
        raise self._error(f"invalid escape '\\{ch}'")

    def _parse_hex4(self) -> int:
        if self._pos + 4 > len(self._input):
            raise self._eof()
        hex_str = self._input[self._pos:self._pos + 4]
        self._pos += 4
        try:
            return int(hex_str, 16)
        except ValueError:
            raise SerdeError(SerdeErrorCode.INVALID_UNICODE, f"invalid hex: {hex_str}")

    def _parse_number(self):
        start = self._pos
        if self._input[self._pos] == '-':
            self._pos += 1
        if self._pos >= len(self._input):
            raise self._eof()
        # Integer part
        if self._input[self._pos] == '0':
            self._pos += 1
        elif self._input[self._pos].isdigit():
            while self._pos < len(self._input) and self._input[self._pos].isdigit():
                self._pos += 1
        else:
            raise self._error("invalid number")
        is_float = False
        # Fraction
        if self._pos < len(self._input) and self._input[self._pos] == '.':
            is_float = True
            self._pos += 1
            if self._pos >= len(self._input) or not self._input[self._pos].isdigit():
                raise self._error("expected digit after '.'")
            while self._pos < len(self._input) and self._input[self._pos].isdigit():
                self._pos += 1
        # Exponent
        if self._pos < len(self._input) and self._input[self._pos] in ('e', 'E'):
            is_float = True
            self._pos += 1
            if self._pos < len(self._input) and self._input[self._pos] in ('+', '-'):
                self._pos += 1
            if self._pos >= len(self._input) or not self._input[self._pos].isdigit():
                raise self._error("expected digit in exponent")
            while self._pos < len(self._input) and self._input[self._pos].isdigit():
                self._pos += 1
        raw = self._input[start:self._pos]
        if is_float:
            return float(raw)
        return int(raw)

    def _expect_literal(self, literal: str, value):
        if self._input[self._pos:self._pos + len(literal)] != literal:
            raise self._error(f"expected '{literal}'")
        self._pos += len(literal)
        return value

    def _skip_ws(self):
        while self._pos < len(self._input) and self._input[self._pos] in ' \t\r\n':
            self._pos += 1

    def _error(self, msg: str) -> SerdeError:
        return SerdeError(SerdeErrorCode.SYNTAX_ERROR, msg)

    def _eof(self) -> SerdeError:
        return SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected end of input")
