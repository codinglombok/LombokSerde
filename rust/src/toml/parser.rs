//! TOML v1.0 parser.

use std::collections::BTreeMap;

use crate::error::SerdeError;
use crate::value::{Value, DateTime};

/// Parse a TOML string into a Value::Map.
pub fn parse(input: &str) -> Result<Value, SerdeError> {
    let mut parser = TomlParser::new(input);
    parser.parse()
}

struct TomlParser<'a> {
    input: &'a str,
    pos: usize,
    line: usize,
    col: usize,
}

impl<'a> TomlParser<'a> {
    fn new(input: &'a str) -> Self {
        Self { input, pos: 0, line: 1, col: 1 }
    }

    fn parse(&mut self) -> Result<Value, SerdeError> {
        let mut root = BTreeMap::new();
        let mut current_table: Vec<String> = Vec::new();

        loop {
            self.skip_whitespace_and_newlines();
            if self.is_eof() {
                break;
            }

            let ch = self.peek_char().unwrap();

            if ch == '#' {
                self.skip_comment();
                continue;
            }

            if ch == '[' {
                // Table or array-of-tables header
                self.advance_char();
                let is_array = if self.peek_char() == Some('[') {
                    self.advance_char();
                    true
                } else {
                    false
                };

                self.skip_ws();
                let keys = self.parse_key()?;
                self.skip_ws();

                if is_array {
                    self.expect_char(']')?;
                    self.expect_char(']')?;
                } else {
                    self.expect_char(']')?;
                }

                self.skip_ws();
                if let Some(c) = self.peek_char() {
                    if c != '\n' && c != '\r' && c != '#' {
                        return Err(self.error("extra characters after table header"));
                    }
                    if c == '#' {
                        self.skip_comment();
                    }
                }

                if is_array {
                    // Array of tables: ensure path exists and push a new table
                    ensure_array_of_tables(&mut root, &keys)?;
                } else {
                    ensure_table(&mut root, &keys)?;
                }
                current_table = keys;
                continue;
            }

            // Key-value pair
            let keys = self.parse_key()?;
            self.skip_ws();
            self.expect_char('=')?;
            self.skip_ws();
            let value = self.parse_value()?;
            self.skip_ws();
            if let Some(c) = self.peek_char() {
                if c == '#' {
                    self.skip_comment();
                } else if c != '\n' && c != '\r' {
                    return Err(self.error("expected newline after value"));
                }
            }

            // Insert into the correct table
            insert_value(&mut root, &current_table, &keys, value)?;
        }

        Ok(Value::Map(root))
    }

    fn parse_key(&mut self) -> Result<Vec<String>, SerdeError> {
        let mut keys = vec![self.parse_simple_key()?];
        loop {
            self.skip_ws();
            if self.peek_char() == Some('.') {
                self.advance_char();
                self.skip_ws();
                keys.push(self.parse_simple_key()?);
            } else {
                break;
            }
        }
        Ok(keys)
    }

    fn parse_simple_key(&mut self) -> Result<String, SerdeError> {
        match self.peek_char() {
            Some('"') => self.parse_basic_string(),
            Some('\'') => self.parse_literal_string(),
            Some(c) if is_bare_key_char(c) => self.parse_bare_key(),
            _ => Err(self.error("expected key")),
        }
    }

    fn parse_bare_key(&mut self) -> Result<String, SerdeError> {
        let start = self.pos;
        while let Some(c) = self.peek_char() {
            if is_bare_key_char(c) {
                self.advance_char();
            } else {
                break;
            }
        }
        if self.pos == start {
            return Err(self.error("empty bare key"));
        }
        Ok(self.input[start..self.pos].to_string())
    }

    fn parse_basic_string(&mut self) -> Result<String, SerdeError> {
        self.expect_char('"')?;
        // Check for multiline
        if self.peek_char() == Some('"') && self.input.get(self.pos + 1..self.pos + 2) == Some("\"") {
            self.advance_char();
            self.advance_char();
            return self.parse_multiline_basic_string();
        }
        let mut s = String::new();
        loop {
            match self.next_char()? {
                '"' => return Ok(s),
                '\\' => s.push(self.parse_escape()?),
                c if c < '\u{20}' && c != '\t' => return Err(self.error("control char in string")),
                c => s.push(c),
            }
        }
    }

    fn parse_multiline_basic_string(&mut self) -> Result<String, SerdeError> {
        // Skip first newline if present
        if self.peek_char() == Some('\n') {
            self.advance_char();
        } else if self.peek_char() == Some('\r') {
            self.advance_char();
            if self.peek_char() == Some('\n') {
                self.advance_char();
            }
        }
        let mut s = String::new();
        loop {
            if self.is_eof() {
                return Err(SerdeError::UnexpectedEof);
            }
            let c = self.next_char()?;
            if c == '"' && self.input.get(self.pos..self.pos + 2) == Some("\"\"") {
                self.advance_char();
                self.advance_char();
                return Ok(s);
            }
            if c == '\\' {
                // Line-ending backslash: skip whitespace and newlines
                let next = self.peek_char();
                if next == Some('\n') || next == Some('\r') {
                    self.skip_whitespace_and_newlines();
                    continue;
                }
                s.push(self.parse_escape()?);
            } else {
                s.push(c);
            }
        }
    }

    fn parse_literal_string(&mut self) -> Result<String, SerdeError> {
        self.expect_char('\'')?;
        // Check for multiline
        if self.peek_char() == Some('\'') && self.input.get(self.pos + 1..self.pos + 2) == Some("'") {
            self.advance_char();
            self.advance_char();
            return self.parse_multiline_literal_string();
        }
        let start = self.pos;
        loop {
            match self.next_char()? {
                '\'' => return Ok(self.input[start..self.pos - 1].to_string()),
                c if c < '\u{20}' && c != '\t' => return Err(self.error("control char in string")),
                _ => {}
            }
        }
    }

    fn parse_multiline_literal_string(&mut self) -> Result<String, SerdeError> {
        if self.peek_char() == Some('\n') {
            self.advance_char();
        } else if self.peek_char() == Some('\r') {
            self.advance_char();
            if self.peek_char() == Some('\n') { self.advance_char(); }
        }
        let mut s = String::new();
        loop {
            if self.is_eof() { return Err(SerdeError::UnexpectedEof); }
            let c = self.next_char()?;
            if c == '\'' && self.input.get(self.pos..self.pos + 2) == Some("''") {
                self.advance_char();
                self.advance_char();
                return Ok(s);
            }
            s.push(c);
        }
    }

    fn parse_escape(&mut self) -> Result<char, SerdeError> {
        match self.next_char()? {
            'b' => Ok('\u{08}'),
            't' => Ok('\t'),
            'n' => Ok('\n'),
            'f' => Ok('\u{0C}'),
            'r' => Ok('\r'),
            '"' => Ok('"'),
            '\\' => Ok('\\'),
            'u' => self.parse_unicode_escape(4),
            'U' => self.parse_unicode_escape(8),
            _ => Err(self.error("invalid escape")),
        }
    }

    fn parse_unicode_escape(&mut self, digits: usize) -> Result<char, SerdeError> {
        let mut val = 0u32;
        for _ in 0..digits {
            let c = self.next_char()?;
            let d = match c {
                '0'..='9' => c as u32 - '0' as u32,
                'a'..='f' => c as u32 - 'a' as u32 + 10,
                'A'..='F' => c as u32 - 'A' as u32 + 10,
                _ => return Err(self.error("invalid hex in unicode escape")),
            };
            val = (val << 4) | d;
        }
        char::from_u32(val).ok_or(SerdeError::InvalidUnicode)
    }

    fn parse_value(&mut self) -> Result<Value, SerdeError> {
        match self.peek_char() {
            Some('"') => {
                let s = self.parse_basic_string()?;
                Ok(Value::String(s))
            }
            Some('\'') => {
                let s = self.parse_literal_string()?;
                Ok(Value::String(s))
            }
            Some('t') => {
                self.expect_str("true")?;
                Ok(Value::Bool(true))
            }
            Some('f') => {
                self.expect_str("false")?;
                Ok(Value::Bool(false))
            }
            Some('[') => self.parse_array(),
            Some('{') => self.parse_inline_table(),
            Some(c) if c == '-' || c == '+' || c.is_ascii_digit() => self.parse_number_or_date(),
            Some('i') => {
                self.expect_str("inf")?;
                Ok(Value::Float(f64::INFINITY))
            }
            Some('n') => {
                self.expect_str("nan")?;
                Ok(Value::Float(f64::NAN))
            }
            _ => Err(self.error("expected value")),
        }
    }

    fn parse_array(&mut self) -> Result<Value, SerdeError> {
        self.expect_char('[')?;
        let mut arr = Vec::new();
        loop {
            self.skip_whitespace_newlines_comments();
            if self.peek_char() == Some(']') {
                self.advance_char();
                return Ok(Value::Array(arr));
            }
            arr.push(self.parse_value()?);
            self.skip_whitespace_newlines_comments();
            if self.peek_char() == Some(',') {
                self.advance_char();
            }
        }
    }

    fn parse_inline_table(&mut self) -> Result<Value, SerdeError> {
        self.expect_char('{')?;
        let mut map = BTreeMap::new();
        self.skip_ws();
        if self.peek_char() == Some('}') {
            self.advance_char();
            return Ok(Value::Map(map));
        }
        loop {
            self.skip_ws();
            let keys = self.parse_key()?;
            self.skip_ws();
            self.expect_char('=')?;
            self.skip_ws();
            let value = self.parse_value()?;

            insert_into_map(&mut map, &keys, value)?;

            self.skip_ws();
            if self.peek_char() == Some(',') {
                self.advance_char();
            } else {
                break;
            }
        }
        self.skip_ws();
        self.expect_char('}')?;
        Ok(Value::Map(map))
    }

    fn parse_number_or_date(&mut self) -> Result<Value, SerdeError> {
        let start = self.pos;

        // Check for sign
        let has_sign = self.peek_char() == Some('+') || self.peek_char() == Some('-');
        let sign = if has_sign {
            let s = self.peek_char().unwrap();
            self.advance_char();
            s
        } else {
            '+'
        };

        // Check for special float values
        if self.remaining().starts_with("inf") {
            self.pos += 3;
            return Ok(Value::Float(if sign == '-' { f64::NEG_INFINITY } else { f64::INFINITY }));
        }
        if self.remaining().starts_with("nan") {
            self.pos += 3;
            return Ok(Value::Float(f64::NAN));
        }

        // Read digits, possibly with underscores
        let num_start = self.pos;
        while let Some(c) = self.peek_char() {
            if c.is_ascii_digit() || c == '_' || c == '.' || c == 'e' || c == 'E'
                || c == '+' || c == '-' || c == 'T' || c == 't' || c == 'Z'
                || c == ':' || c == 'x' || c == 'o' || c == 'b'
                || matches!(c, 'a'..='f') || matches!(c, 'A'..='F')
            {
                self.advance_char();
            } else {
                break;
            }
        }

        let raw = &self.input[start..self.pos];
        let clean: String = raw.replace('_', "");

        // Try to detect datetime patterns
        if looks_like_datetime(&clean) {
            return parse_datetime(&clean);
        }

        // Hex, octal, binary
        let no_sign = if has_sign { &clean[1..] } else { &clean[..] };
        if no_sign.starts_with("0x") || no_sign.starts_with("0X") {
            let hex = &no_sign[2..];
            let n = i64::from_str_radix(hex, 16)
                .map_err(|_| self.error("invalid hex integer"))?;
            return Ok(Value::Integer(if sign == '-' { -n } else { n }));
        }
        if no_sign.starts_with("0o") || no_sign.starts_with("0O") {
            let oct = &no_sign[2..];
            let n = i64::from_str_radix(oct, 8)
                .map_err(|_| self.error("invalid octal integer"))?;
            return Ok(Value::Integer(if sign == '-' { -n } else { n }));
        }
        if no_sign.starts_with("0b") || no_sign.starts_with("0B") {
            let bin = &no_sign[2..];
            let n = i64::from_str_radix(bin, 2)
                .map_err(|_| self.error("invalid binary integer"))?;
            return Ok(Value::Integer(if sign == '-' { -n } else { n }));
        }

        // Float or integer
        if clean.contains('.') || clean.contains('e') || clean.contains('E') {
            let f: f64 = clean.parse()
                .map_err(|_| self.error("invalid float"))?;
            Ok(Value::Float(f))
        } else {
            let n: i64 = clean.parse()
                .map_err(|_| self.error("invalid integer"))?;
            Ok(Value::Integer(n))
        }
    }

    // --- Navigation helpers ---

    fn remaining(&self) -> &'a str {
        &self.input[self.pos..]
    }

    fn is_eof(&self) -> bool {
        self.pos >= self.input.len()
    }

    fn peek_char(&self) -> Option<char> {
        self.input[self.pos..].chars().next()
    }

    fn next_char(&mut self) -> Result<char, SerdeError> {
        let c = self.peek_char().ok_or(SerdeError::UnexpectedEof)?;
        self.advance_char();
        Ok(c)
    }

    fn advance_char(&mut self) {
        if let Some(c) = self.input[self.pos..].chars().next() {
            if c == '\n' {
                self.line += 1;
                self.col = 1;
            } else {
                self.col += 1;
            }
            self.pos += c.len_utf8();
        }
    }

    fn expect_char(&mut self, expected: char) -> Result<(), SerdeError> {
        let c = self.next_char()?;
        if c != expected {
            Err(self.error("unexpected character"))
        } else {
            Ok(())
        }
    }

    fn expect_str(&mut self, expected: &str) -> Result<(), SerdeError> {
        for ec in expected.chars() {
            self.expect_char(ec)?;
        }
        Ok(())
    }

    fn skip_ws(&mut self) {
        while let Some(c) = self.peek_char() {
            if c == ' ' || c == '\t' {
                self.advance_char();
            } else {
                break;
            }
        }
    }

    fn skip_whitespace_and_newlines(&mut self) {
        while let Some(c) = self.peek_char() {
            if c == ' ' || c == '\t' || c == '\n' || c == '\r' {
                self.advance_char();
            } else {
                break;
            }
        }
    }

    fn skip_whitespace_newlines_comments(&mut self) {
        loop {
            self.skip_whitespace_and_newlines();
            if self.peek_char() == Some('#') {
                self.skip_comment();
            } else {
                break;
            }
        }
    }

    fn skip_comment(&mut self) {
        while let Some(c) = self.peek_char() {
            self.advance_char();
            if c == '\n' {
                break;
            }
        }
    }

    fn error(&self, message: &'static str) -> SerdeError {
        SerdeError::syntax(message, self.line, self.col)
    }
}

fn is_bare_key_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-' || c == '_'
}

fn looks_like_datetime(s: &str) -> bool {
    // Simple heuristic: contains 'T' or ':' with digits around it, or matches date pattern
    let bytes = s.as_bytes();
    if bytes.len() >= 10 {
        // Check for YYYY-MM-DD pattern
        if bytes.len() >= 10
            && bytes[4] == b'-'
            && bytes[7] == b'-'
            && bytes[0].is_ascii_digit()
        {
            return true;
        }
    }
    // Time only: HH:MM:SS
    if bytes.len() >= 5 && bytes[2] == b':' && bytes[0].is_ascii_digit() {
        return true;
    }
    false
}

fn parse_datetime(s: &str) -> Result<Value, SerdeError> {
    // Offset datetime: contains T and Z/+/-
    if (s.contains('T') || s.contains('t')) && s.len() > 10 {
        let rest = &s[10..];
        if rest.contains('Z') || rest.contains('+') || rest.rfind('-').map_or(false, |i| i > 0) {
            return Ok(Value::DateTime(DateTime::OffsetDateTime(s.to_string())));
        }
        return Ok(Value::DateTime(DateTime::LocalDateTime(s.to_string())));
    }
    // Local date
    if s.len() == 10 && s.as_bytes()[4] == b'-' {
        return Ok(Value::DateTime(DateTime::LocalDate(s.to_string())));
    }
    // Local time
    if s.contains(':') && !s.contains('-') {
        return Ok(Value::DateTime(DateTime::LocalTime(s.to_string())));
    }
    Err(SerdeError::syntax_at_zero("ambiguous datetime"))
}

fn ensure_table(root: &mut BTreeMap<String, Value>, keys: &[String]) -> Result<(), SerdeError> {
    let mut current = root;
    for key in keys {
        if !current.contains_key(key) {
            current.insert(key.clone(), Value::Map(BTreeMap::new()));
        }
        match current.get_mut(key) {
            Some(Value::Map(m)) => current = m,
            Some(Value::Array(arr)) => {
                // Navigate into last element of array-of-tables
                match arr.last_mut() {
                    Some(Value::Map(m)) => current = m,
                    _ => return Err(SerdeError::DuplicateKey),
                }
            }
            _ => return Err(SerdeError::DuplicateKey),
        }
    }
    Ok(())
}

fn ensure_array_of_tables(root: &mut BTreeMap<String, Value>, keys: &[String]) -> Result<(), SerdeError> {
    let mut current = root;
    // Navigate to parent
    for key in &keys[..keys.len() - 1] {
        if !current.contains_key(key) {
            current.insert(key.clone(), Value::Map(BTreeMap::new()));
        }
        match current.get_mut(key) {
            Some(Value::Map(m)) => current = m,
            Some(Value::Array(arr)) => {
                match arr.last_mut() {
                    Some(Value::Map(m)) => current = m,
                    _ => return Err(SerdeError::DuplicateKey),
                }
            }
            _ => return Err(SerdeError::DuplicateKey),
        }
    }
    // Push new table to array at final key
    let last_key = &keys[keys.len() - 1];
    if !current.contains_key(last_key) {
        current.insert(last_key.clone(), Value::Array(vec![Value::Map(BTreeMap::new())]));
    } else {
        match current.get_mut(last_key) {
            Some(Value::Array(arr)) => {
                arr.push(Value::Map(BTreeMap::new()));
            }
            _ => return Err(SerdeError::DuplicateKey),
        }
    }
    Ok(())
}

fn insert_value(
    root: &mut BTreeMap<String, Value>,
    table_path: &[String],
    keys: &[String],
    value: Value,
) -> Result<(), SerdeError> {
    // Navigate to the current table
    let mut current = root;
    for key in table_path {
        match current.get_mut(key) {
            Some(Value::Map(m)) => current = m,
            Some(Value::Array(arr)) => {
                match arr.last_mut() {
                    Some(Value::Map(m)) => current = m,
                    _ => return Err(SerdeError::DuplicateKey),
                }
            }
            _ => return Err(SerdeError::DuplicateKey),
        }
    }
    insert_into_map(current, keys, value)
}

fn insert_into_map(
    map: &mut BTreeMap<String, Value>,
    keys: &[String],
    value: Value,
) -> Result<(), SerdeError> {
    if keys.len() == 1 {
        if map.contains_key(&keys[0]) {
            return Err(SerdeError::DuplicateKey);
        }
        map.insert(keys[0].clone(), value);
        Ok(())
    } else {
        if !map.contains_key(&keys[0]) {
            map.insert(keys[0].clone(), Value::Map(BTreeMap::new()));
        }
        match map.get_mut(&keys[0]) {
            Some(Value::Map(m)) => insert_into_map(m, &keys[1..], value),
            _ => Err(SerdeError::DuplicateKey),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_kv() {
        let v = parse("key = \"value\"\nnum = 42").unwrap();
        assert_eq!(v.get("key").unwrap().as_str().unwrap(), "value");
        assert_eq!(v.get("num").unwrap().as_integer().unwrap(), 42);
    }

    #[test]
    fn test_table() {
        let v = parse("[server]\nhost = \"localhost\"\nport = 8080").unwrap();
        let server = v.get("server").unwrap();
        assert_eq!(server.get("host").unwrap().as_str().unwrap(), "localhost");
        assert_eq!(server.get("port").unwrap().as_integer().unwrap(), 8080);
    }

    #[test]
    fn test_array_of_tables() {
        let v = parse("[[products]]\nname = \"A\"\n[[products]]\nname = \"B\"").unwrap();
        let products = v.get("products").unwrap().as_array().unwrap();
        assert_eq!(products.len(), 2);
        assert_eq!(products[0].get("name").unwrap().as_str().unwrap(), "A");
        assert_eq!(products[1].get("name").unwrap().as_str().unwrap(), "B");
    }

    #[test]
    fn test_inline_table() {
        let v = parse("point = {x = 1, y = 2}").unwrap();
        let pt = v.get("point").unwrap();
        assert_eq!(pt.get("x").unwrap().as_integer().unwrap(), 1);
        assert_eq!(pt.get("y").unwrap().as_integer().unwrap(), 2);
    }

    #[test]
    fn test_array() {
        let v = parse("arr = [1, 2, 3]").unwrap();
        let arr = v.get("arr").unwrap().as_array().unwrap();
        assert_eq!(arr.len(), 3);
    }

    #[test]
    fn test_bool() {
        let v = parse("flag = true\nother = false").unwrap();
        assert_eq!(v.get("flag").unwrap().as_bool().unwrap(), true);
        assert_eq!(v.get("other").unwrap().as_bool().unwrap(), false);
    }

    #[test]
    fn test_multiline_string() {
        let v = parse("s = \"\"\"\nhello\nworld\"\"\"").unwrap();
        assert_eq!(v.get("s").unwrap().as_str().unwrap(), "hello\nworld");
    }
}
