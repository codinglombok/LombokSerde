"""JSON tokenizer."""

from enum import Enum
from typing import Any, List, Optional
from ..error import SerdeError, SerdeErrorCode


class JsonTokenType(Enum):
    OBJECT_START = "ObjectStart"
    OBJECT_END = "ObjectEnd"
    ARRAY_START = "ArrayStart"
    ARRAY_END = "ArrayEnd"
    STRING = "String"
    INTEGER = "Integer"
    FLOAT = "Float"
    BOOL = "Bool"
    NULL = "Null"
    COLON = "Colon"
    COMMA = "Comma"


class JsonToken:
    __slots__ = ('type', 'value')

    def __init__(self, token_type: JsonTokenType, value: Any = None):
        self.type = token_type
        self.value = value

    def __repr__(self) -> str:
        if self.value is not None:
            return f"JsonToken({self.type.value}, {self.value!r})"
        return f"JsonToken({self.type.value})"


def tokenize(input_str: str) -> List[JsonToken]:
    """Tokenize a JSON string into a list of tokens."""
    t = _JsonTokenizer(input_str)
    tokens = []
    while True:
        tok = t._next_token()
        if tok is None:
            break
        tokens.append(tok)
    return tokens


class _JsonTokenizer:
    def __init__(self, input_str: str):
        self._input = input_str
        self._pos = 0

    def _next_token(self) -> Optional[JsonToken]:
        self._skip_ws()
        if self._pos >= len(self._input):
            return None
        ch = self._input[self._pos]
        if ch == '{':
            self._pos += 1
            return JsonToken(JsonTokenType.OBJECT_START)
        if ch == '}':
            self._pos += 1
            return JsonToken(JsonTokenType.OBJECT_END)
        if ch == '[':
            self._pos += 1
            return JsonToken(JsonTokenType.ARRAY_START)
        if ch == ']':
            self._pos += 1
            return JsonToken(JsonTokenType.ARRAY_END)
        if ch == ':':
            self._pos += 1
            return JsonToken(JsonTokenType.COLON)
        if ch == ',':
            self._pos += 1
            return JsonToken(JsonTokenType.COMMA)
        if ch == '"':
            return JsonToken(JsonTokenType.STRING, self._read_string())
        if ch == 't':
            self._expect("true")
            return JsonToken(JsonTokenType.BOOL, True)
        if ch == 'f':
            self._expect("false")
            return JsonToken(JsonTokenType.BOOL, False)
        if ch == 'n':
            self._expect("null")
            return JsonToken(JsonTokenType.NULL)
        if ch == '-' or ch.isdigit():
            return self._read_number()
        raise SerdeError(SerdeErrorCode.SYNTAX_ERROR, f"unexpected character '{ch}'")

    def _read_string(self) -> str:
        self._pos += 1  # skip '"'
        parts = []
        start = self._pos
        while True:
            if self._pos >= len(self._input):
                raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unterminated string")
            ch = self._input[self._pos]
            if ch == '"':
                parts.append(self._input[start:self._pos])
                self._pos += 1
                return ''.join(parts)
            if ch == '\\':
                parts.append(self._input[start:self._pos])
                self._pos += 1
                if self._pos >= len(self._input):
                    raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unterminated escape")
                esc = self._input[self._pos]
                self._pos += 1
                if esc == '"': parts.append('"')
                elif esc == '\\': parts.append('\\')
                elif esc == '/': parts.append('/')
                elif esc == 'b': parts.append('\b')
                elif esc == 'f': parts.append('\f')
                elif esc == 'n': parts.append('\n')
                elif esc == 'r': parts.append('\r')
                elif esc == 't': parts.append('\t')
                elif esc == 'u':
                    h = self._input[self._pos:self._pos + 4]
                    self._pos += 4
                    parts.append(chr(int(h, 16)))
                else:
                    parts.append(esc)
                start = self._pos
            else:
                self._pos += 1

    def _read_number(self) -> JsonToken:
        start = self._pos
        if self._input[self._pos] == '-':
            self._pos += 1
        while self._pos < len(self._input) and self._input[self._pos].isdigit():
            self._pos += 1
        is_float = False
        if self._pos < len(self._input) and self._input[self._pos] == '.':
            is_float = True
            self._pos += 1
            while self._pos < len(self._input) and self._input[self._pos].isdigit():
                self._pos += 1
        if self._pos < len(self._input) and self._input[self._pos] in ('e', 'E'):
            is_float = True
            self._pos += 1
            if self._pos < len(self._input) and self._input[self._pos] in ('+', '-'):
                self._pos += 1
            while self._pos < len(self._input) and self._input[self._pos].isdigit():
                self._pos += 1
        raw = self._input[start:self._pos]
        if is_float:
            return JsonToken(JsonTokenType.FLOAT, float(raw))
        return JsonToken(JsonTokenType.INTEGER, int(raw))

    def _expect(self, s: str):
        if self._input[self._pos:self._pos + len(s)] != s:
            raise SerdeError(SerdeErrorCode.SYNTAX_ERROR, f"expected '{s}'")
        self._pos += len(s)

    def _skip_ws(self):
        while self._pos < len(self._input) and self._input[self._pos] in ' \t\r\n':
            self._pos += 1
