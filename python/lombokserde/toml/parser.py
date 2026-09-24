"""TOML v1.0 parser."""

import re
from ..error import SerdeError, SerdeErrorCode
from ..value import DateTimeValue


def parse(input_str: str) -> dict:
    """Parse a TOML string into a dict."""
    p = _TomlParser(input_str)
    return p.parse()


def _is_bare_key_char(ch: str) -> bool:
    return ch.isalnum() or ch == '_' or ch == '-'


def _looks_like_datetime(s: str) -> bool:
    if len(s) >= 10 and s[4] == '-' and s[7] == '-' and s[0].isdigit():
        return True
    if len(s) >= 5 and s[2] == ':' and s[0].isdigit():
        return True
    return False


def _parse_datetime(s: str) -> DateTimeValue:
    if ('T' in s or 't' in s) and len(s) > 10:
        rest = s[10:]
        if 'Z' in rest or '+' in rest or rest.rfind('-') > 0:
            return DateTimeValue('offset', s)
        return DateTimeValue('local-datetime', s)
    if len(s) == 10 and s[4] == '-':
        return DateTimeValue('local-date', s)
    if ':' in s and '-' not in s:
        return DateTimeValue('local-time', s)
    return DateTimeValue('local-datetime', s)


class _TomlParser:
    def __init__(self, input_str: str):
        self._input = input_str
        self._pos = 0

    def parse(self) -> dict:
        root = {}
        current_path = []

        while True:
            self._skip_ws_newlines()
            if self._pos >= len(self._input):
                break

            ch = self._input[self._pos]
            if ch == '#':
                self._skip_comment()
                continue

            if ch == '[':
                self._pos += 1
                is_array = self._pos < len(self._input) and self._input[self._pos] == '['
                if is_array:
                    self._pos += 1
                self._skip_ws()
                keys = self._parse_key()
                self._skip_ws()
                if is_array:
                    self._expect(']')
                    self._expect(']')
                else:
                    self._expect(']')
                self._skip_ws()
                if self._pos < len(self._input) and self._input[self._pos] == '#':
                    self._skip_comment()

                if is_array:
                    self._ensure_array_of_tables(root, keys)
                else:
                    self._ensure_table(root, keys)
                current_path = keys
                continue

            # Key-value pair
            keys = self._parse_key()
            self._skip_ws()
            self._expect('=')
            self._skip_ws()
            value = self._parse_value()
            self._skip_ws()
            if self._pos < len(self._input) and self._input[self._pos] == '#':
                self._skip_comment()

            self._insert_value(root, current_path, keys, value)

        return root

    def _parse_key(self) -> list:
        keys = [self._parse_simple_key()]
        while True:
            self._skip_ws()
            if self._pos < len(self._input) and self._input[self._pos] == '.':
                self._pos += 1
                self._skip_ws()
                keys.append(self._parse_simple_key())
            else:
                break
        return keys

    def _parse_simple_key(self) -> str:
        if self._pos >= len(self._input):
            raise self._eof()
        ch = self._input[self._pos]
        if ch == '"':
            return self._parse_basic_string()
        if ch == "'":
            return self._parse_literal_string()
        return self._parse_bare_key()

    def _parse_bare_key(self) -> str:
        start = self._pos
        while self._pos < len(self._input) and _is_bare_key_char(self._input[self._pos]):
            self._pos += 1
        if self._pos == start:
            raise self._error("empty bare key")
        return self._input[start:self._pos]

    def _parse_basic_string(self) -> str:
        self._expect('"')
        if (self._pos + 1 < len(self._input)
                and self._input[self._pos] == '"'
                and self._input[self._pos + 1] == '"'):
            self._pos += 2
            return self._parse_multiline_basic_string()
        s = []
        while True:
            if self._pos >= len(self._input):
                raise self._eof()
            ch = self._input[self._pos]
            self._pos += 1
            if ch == '"':
                return ''.join(s)
            if ch == '\\':
                s.append(self._parse_escape())
            else:
                s.append(ch)

    def _parse_multiline_basic_string(self) -> str:
        if self._pos < len(self._input) and self._input[self._pos] == '\n':
            self._pos += 1
        elif self._pos < len(self._input) and self._input[self._pos] == '\r':
            self._pos += 1
            if self._pos < len(self._input) and self._input[self._pos] == '\n':
                self._pos += 1
        s = []
        while True:
            if self._pos >= len(self._input):
                raise self._eof()
            ch = self._input[self._pos]
            self._pos += 1
            if ch == '"' and self._input[self._pos:self._pos + 2] == '""':
                self._pos += 2
                return ''.join(s)
            if ch == '\\':
                nxt = self._input[self._pos] if self._pos < len(self._input) else ''
                if nxt in ('\n', '\r'):
                    self._skip_ws_newlines()
                    continue
                s.append(self._parse_escape())
                continue
            s.append(ch)

    def _parse_literal_string(self) -> str:
        self._expect("'")
        if (self._pos + 1 < len(self._input)
                and self._input[self._pos] == "'"
                and self._input[self._pos + 1] == "'"):
            self._pos += 2
            return self._parse_multiline_literal_string()
        start = self._pos
        while self._pos < len(self._input) and self._input[self._pos] != "'":
            self._pos += 1
        s = self._input[start:self._pos]
        self._expect("'")
        return s

    def _parse_multiline_literal_string(self) -> str:
        if self._pos < len(self._input) and self._input[self._pos] == '\n':
            self._pos += 1
        elif self._pos < len(self._input) and self._input[self._pos] == '\r':
            self._pos += 1
            if self._pos < len(self._input) and self._input[self._pos] == '\n':
                self._pos += 1
        s = []
        while True:
            if self._pos >= len(self._input):
                raise self._eof()
            ch = self._input[self._pos]
            self._pos += 1
            if ch == "'" and self._input[self._pos:self._pos + 2] == "''":
                self._pos += 2
                return ''.join(s)
            s.append(ch)

    def _parse_escape(self) -> str:
        if self._pos >= len(self._input):
            raise self._eof()
        ch = self._input[self._pos]
        self._pos += 1
        esc_map = {'b': '\b', 't': '\t', 'n': '\n', 'f': '\f', 'r': '\r', '"': '"', '\\': '\\'}
        if ch in esc_map:
            return esc_map[ch]
        if ch == 'u':
            return self._parse_unicode_escape(4)
        if ch == 'U':
            return self._parse_unicode_escape(8)
        raise self._error("invalid escape")

    def _parse_unicode_escape(self, digits: int) -> str:
        hex_str = self._input[self._pos:self._pos + digits]
        self._pos += digits
        try:
            cp = int(hex_str, 16)
        except ValueError:
            raise self._error("invalid unicode escape")
        return chr(cp)

    def _parse_value(self):
        if self._pos >= len(self._input):
            raise self._eof()
        ch = self._input[self._pos]
        if ch == '"':
            return self._parse_basic_string()
        if ch == "'":
            return self._parse_literal_string()
        if ch == 't':
            self._expect_str("true")
            return True
        if ch == 'f':
            self._expect_str("false")
            return False
        if ch == '[':
            return self._parse_array()
        if ch == '{':
            return self._parse_inline_table()
        if ch == 'i':
            self._expect_str("inf")
            return float('inf')
        if ch == 'n' and self._input[self._pos:self._pos + 3] == 'nan':
            self._pos += 3
            return float('nan')
        if ch == '-' or ch == '+' or ch.isdigit():
            return self._parse_number_or_date()
        raise self._error("expected value")

    def _parse_array(self) -> list:
        self._expect('[')
        arr = []
        while True:
            self._skip_ws_newlines_comments()
            if self._pos < len(self._input) and self._input[self._pos] == ']':
                self._pos += 1
                return arr
            arr.append(self._parse_value())
            self._skip_ws_newlines_comments()
            if self._pos < len(self._input) and self._input[self._pos] == ',':
                self._pos += 1

    def _parse_inline_table(self) -> dict:
        self._expect('{')
        result = {}
        self._skip_ws()
        if self._pos < len(self._input) and self._input[self._pos] == '}':
            self._pos += 1
            return result
        while True:
            self._skip_ws()
            keys = self._parse_key()
            self._skip_ws()
            self._expect('=')
            self._skip_ws()
            value = self._parse_value()
            self._insert_into_map(result, keys, value)
            self._skip_ws()
            if self._pos < len(self._input) and self._input[self._pos] == ',':
                self._pos += 1
            else:
                break
        self._skip_ws()
        self._expect('}')
        return result

    def _parse_number_or_date(self):
        start = self._pos
        sign = self._input[self._pos]
        if sign in ('+', '-'):
            self._pos += 1

        # Special floats
        if self._input[self._pos:self._pos + 3] == 'inf':
            self._pos += 3
            return float('-inf') if sign == '-' else float('inf')
        if self._input[self._pos:self._pos + 3] == 'nan':
            self._pos += 3
            return float('nan')

        while self._pos < len(self._input):
            c = self._input[self._pos]
            if re.match(r'[0-9a-fA-F_.:\+\-TtZxXoObB]', c):
                self._pos += 1
            else:
                break

        raw = self._input[start:self._pos]
        clean = raw.replace('_', '')

        if _looks_like_datetime(clean):
            return _parse_datetime(clean)

        no_sign = clean.lstrip('+-') if sign in ('+', '-') else clean
        mult = -1 if sign == '-' else 1

        if no_sign.startswith(('0x', '0X')):
            return int(no_sign, 16) * mult
        if no_sign.startswith(('0o', '0O')):
            return int(no_sign[2:], 8) * mult
        if no_sign.startswith(('0b', '0B')):
            return int(no_sign[2:], 2) * mult

        if '.' in clean or 'e' in clean or 'E' in clean:
            return float(clean)
        return int(clean, 10)

    # --- Table navigation ---

    def _ensure_table(self, root: dict, keys: list):
        current = root
        for key in keys:
            if key not in current:
                current[key] = {}
            val = current[key]
            if isinstance(val, list):
                current = val[-1]
            elif isinstance(val, dict):
                current = val
            else:
                raise SerdeError(SerdeErrorCode.DUPLICATE_KEY, "duplicate key")

    def _ensure_array_of_tables(self, root: dict, keys: list):
        current = root
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            val = current[key]
            if isinstance(val, list):
                current = val[-1]
            elif isinstance(val, dict):
                current = val
            else:
                raise SerdeError(SerdeErrorCode.DUPLICATE_KEY, "duplicate key")
        last_key = keys[-1]
        if last_key not in current:
            current[last_key] = [{}]
        else:
            val = current[last_key]
            if isinstance(val, list):
                val.append({})
            else:
                raise SerdeError(SerdeErrorCode.DUPLICATE_KEY, "duplicate key")

    def _insert_value(self, root: dict, table_path: list, keys: list, value):
        current = root
        for key in table_path:
            val = current[key]
            if isinstance(val, list):
                current = val[-1]
            else:
                current = val
        self._insert_into_map(current, keys, value)

    def _insert_into_map(self, m: dict, keys: list, value):
        if len(keys) == 1:
            if keys[0] in m:
                raise SerdeError(SerdeErrorCode.DUPLICATE_KEY, "duplicate key")
            m[keys[0]] = value
        else:
            if keys[0] not in m:
                m[keys[0]] = {}
            sub = m[keys[0]]
            if isinstance(sub, dict):
                self._insert_into_map(sub, keys[1:], value)
            else:
                raise SerdeError(SerdeErrorCode.DUPLICATE_KEY, "duplicate key")

    # --- Helpers ---

    def _expect(self, ch: str):
        if self._pos >= len(self._input) or self._input[self._pos] != ch:
            raise self._error(f"expected '{ch}'")
        self._pos += 1

    def _expect_str(self, s: str):
        for i, c in enumerate(s):
            if self._pos + i >= len(self._input) or self._input[self._pos + i] != c:
                raise self._error(f"expected '{s}'")
        self._pos += len(s)

    def _skip_ws(self):
        while self._pos < len(self._input) and self._input[self._pos] in (' ', '\t'):
            self._pos += 1

    def _skip_ws_newlines(self):
        while self._pos < len(self._input) and self._input[self._pos] in (' ', '\t', '\r', '\n'):
            self._pos += 1

    def _skip_ws_newlines_comments(self):
        while True:
            self._skip_ws_newlines()
            if self._pos < len(self._input) and self._input[self._pos] == '#':
                self._skip_comment()
            else:
                break

    def _skip_comment(self):
        while self._pos < len(self._input) and self._input[self._pos] != '\n':
            self._pos += 1
        if self._pos < len(self._input):
            self._pos += 1

    def _error(self, msg: str) -> SerdeError:
        return SerdeError(SerdeErrorCode.SYNTAX_ERROR, msg)

    def _eof(self) -> SerdeError:
        return SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected end of input")
