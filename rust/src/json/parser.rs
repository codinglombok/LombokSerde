//! JSON parser (RFC 8259) — recursive descent.

extern crate alloc;
use alloc::collections::BTreeMap;
use alloc::string::String;
use alloc::vec::Vec;

use crate::error::SerdeError;
use crate::value::Value;

/// JSON parser with configurable depth limit.
pub struct JsonParser<'a> {
    input: &'a [u8],
    pos: usize,
    line: usize,
    col: usize,
    max_depth: usize,
}

impl<'a> JsonParser<'a> {
    /// Create a new parser with default max depth (128).
    pub fn new(input: &'a [u8]) -> Self {
        Self {
            input,
            pos: 0,
            line: 1,
            col: 1,
            max_depth: 128,
        }
    }

    /// Set the maximum nesting depth.
    pub fn with_max_depth(mut self, depth: usize) -> Self {
        self.max_depth = depth;
        self
    }

    /// Parse the entire input as a JSON value.
    pub fn parse(&mut self) -> Result<Value, SerdeError> {
        self.skip_whitespace();
        let value = self.parse_value(0)?;
        self.skip_whitespace();
        if self.pos < self.input.len() {
            return Err(self.error("trailing data after JSON value"));
        }
        Ok(value)
    }

    fn parse_value(&mut self, depth: usize) -> Result<Value, SerdeError> {
        if depth > self.max_depth {
            return Err(SerdeError::DepthExceeded(self.max_depth));
        }
        self.skip_whitespace();
        match self.peek() {
            Some(b'"') => self.parse_string().map(Value::String),
            Some(b'{') => self.parse_object(depth),
            Some(b'[') => self.parse_array(depth),
            Some(b't') => self.parse_literal(b"true", Value::Bool(true)),
            Some(b'f') => self.parse_literal(b"false", Value::Bool(false)),
            Some(b'n') => self.parse_literal(b"null", Value::Null),
            Some(c) if c == b'-' || c.is_ascii_digit() => self.parse_number(),
            Some(_) => Err(self.error("unexpected character")),
            None => Err(SerdeError::UnexpectedEof),
        }
    }

    fn parse_string(&mut self) -> Result<String, SerdeError> {
        self.expect(b'"')?;
        let mut s = String::new();
        loop {
            match self.next_byte()? {
                b'"' => return Ok(s),
                b'\\' => {
                    let esc = self.next_byte()?;
                    match esc {
                        b'"' => s.push('"'),
                        b'\\' => s.push('\\'),
                        b'/' => s.push('/'),
                        b'b' => s.push('\u{08}'),
                        b'f' => s.push('\u{0C}'),
                        b'n' => s.push('\n'),
                        b'r' => s.push('\r'),
                        b't' => s.push('\t'),
                        b'u' => {
                            let cp = self.parse_hex4()?;
                            // Handle surrogate pairs
                            if (0xD800..=0xDBFF).contains(&cp) {
                                self.expect(b'\\')?;
                                self.expect(b'u')?;
                                let low = self.parse_hex4()?;
                                if !(0xDC00..=0xDFFF).contains(&low) {
                                    return Err(self.error("invalid surrogate pair"));
                                }
                                let combined = 0x10000
                                    + ((cp as u32 - 0xD800) << 10)
                                    + (low as u32 - 0xDC00);
                                match char::from_u32(combined) {
                                    Some(c) => s.push(c),
                                    None => return Err(SerdeError::InvalidUnicode),
                                }
                            } else if (0xDC00..=0xDFFF).contains(&cp) {
                                return Err(self.error("unexpected low surrogate"));
                            } else {
                                match char::from_u32(cp as u32) {
                                    Some(c) => s.push(c),
                                    None => return Err(SerdeError::InvalidUnicode),
                                }
                            }
                        }
                        _ => return Err(self.error("invalid escape sequence")),
                    }
                }
                b if b < 0x20 => return Err(self.error("control character in string")),
                b => {
                    // UTF-8 multi-byte handling
                    if b < 0x80 {
                        s.push(b as char);
                    } else {
                        // Collect full UTF-8 sequence
                        let start = self.pos - 1;
                        let width = if b < 0xE0 {
                            2
                        } else if b < 0xF0 {
                            3
                        } else {
                            4
                        };
                        // We already consumed the first byte
                        for _ in 1..width {
                            let cont = self.next_byte()?;
                            if cont & 0xC0 != 0x80 {
                                return Err(SerdeError::InvalidUnicode);
                            }
                        }
                        let end = self.pos;
                        match core::str::from_utf8(&self.input[start..end]) {
                            Ok(ch) => s.push_str(ch),
                            Err(_) => return Err(SerdeError::InvalidUnicode),
                        }
                    }
                }
            }
        }
    }

    fn parse_hex4(&mut self) -> Result<u16, SerdeError> {
        let mut val = 0u16;
        for _ in 0..4 {
            let b = self.next_byte()?;
            let digit = match b {
                b'0'..=b'9' => b - b'0',
                b'a'..=b'f' => b - b'a' + 10,
                b'A'..=b'F' => b - b'A' + 10,
                _ => return Err(self.error("invalid hex digit in \\uXXXX")),
            };
            val = (val << 4) | digit as u16;
        }
        Ok(val)
    }

    fn parse_number(&mut self) -> Result<Value, SerdeError> {
        let start = self.pos;
        let mut is_float = false;

        // Optional minus
        if self.peek() == Some(b'-') {
            self.advance();
        }

        // Integer part
        match self.peek() {
            Some(b'0') => {
                self.advance();
            }
            Some(c) if c >= b'1' && c <= b'9' => {
                self.advance();
                while let Some(c) = self.peek() {
                    if c.is_ascii_digit() {
                        self.advance();
                    } else {
                        break;
                    }
                }
            }
            _ => return Err(self.error("invalid number")),
        }

        // Fractional part
        if self.peek() == Some(b'.') {
            is_float = true;
            self.advance();
            if !self.peek().map_or(false, |c| c.is_ascii_digit()) {
                return Err(self.error("expected digit after decimal point"));
            }
            while let Some(c) = self.peek() {
                if c.is_ascii_digit() {
                    self.advance();
                } else {
                    break;
                }
            }
        }

        // Exponent
        if let Some(b'e' | b'E') = self.peek() {
            is_float = true;
            self.advance();
            if let Some(b'+' | b'-') = self.peek() {
                self.advance();
            }
            if !self.peek().map_or(false, |c| c.is_ascii_digit()) {
                return Err(self.error("expected digit in exponent"));
            }
            while let Some(c) = self.peek() {
                if c.is_ascii_digit() {
                    self.advance();
                } else {
                    break;
                }
            }
        }

        let text = core::str::from_utf8(&self.input[start..self.pos])
            .map_err(|_| self.error("invalid number encoding"))?;

        if is_float {
            let f: f64 = text
                .parse()
                .map_err(|_| self.error("invalid float literal"))?;
            Ok(Value::Float(f))
        } else {
            match text.parse::<i64>() {
                Ok(n) => Ok(Value::Integer(n)),
                Err(_) => {
                    // Fall back to float for numbers outside i64 range
                    let f: f64 = text
                        .parse()
                        .map_err(|_| self.error("number out of range"))?;
                    Ok(Value::Float(f))
                }
            }
        }
    }

    fn parse_object(&mut self, depth: usize) -> Result<Value, SerdeError> {
        self.expect(b'{')?;
        self.skip_whitespace();

        let mut map = BTreeMap::new();

        if self.peek() == Some(b'}') {
            self.advance();
            return Ok(Value::Map(map));
        }

        loop {
            self.skip_whitespace();
            let key = self.parse_string()?;
            self.skip_whitespace();
            self.expect(b':')?;
            let value = self.parse_value(depth + 1)?;

            if map.contains_key(&key) {
                return Err(SerdeError::DuplicateKey);
            }
            map.insert(key, value);

            self.skip_whitespace();
            match self.peek() {
                Some(b',') => {
                    self.advance();
                }
                Some(b'}') => {
                    self.advance();
                    return Ok(Value::Map(map));
                }
                _ => return Err(self.error("expected ',' or '}'")),
            }
        }
    }

    fn parse_array(&mut self, depth: usize) -> Result<Value, SerdeError> {
        self.expect(b'[')?;
        self.skip_whitespace();

        let mut arr = Vec::new();

        if self.peek() == Some(b']') {
            self.advance();
            return Ok(Value::Array(arr));
        }

        loop {
            let value = self.parse_value(depth + 1)?;
            arr.push(value);

            self.skip_whitespace();
            match self.peek() {
                Some(b',') => {
                    self.advance();
                }
                Some(b']') => {
                    self.advance();
                    return Ok(Value::Array(arr));
                }
                _ => return Err(self.error("expected ',' or ']'")),
            }
        }
    }

    fn parse_literal(&mut self, expected: &[u8], value: Value) -> Result<Value, SerdeError> {
        for &b in expected {
            let actual = self.next_byte()?;
            if actual != b {
                return Err(self.error("invalid literal"));
            }
        }
        Ok(value)
    }

    // --- Helper methods ---

    fn peek(&self) -> Option<u8> {
        self.input.get(self.pos).copied()
    }

    fn advance(&mut self) {
        if self.pos < self.input.len() {
            if self.input[self.pos] == b'\n' {
                self.line += 1;
                self.col = 1;
            } else {
                self.col += 1;
            }
            self.pos += 1;
        }
    }

    fn next_byte(&mut self) -> Result<u8, SerdeError> {
        if self.pos >= self.input.len() {
            return Err(SerdeError::UnexpectedEof);
        }
        let b = self.input[self.pos];
        self.advance();
        Ok(b)
    }

    fn expect(&mut self, byte: u8) -> Result<(), SerdeError> {
        let b = self.next_byte()?;
        if b != byte {
            Err(self.error("unexpected character"))
        } else {
            Ok(())
        }
    }

    fn skip_whitespace(&mut self) {
        while let Some(b) = self.peek() {
            match b {
                b' ' | b'\t' | b'\r' | b'\n' => self.advance(),
                _ => break,
            }
        }
    }

    fn error(&self, message: &'static str) -> SerdeError {
        SerdeError::syntax(message, self.line, self.col)
    }
}

/// Parse a JSON string into a Value.
pub fn parse(input: &str) -> Result<Value, SerdeError> {
    JsonParser::new(input.as_bytes()).parse()
}

/// Parse JSON bytes into a Value.
pub fn parse_bytes(input: &[u8]) -> Result<Value, SerdeError> {
    JsonParser::new(input).parse()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_null() {
        assert_eq!(parse("null").unwrap(), Value::Null);
    }

    #[test]
    fn test_parse_bool() {
        assert_eq!(parse("true").unwrap(), Value::Bool(true));
        assert_eq!(parse("false").unwrap(), Value::Bool(false));
    }

    #[test]
    fn test_parse_integer() {
        assert_eq!(parse("42").unwrap(), Value::Integer(42));
        assert_eq!(parse("-17").unwrap(), Value::Integer(-17));
        assert_eq!(parse("0").unwrap(), Value::Integer(0));
    }

    #[test]
    fn test_parse_float() {
        assert_eq!(parse("3.14").unwrap(), Value::Float(3.14));
        assert_eq!(parse("-0.5").unwrap(), Value::Float(-0.5));
        assert_eq!(parse("1e10").unwrap(), Value::Float(1e10));
        assert_eq!(parse("2.5E-3").unwrap(), Value::Float(2.5e-3));
    }

    #[test]
    fn test_parse_string() {
        assert_eq!(parse(r#""hello""#).unwrap(), Value::String("hello".into()));
        assert_eq!(parse(r#""a\nb""#).unwrap(), Value::String("a\nb".into()));
        assert_eq!(
            parse(r#""a\\b""#).unwrap(),
            Value::String("a\\b".into())
        );
    }

    #[test]
    fn test_parse_unicode_escape() {
        assert_eq!(
            parse(r#""A""#).unwrap(),
            Value::String("A".into())
        );
        // Surrogate pair for U+1F600 (😀)
        assert_eq!(
            parse(r#""😀""#).unwrap(),
            Value::String("😀".into())
        );
    }

    #[test]
    fn test_parse_array() {
        let v = parse("[1, 2, 3]").unwrap();
        assert_eq!(
            v,
            Value::Array(vec![
                Value::Integer(1),
                Value::Integer(2),
                Value::Integer(3),
            ])
        );
    }

    #[test]
    fn test_parse_object() {
        let v = parse(r#"{"a": 1, "b": "hello"}"#).unwrap();
        let mut map = BTreeMap::new();
        map.insert("a".into(), Value::Integer(1));
        map.insert("b".into(), Value::String("hello".into()));
        assert_eq!(v, Value::Map(map));
    }

    #[test]
    fn test_parse_nested() {
        let v = parse(r#"{"arr": [1, null, true], "obj": {"x": 2}}"#).unwrap();
        assert!(v.get("arr").unwrap().as_array().is_some());
        assert!(v.get("obj").unwrap().get("x").is_some());
    }

    #[test]
    fn test_parse_empty() {
        assert_eq!(parse("{}").unwrap(), Value::Map(BTreeMap::new()));
        assert_eq!(parse("[]").unwrap(), Value::Array(vec![]));
    }

    #[test]
    fn test_depth_limit() {
        let deep = "[".repeat(200) + &"]".repeat(200);
        assert!(matches!(
            parse(&deep),
            Err(SerdeError::DepthExceeded(_))
        ));
    }

    #[test]
    fn test_duplicate_key() {
        assert!(matches!(
            parse(r#"{"a": 1, "a": 2}"#),
            Err(SerdeError::DuplicateKey)
        ));
    }
}
