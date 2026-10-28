//! JSON codec (RFC 8259) — canonical, byte-precise (see SPEC).

use crate::error::SerdeError;
use crate::float::render_float;
use crate::value::Value;

/// Options for the JSON codec. `depth_limit` is the maximum container
/// nesting (outermost container is depth 1).
#[derive(Debug, Clone)]
pub struct JsonOptions {
    pub depth_limit: u32,
}

impl Default for JsonOptions {
    fn default() -> Self {
        JsonOptions {
            depth_limit: crate::DEFAULT_DEPTH_LIMIT,
        }
    }
}

const E_SYNTAX: &str = "SERDE_JSON_SYNTAX";
const E_UTF8: &str = "SERDE_JSON_UTF8";
const E_DEPTH: &str = "SERDE_JSON_DEPTH";
const E_TRAILING: &str = "SERDE_JSON_TRAILING";
const E_INT_RANGE: &str = "SERDE_JSON_INT_RANGE";
const E_FLOAT_NANINF: &str = "SERDE_JSON_FLOAT_NANINF";
const E_BYTES: &str = "SERDE_JSON_BYTES";
const E_DATETIME: &str = "SERDE_JSON_DATETIME";

fn err(code: &'static str, offset: usize, detail: &'static str) -> SerdeError {
    SerdeError::syntax(code, offset, detail)
}

/// Decode exactly one JSON value; trailing non-whitespace is an error.
pub fn json_decode(data: &[u8], opts: &JsonOptions) -> Result<Value, SerdeError> {
    let valid_end = match std::str::from_utf8(data) {
        Ok(_) => data.len(),
        Err(e) => e.valid_up_to(),
    };
    if valid_end != data.len() {
        return Err(err(E_UTF8, valid_end, "invalid UTF-8"));
    }
    let mut p = Parser {
        b: data,
        i: 0,
        limit: opts.depth_limit,
    };
    let v = p.parse_value(1)?;
    p.skip_ws();
    if p.i != data.len() {
        return Err(err(
            E_TRAILING,
            p.i,
            "trailing characters after the top-level value",
        ));
    }
    Ok(v)
}

/// Encode a value as canonical compact JSON: no whitespace, table keys
/// sorted bytewise, shortest-roundtrip floats.
pub fn json_encode(v: &Value, opts: &JsonOptions) -> Result<Vec<u8>, SerdeError> {
    let mut out = String::new();
    write_value(&mut out, v, 1, opts.depth_limit)?;
    Ok(out.into_bytes())
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
    limit: u32,
}

impl<'a> Parser<'a> {
    fn skip_ws(&mut self) {
        while self.i < self.b.len() && matches!(self.b[self.i], 0x20 | 0x09 | 0x0A | 0x0D) {
            self.i += 1;
        }
    }

    fn fail(&self, detail: &'static str) -> SerdeError {
        err(E_SYNTAX, self.i, detail)
    }

    fn parse_value(&mut self, depth: u32) -> Result<Value, SerdeError> {
        self.skip_ws();
        if self.i >= self.b.len() {
            return Err(self.fail("unexpected end of input"));
        }
        match self.b[self.i] {
            b'{' => {
                if depth > self.limit {
                    return Err(err(E_DEPTH, self.i, "depth limit exceeded"));
                }
                self.parse_object(depth)
            }
            b'[' => {
                if depth > self.limit {
                    return Err(err(E_DEPTH, self.i, "depth limit exceeded"));
                }
                self.parse_array(depth)
            }
            b'"' => Ok(Value::Str(self.parse_string()?)),
            b't' => {
                self.expect(b"true")?;
                Ok(Value::Bool(true))
            }
            b'f' => {
                self.expect(b"false")?;
                Ok(Value::Bool(false))
            }
            b'n' => {
                self.expect(b"null")?;
                Ok(Value::Null)
            }
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => Err(self.fail("unexpected character")),
        }
    }

    fn expect(&mut self, word: &[u8]) -> Result<(), SerdeError> {
        if self.b.len() - self.i < word.len() || &self.b[self.i..self.i + word.len()] != word {
            return Err(self.fail("invalid literal"));
        }
        self.i += word.len();
        Ok(())
    }

    fn parse_object(&mut self, depth: u32) -> Result<Value, SerdeError> {
        self.i += 1; // {
        let mut pairs: Vec<(String, Value)> = Vec::new();
        self.skip_ws();
        if self.i < self.b.len() && self.b[self.i] == b'}' {
            self.i += 1;
            return Ok(Value::table(pairs));
        }
        loop {
            self.skip_ws();
            if self.i >= self.b.len() || self.b[self.i] != b'"' {
                return Err(self.fail("expected object key"));
            }
            let k = self.parse_string()?;
            self.skip_ws();
            if self.i >= self.b.len() || self.b[self.i] != b':' {
                return Err(self.fail("expected ':'"));
            }
            self.i += 1;
            let v = self.parse_value(depth + 1)?;
            pairs.push((k, v));
            self.skip_ws();
            if self.i >= self.b.len() {
                return Err(self.fail("unterminated object"));
            }
            match self.b[self.i] {
                b',' => self.i += 1,
                b'}' => {
                    self.i += 1;
                    return Value::try_table(pairs)
                        .map_err(|_| err(E_SYNTAX, self.i, "duplicate object key"));
                }
                _ => return Err(self.fail("expected ',' or '}'")),
            }
        }
    }

    fn parse_array(&mut self, depth: u32) -> Result<Value, SerdeError> {
        self.i += 1; // [
        let mut items = Vec::new();
        self.skip_ws();
        if self.i < self.b.len() && self.b[self.i] == b']' {
            self.i += 1;
            return Ok(Value::Array(items));
        }
        loop {
            items.push(self.parse_value(depth + 1)?);
            self.skip_ws();
            if self.i >= self.b.len() {
                return Err(self.fail("unterminated array"));
            }
            match self.b[self.i] {
                b',' => self.i += 1,
                b']' => {
                    self.i += 1;
                    return Ok(Value::Array(items));
                }
                _ => return Err(self.fail("expected ',' or ']'")),
            }
        }
    }

    fn parse_string(&mut self) -> Result<String, SerdeError> {
        self.i += 1; // opening quote
        let mut out = String::new();
        loop {
            if self.i >= self.b.len() {
                return Err(self.fail("unterminated string"));
            }
            let c = self.b[self.i];
            if c == b'"' {
                self.i += 1;
                return Ok(out);
            }
            if c == b'\\' {
                self.i += 1;
                if self.i >= self.b.len() {
                    return Err(self.fail("unterminated escape"));
                }
                let e = self.b[self.i];
                match e {
                    b'"' => {
                        out.push('"');
                        self.i += 1;
                    }
                    b'\\' => {
                        out.push('\\');
                        self.i += 1;
                    }
                    b'/' => {
                        out.push('/');
                        self.i += 1;
                    }
                    b'b' => {
                        out.push('\u{0008}');
                        self.i += 1;
                    }
                    b'f' => {
                        out.push('\u{000C}');
                        self.i += 1;
                    }
                    b'n' => {
                        out.push('\n');
                        self.i += 1;
                    }
                    b'r' => {
                        out.push('\r');
                        self.i += 1;
                    }
                    b't' => {
                        out.push('\t');
                        self.i += 1;
                    }
                    b'u' => {
                        let cp = self.parse_hex4()?;
                        if (0xD800..=0xDBFF).contains(&cp) {
                            if self.i + 3 < self.b.len()
                                && self.b[self.i + 1] == b'\\'
                                && self.b[self.i + 2] == b'u'
                            {
                                self.i += 2;
                                let lo = self.parse_hex4()?;
                                if (0xDC00..=0xDFFF).contains(&lo) {
                                    let c = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                    out.push(char::from_u32(c).unwrap());
                                } else {
                                    return Err(self.fail("invalid low surrogate"));
                                }
                            } else {
                                return Err(self.fail("lone high surrogate"));
                            }
                        } else if (0xDC00..=0xDFFF).contains(&cp) {
                            return Err(self.fail("lone low surrogate"));
                        } else {
                            out.push(char::from_u32(cp).unwrap());
                        }
                    }
                    _ => return Err(self.fail("invalid escape")),
                }
                continue;
            }
            if c < 0x20 {
                return Err(self.fail("raw control character in string"));
            }
            // consume one UTF-8 code point (input is pre-validated)
            let n = if c < 0x80 {
                1
            } else if c < 0xE0 {
                2
            } else if c < 0xF0 {
                3
            } else {
                4
            };
            let s = std::str::from_utf8(&self.b[self.i..self.i + n]).expect("validated");
            out.push_str(s);
            self.i += n;
        }
    }

    fn parse_hex4(&mut self) -> Result<u32, SerdeError> {
        if self.i >= self.b.len() || self.b[self.i] != b'u' {
            return Err(self.fail("expected \\u"));
        }
        if self.i + 4 >= self.b.len() {
            return Err(self.fail("truncated \\u escape"));
        }
        let h = std::str::from_utf8(&self.b[self.i + 1..self.i + 5]).expect("validated");
        let cp = u32::from_str_radix(h, 16).map_err(|_| self.fail("invalid \\u escape"))?;
        self.i += 5;
        Ok(cp)
    }

    fn parse_number(&mut self) -> Result<Value, SerdeError> {
        let start = self.i;
        let b = self.b;
        if b[self.i] == b'-' {
            self.i += 1;
            if self.i >= b.len() {
                return Err(self.fail("unexpected end of input"));
            }
        }
        // integer part
        if b[self.i] == b'0' {
            self.i += 1;
        } else if b[self.i].is_ascii_digit() {
            while self.i < b.len() && b[self.i].is_ascii_digit() {
                self.i += 1;
            }
        } else {
            return Err(self.fail("invalid number"));
        }
        let mut is_float = false;
        if self.i < b.len() && b[self.i] == b'.' {
            is_float = true;
            self.i += 1;
            if self.i >= b.len() || !b[self.i].is_ascii_digit() {
                return Err(self.fail("expected digit after '.'"));
            }
            while self.i < b.len() && b[self.i].is_ascii_digit() {
                self.i += 1;
            }
        }
        if self.i < b.len() && (b[self.i] == b'e' || b[self.i] == b'E') {
            is_float = true;
            self.i += 1;
            if self.i < b.len() && (b[self.i] == b'+' || b[self.i] == b'-') {
                self.i += 1;
            }
            if self.i >= b.len() || !b[self.i].is_ascii_digit() {
                return Err(self.fail("expected digit in exponent"));
            }
            while self.i < b.len() && b[self.i].is_ascii_digit() {
                self.i += 1;
            }
        }
        let text = std::str::from_utf8(&b[start..self.i]).expect("validated");
        if !is_float {
            let n: i128 = text
                .parse()
                .map_err(|_| err(E_INT_RANGE, start, "integer out of 64-bit range"))?;
            if n >= i64::MIN as i128 && n <= i64::MAX as i128 {
                return Ok(Value::Int(n as i64));
            }
            if n >= 0 && n <= u64::MAX as i128 {
                return Ok(Value::UInt(n as u64));
            }
            return Err(err(E_INT_RANGE, start, "integer out of 64-bit range"));
        }
        let f: f64 = text
            .parse()
            .expect("RFC 8259 number is a valid f64 literal");
        Ok(Value::Float(f))
    }
}

fn write_value(out: &mut String, v: &Value, depth: u32, limit: u32) -> Result<(), SerdeError> {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Int(n) => out.push_str(&n.to_string()),
        Value::UInt(n) => out.push_str(&n.to_string()),
        Value::Float(f) => {
            if f.is_nan() || f.is_infinite() {
                return Err(SerdeError::new(
                    E_FLOAT_NANINF,
                    "non-finite float is not valid JSON",
                    None,
                ));
            }
            out.push_str(&render_float(*f));
        }
        Value::Str(s) => write_json_string(out, s),
        Value::Bytes(_) => {
            return Err(SerdeError::new(
                E_BYTES,
                "Bytes values cannot be encoded as JSON",
                None,
            ));
        }
        Value::Datetime(_) => {
            return Err(SerdeError::new(
                E_DATETIME,
                "Datetime values cannot be encoded as JSON",
                None,
            ));
        }
        Value::Array(items) => {
            if depth > limit {
                return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
            }
            out.push('[');
            for (i, x) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_value(out, x, depth + 1, limit)?;
            }
            out.push(']');
        }
        Value::Table(pairs) => {
            if depth > limit {
                return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
            }
            out.push('{');
            for (i, (k, x)) in pairs.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_json_string(out, k);
                out.push(':');
                write_value(out, x, depth + 1, limit)?;
            }
            out.push('}');
        }
    }
    Ok(())
}

fn write_json_string(out: &mut String, s: &str) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{0009}' => out.push_str("\\t"),
            '\u{000A}' => out.push_str("\\n"),
            '\u{000C}' => out.push_str("\\f"),
            '\u{000D}' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}
