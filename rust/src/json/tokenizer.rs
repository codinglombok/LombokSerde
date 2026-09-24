//! Streaming JSON tokenizer — token-by-token without full DOM.

extern crate alloc;
use alloc::string::String;

use crate::error::SerdeError;

/// JSON token types.
#[derive(Debug, Clone, PartialEq)]
pub enum JsonToken {
    /// Start of object `{`
    ObjectStart,
    /// End of object `}`
    ObjectEnd,
    /// Start of array `[`
    ArrayStart,
    /// End of array `]`
    ArrayEnd,
    /// String value (also object keys)
    String(String),
    /// Integer value
    Integer(i64),
    /// Float value
    Float(f64),
    /// Boolean value
    Bool(bool),
    /// Null value
    Null,
    /// Colon separator `:`
    Colon,
    /// Comma separator `,`
    Comma,
}

/// Streaming JSON tokenizer.
pub struct JsonTokenizer<'a> {
    input: &'a [u8],
    pos: usize,
    line: usize,
    col: usize,
}

impl<'a> JsonTokenizer<'a> {
    /// Create a new tokenizer.
    pub fn new(input: &'a [u8]) -> Self {
        Self {
            input,
            pos: 0,
            line: 1,
            col: 1,
        }
    }

    /// Read the next token, or None if end of input.
    pub fn next_token(&mut self) -> Result<Option<JsonToken>, SerdeError> {
        self.skip_whitespace();
        if self.pos >= self.input.len() {
            return Ok(None);
        }

        let b = self.input[self.pos];
        match b {
            b'{' => { self.advance(); Ok(Some(JsonToken::ObjectStart)) }
            b'}' => { self.advance(); Ok(Some(JsonToken::ObjectEnd)) }
            b'[' => { self.advance(); Ok(Some(JsonToken::ArrayStart)) }
            b']' => { self.advance(); Ok(Some(JsonToken::ArrayEnd)) }
            b':' => { self.advance(); Ok(Some(JsonToken::Colon)) }
            b',' => { self.advance(); Ok(Some(JsonToken::Comma)) }
            b'"' => self.read_string().map(|s| Some(JsonToken::String(s))),
            b't' => self.read_literal(b"true").map(|_| Some(JsonToken::Bool(true))),
            b'f' => self.read_literal(b"false").map(|_| Some(JsonToken::Bool(false))),
            b'n' => self.read_literal(b"null").map(|_| Some(JsonToken::Null)),
            b'-' | b'0'..=b'9' => self.read_number().map(Some),
            _ => Err(self.error("unexpected character")),
        }
    }

    /// Collect all remaining tokens.
    pub fn collect_all(&mut self) -> Result<alloc::vec::Vec<JsonToken>, SerdeError> {
        let mut tokens = alloc::vec::Vec::new();
        while let Some(tok) = self.next_token()? {
            tokens.push(tok);
        }
        Ok(tokens)
    }

    fn read_string(&mut self) -> Result<String, SerdeError> {
        self.advance(); // skip opening quote
        let mut s = String::new();
        loop {
            if self.pos >= self.input.len() {
                return Err(SerdeError::UnexpectedEof);
            }
            let b = self.input[self.pos];
            self.advance();
            match b {
                b'"' => return Ok(s),
                b'\\' => {
                    if self.pos >= self.input.len() {
                        return Err(SerdeError::UnexpectedEof);
                    }
                    let esc = self.input[self.pos];
                    self.advance();
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
                            let cp = self.read_hex4()?;
                            if (0xD800..=0xDBFF).contains(&cp) {
                                if self.pos + 1 < self.input.len()
                                    && self.input[self.pos] == b'\\'
                                    && self.input[self.pos + 1] == b'u'
                                {
                                    self.advance();
                                    self.advance();
                                    let low = self.read_hex4()?;
                                    if (0xDC00..=0xDFFF).contains(&low) {
                                        let combined = 0x10000
                                            + ((cp as u32 - 0xD800) << 10)
                                            + (low as u32 - 0xDC00);
                                        if let Some(c) = char::from_u32(combined) {
                                            s.push(c);
                                        } else {
                                            return Err(SerdeError::InvalidUnicode);
                                        }
                                    } else {
                                        return Err(self.error("invalid surrogate pair"));
                                    }
                                } else {
                                    return Err(self.error("expected low surrogate"));
                                }
                            } else {
                                if let Some(c) = char::from_u32(cp as u32) {
                                    s.push(c);
                                } else {
                                    return Err(SerdeError::InvalidUnicode);
                                }
                            }
                        }
                        _ => return Err(self.error("invalid escape")),
                    }
                }
                b if b < 0x20 => return Err(self.error("control character in string")),
                b if b < 0x80 => s.push(b as char),
                b => {
                    let start = self.pos - 1;
                    let width = if b < 0xE0 { 2 } else if b < 0xF0 { 3 } else { 4 };
                    for _ in 1..width {
                        if self.pos >= self.input.len() {
                            return Err(SerdeError::UnexpectedEof);
                        }
                        self.advance();
                    }
                    match core::str::from_utf8(&self.input[start..self.pos]) {
                        Ok(ch) => s.push_str(ch),
                        Err(_) => return Err(SerdeError::InvalidUnicode),
                    }
                }
            }
        }
    }

    fn read_hex4(&mut self) -> Result<u16, SerdeError> {
        let mut val = 0u16;
        for _ in 0..4 {
            if self.pos >= self.input.len() {
                return Err(SerdeError::UnexpectedEof);
            }
            let b = self.input[self.pos];
            self.advance();
            let digit = match b {
                b'0'..=b'9' => b - b'0',
                b'a'..=b'f' => b - b'a' + 10,
                b'A'..=b'F' => b - b'A' + 10,
                _ => return Err(self.error("invalid hex digit")),
            };
            val = (val << 4) | digit as u16;
        }
        Ok(val)
    }

    fn read_number(&mut self) -> Result<JsonToken, SerdeError> {
        let start = self.pos;
        let mut is_float = false;

        if self.pos < self.input.len() && self.input[self.pos] == b'-' {
            self.advance();
        }

        if self.pos < self.input.len() && self.input[self.pos] == b'0' {
            self.advance();
        } else {
            while self.pos < self.input.len() && self.input[self.pos].is_ascii_digit() {
                self.advance();
            }
        }

        if self.pos < self.input.len() && self.input[self.pos] == b'.' {
            is_float = true;
            self.advance();
            while self.pos < self.input.len() && self.input[self.pos].is_ascii_digit() {
                self.advance();
            }
        }

        if self.pos < self.input.len() && (self.input[self.pos] == b'e' || self.input[self.pos] == b'E') {
            is_float = true;
            self.advance();
            if self.pos < self.input.len() && (self.input[self.pos] == b'+' || self.input[self.pos] == b'-') {
                self.advance();
            }
            while self.pos < self.input.len() && self.input[self.pos].is_ascii_digit() {
                self.advance();
            }
        }

        let text = core::str::from_utf8(&self.input[start..self.pos])
            .map_err(|_| self.error("invalid number"))?;

        if is_float {
            let f: f64 = text.parse().map_err(|_| self.error("invalid float"))?;
            Ok(JsonToken::Float(f))
        } else {
            match text.parse::<i64>() {
                Ok(n) => Ok(JsonToken::Integer(n)),
                Err(_) => {
                    let f: f64 = text.parse().map_err(|_| self.error("number out of range"))?;
                    Ok(JsonToken::Float(f))
                }
            }
        }
    }

    fn read_literal(&mut self, expected: &[u8]) -> Result<(), SerdeError> {
        for &b in expected {
            if self.pos >= self.input.len() {
                return Err(SerdeError::UnexpectedEof);
            }
            if self.input[self.pos] != b {
                return Err(self.error("invalid literal"));
            }
            self.advance();
        }
        Ok(())
    }

    fn skip_whitespace(&mut self) {
        while self.pos < self.input.len() {
            match self.input[self.pos] {
                b' ' | b'\t' | b'\r' | b'\n' => self.advance(),
                _ => break,
            }
        }
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

    fn error(&self, message: &'static str) -> SerdeError {
        SerdeError::syntax(message, self.line, self.col)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tokenize_simple() {
        let mut t = JsonTokenizer::new(b"[1, true, null]");
        let tokens = t.collect_all().unwrap();
        assert_eq!(tokens, vec![
            JsonToken::ArrayStart,
            JsonToken::Integer(1),
            JsonToken::Comma,
            JsonToken::Bool(true),
            JsonToken::Comma,
            JsonToken::Null,
            JsonToken::ArrayEnd,
        ]);
    }

    #[test]
    fn test_tokenize_object() {
        let mut t = JsonTokenizer::new(br#"{"key": "value"}"#);
        let tokens = t.collect_all().unwrap();
        assert_eq!(tokens, vec![
            JsonToken::ObjectStart,
            JsonToken::String("key".into()),
            JsonToken::Colon,
            JsonToken::String("value".into()),
            JsonToken::ObjectEnd,
        ]);
    }
}
