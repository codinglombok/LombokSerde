//! TOML v1.0 codec — canonical, byte-precise (see SPEC).
//!
//! Decode implements the TOML v1.0 core grammar: bare/quoted/dotted keys,
//! basic/literal/multiline strings, decimal/hex/octal/binary integers with
//! underscores, floats with `inf`/`nan`, the four datetime kinds, arrays,
//! inline tables, tables and arrays-of-tables, with the spec's redefinition
//! rules (fail-closed). Encode emits the canonical form: scalars first
//! (sorted), then `[sub-tables]` (sorted), then `[[array-of-tables]]`
//! (sorted); all arrays are single-line inline arrays.

use crate::error::SerdeError;
use crate::float::render_float;
use crate::value::{Datetime, DatetimeKind, Value};
use std::collections::BTreeMap;

/// Options for the TOML codec.
#[derive(Debug, Clone)]
pub struct TomlOptions {
    pub depth_limit: u32,
}

impl Default for TomlOptions {
    fn default() -> Self {
        TomlOptions {
            depth_limit: crate::DEFAULT_DEPTH_LIMIT,
        }
    }
}

const E_SYNTAX: &str = "SERDE_TOML_SYNTAX";
const E_UTF8: &str = "SERDE_TOML_UTF8";
const E_DUPLICATE: &str = "SERDE_TOML_DUPLICATE";
const E_DEPTH: &str = "SERDE_TOML_DEPTH";
const E_ROOT: &str = "SERDE_TOML_ROOT";
const E_BYTES: &str = "SERDE_TOML_BYTES";
const E_DATETIME: &str = "SERDE_TOML_DATETIME";

fn err(code: &'static str, offset: usize, detail: &'static str) -> SerdeError {
    SerdeError::syntax(code, offset, detail)
}

/// Decode a TOML document into a table value.
pub fn toml_decode(data: &[u8], opts: &TomlOptions) -> Result<Value, SerdeError> {
    let valid_end = match std::str::from_utf8(data) {
        Ok(_) => data.len(),
        Err(e) => e.valid_up_to(),
    };
    if valid_end != data.len() {
        return Err(err(E_UTF8, valid_end, "invalid UTF-8"));
    }
    let mut p = TomlParser::new(data, opts.depth_limit);
    p.parse()
}

/// Encode a table value as canonical TOML. The root must be a table.
pub fn toml_encode(v: &Value, opts: &TomlOptions) -> Result<Vec<u8>, SerdeError> {
    let mut out = String::new();
    match v {
        Value::Table(_) => emit_table(v, &[], &mut out, 1, opts.depth_limit)?,
        _ => {
            return Err(SerdeError::new(
                E_ROOT,
                "TOML documents encode from a table root",
                None,
            ))
        }
    }
    Ok(out.into_bytes())
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    Implicit,
    Explicit,
    Dotted,
    Aot,
}

struct Node {
    state: State,
    pairs: BTreeMap<String, Value>,
    elems: Option<Vec<Node>>,
}

impl Node {
    fn new(state: State) -> Self {
        Node {
            state,
            pairs: BTreeMap::new(),
            elems: None,
        }
    }
}

struct TomlParser<'a> {
    b: &'a [u8],
    i: usize,
    limit: u32,
    root: BTreeMap<Vec<String>, Node>,
    cur: Vec<String>,
}

fn is_pseudo(seg: &str) -> bool {
    seg.starts_with('#')
}

impl<'a> TomlParser<'a> {
    fn new(b: &'a [u8], limit: u32) -> Self {
        let mut root = BTreeMap::new();
        root.insert(Vec::new(), Node::new(State::Explicit));
        TomlParser {
            b,
            i: 0,
            limit,
            root,
            cur: Vec::new(),
        }
    }

    fn fail(&self, detail: &'static str) -> SerdeError {
        err(E_SYNTAX, self.i, detail)
    }

    fn dup(&self) -> SerdeError {
        err(E_DUPLICATE, self.i, "duplicate key or table definition")
    }

    fn peek(&self) -> Option<u8> {
        self.b.get(self.i).copied()
    }

    fn skip_inline_ws(&mut self) {
        while matches!(self.peek(), Some(0x20) | Some(0x09)) {
            self.i += 1;
        }
    }

    fn skip_comment(&mut self) {
        if self.peek() == Some(b'#') {
            while !matches!(self.peek(), None | Some(0x0A) | Some(0x0D)) {
                self.i += 1;
            }
        }
    }

    fn expect_line_end(&mut self) -> Result<(), SerdeError> {
        self.skip_inline_ws();
        self.skip_comment();
        match self.peek() {
            None => Ok(()),
            Some(0x0A) => {
                self.i += 1;
                Ok(())
            }
            Some(0x0D) => {
                self.i += 1;
                if self.peek() == Some(0x0A) {
                    self.i += 1;
                }
                Ok(())
            }
            Some(_) => Err(self.fail("expected end of line")),
        }
    }

    fn parse(&mut self) -> Result<Value, SerdeError> {
        loop {
            self.skip_inline_ws();
            match self.peek() {
                None => break,
                Some(0x0A) => {
                    self.i += 1;
                    continue;
                }
                Some(0x0D) => {
                    self.i += 1;
                    if self.peek() == Some(0x0A) {
                        self.i += 1;
                    }
                    continue;
                }
                Some(0x23) => {
                    self.skip_comment();
                    continue;
                }
                Some(0x5B) => {
                    if self.b.get(self.i + 1) == Some(&0x5B) {
                        self.parse_aot_header()?;
                    } else {
                        self.parse_table_header()?;
                    }
                }
                Some(_) => self.parse_keyval()?,
            }
            self.expect_line_end()?;
        }
        self.to_value(&[], 1)
    }

    // --- headers -----------------------------------------------------------

    fn parse_table_header(&mut self) -> Result<(), SerdeError> {
        let start = self.i;
        self.i += 1; // [
        let path = self.parse_key_path()?;
        self.skip_inline_ws();
        if self.peek() != Some(0x5D) {
            return Err(self.fail("expected ']'"));
        }
        self.i += 1;
        if (path.len() as u32) + 1 > self.limit {
            return Err(err(E_DEPTH, start, "depth limit exceeded"));
        }
        self.define_table(&path)?;
        self.cur = path;
        Ok(())
    }

    fn parse_aot_header(&mut self) -> Result<(), SerdeError> {
        let start = self.i;
        self.i += 2; // [[
        let path = self.parse_key_path()?;
        self.skip_inline_ws();
        if self.peek() != Some(0x5D) || self.b.get(self.i + 1) != Some(&0x5D) {
            return Err(self.fail("expected ']]'"));
        }
        self.i += 2;
        if (path.len() as u32) + 1 > self.limit {
            return Err(err(E_DEPTH, start, "depth limit exceeded"));
        }
        self.define_aot(&path)?;
        self.cur = path;
        Ok(())
    }

    fn resolve(&self, path: &[String]) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for seg in path {
            if let Some(node) = self.root.get(&out) {
                if node.state == State::Aot {
                    let n = node.elems.as_ref().map(|e| e.len()).unwrap_or(1);
                    out.push(format!("#{}", n - 1));
                }
            }
            out.push(seg.clone());
        }
        out
    }

    fn define_table(&mut self, path: &[String]) -> Result<(), SerdeError> {
        let concrete = self.resolve(path);
        for j in 1..=concrete.len() {
            if is_pseudo(&concrete[j - 1]) {
                continue;
            }
            let sp = concrete[..j].to_vec();
            match self.root.get(&sp).map(|n| n.state) {
                None => {
                    self.root.insert(sp, Node::new(State::Implicit));
                }
                Some(State::Dotted) => {
                    return Err(err(
                        E_DUPLICATE,
                        self.i,
                        "dotted-key table redefined by header",
                    ));
                }
                _ => {}
            }
        }
        if !self.root.contains_key(&concrete) {
            self.root
                .insert(concrete.clone(), Node::new(State::Explicit));
            return Ok(());
        }
        let node = self.root.get_mut(&concrete).unwrap();
        match node.state {
            State::Implicit => {
                node.state = State::Explicit;
                Ok(())
            }
            _ => Err(self.dup()),
        }
    }

    fn define_aot(&mut self, path: &[String]) -> Result<(), SerdeError> {
        let concrete = self.resolve(path);
        for j in 1..=concrete.len() {
            if is_pseudo(&concrete[j - 1]) {
                continue;
            }
            let sp = concrete[..j].to_vec();
            match self.root.get(&sp).map(|n| n.state) {
                None => {
                    self.root.insert(sp, Node::new(State::Implicit));
                }
                Some(State::Dotted) => {
                    return Err(err(
                        E_DUPLICATE,
                        self.i,
                        "dotted-key table redefined by header",
                    ));
                }
                _ => {}
            }
        }
        if !self.root.contains_key(&concrete) {
            return Err(self.dup());
        }
        let node = self.root.get_mut(&concrete).unwrap();
        match node.state {
            State::Aot => {
                node.elems
                    .as_mut()
                    .unwrap()
                    .push(Node::new(State::Explicit));
            }
            State::Implicit => {
                node.state = State::Aot;
                node.elems = Some(vec![Node::new(State::Explicit)]);
            }
            _ => return Err(self.dup()),
        }
        Ok(())
    }

    // --- keys ---------------------------------------------------------------

    fn parse_key_path(&mut self) -> Result<Vec<String>, SerdeError> {
        let mut keys = Vec::new();
        self.skip_inline_ws();
        loop {
            keys.push(self.parse_single_key()?);
            self.skip_inline_ws();
            if self.peek() == Some(0x2E) {
                self.i += 1;
                self.skip_inline_ws();
                continue;
            }
            break;
        }
        Ok(keys)
    }

    fn parse_single_key(&mut self) -> Result<String, SerdeError> {
        match self.peek() {
            None => Err(self.fail("expected key")),
            Some(0x22) => {
                let k = self.parse_basic_string()?;
                Self::check_reserved(&k, self.i)?;
                Ok(k)
            }
            Some(0x27) => {
                let k = self.parse_literal_string()?;
                Self::check_reserved(&k, self.i)?;
                Ok(k)
            }
            Some(_) => {
                let s = self.i;
                while self.peek().is_some_and(is_bare_key_byte) {
                    self.i += 1;
                }
                if self.i == s {
                    return Err(self.fail("invalid key"));
                }
                Ok(String::from_utf8_lossy(&self.b[s..self.i]).into_owned())
            }
        }
    }

    /// '#'-prefixed keys are reserved: they collide with the internal
    /// array-of-tables element markers (fail-closed v1 restriction).
    fn check_reserved(key: &str, at: usize) -> Result<(), SerdeError> {
        if key.starts_with('#') {
            return Err(err(E_SYNTAX, at, "keys starting with '#' are reserved"));
        }
        Ok(())
    }

    // --- keyval ---------------------------------------------------------------

    fn parse_keyval(&mut self) -> Result<(), SerdeError> {
        let keys = self.parse_key_path()?;
        self.skip_inline_ws();
        if self.peek() != Some(0x3D) {
            return Err(self.fail("expected '='"));
        }
        self.i += 1;
        self.skip_inline_ws();
        let v = self.parse_value((self.cur.len() + keys.len() + 1) as u32)?;
        let base = self.resolve(&self.cur);
        let inter = keys[..keys.len().saturating_sub(1)].to_vec();
        if !inter.is_empty()
            && self.root.get(&base).map(|n| n.state) == Some(State::Aot)
        {
            // v1: dotted keys cannot extend array-of-tables elements
            return Err(err(
                E_SYNTAX,
                self.i,
                "dotted keys cannot extend array-of-tables elements",
            ));
        }
        // dotted intermediates: create or descend; explicit tables reject extension
        for j in 1..=inter.len() {
            let mut sp = base.clone();
            sp.extend_from_slice(&inter[..j]);
            if is_pseudo(sp.last().map(|s| s.as_str()).unwrap_or("")) {
                continue; // AoT element markers have no node of their own
            }
            match self.root.get(&sp).map(|n| n.state) {
                None => {
                    self.root.insert(sp, Node::new(State::Dotted));
                }
                Some(State::Explicit) => {
                    return Err(err(
                        E_DUPLICATE,
                        self.i,
                        "dotted key extends a header-defined table",
                    ));
                }
                _ => {}
            }
        }
        let mut parent_path = base;
        parent_path.extend_from_slice(&inter);
        let last = keys.last().unwrap().clone();
        let leaf = {
            let mut leaf = parent_path.clone();
            leaf.push(last.clone());
            leaf
        };
        if self.root.contains_key(&leaf) {
            return Err(self.dup());
        }
        if !self.root.contains_key(&parent_path) {
            self.root
                .insert(parent_path.clone(), Node::new(State::Dotted));
        }
        let node = self.root.get_mut(&parent_path).unwrap();
        if node.state == State::Aot {
            // keyvals directly under [[a]] write into the most recent element
            let elem = node.elems.as_mut().unwrap().last_mut().unwrap();
            if elem.pairs.contains_key(&last) {
                return Err(self.dup());
            }
            elem.pairs.insert(last, v);
            return Ok(());
        }
        if node.pairs.contains_key(&last) {
            return Err(self.dup());
        }
        node.pairs.insert(last, v);
        Ok(())
    }

    // --- values ---------------------------------------------------------------

    fn parse_value(&mut self, depth: u32) -> Result<Value, SerdeError> {
        let c = match self.peek() {
            None => return Err(self.fail("expected value")),
            Some(c) => c,
        };
        match c {
            0x22 => {
                if self.b[self.i..].starts_with(b"\"\"\"") {
                    Ok(Value::Str(self.parse_ml_basic()?))
                } else {
                    Ok(Value::Str(self.parse_basic_string()?))
                }
            }
            0x27 => {
                if self.b[self.i..].starts_with(b"'''") {
                    Ok(Value::Str(self.parse_ml_literal()?))
                } else {
                    Ok(Value::Str(self.parse_literal_string()?))
                }
            }
            0x5B => self.parse_array(depth),
            0x7B => self.parse_inline_table(depth),
            _ => {
                if self.b[self.i..].starts_with(b"true") {
                    self.i += 4;
                    Ok(Value::Bool(true))
                } else if self.b[self.i..].starts_with(b"false") {
                    self.i += 5;
                    Ok(Value::Bool(false))
                } else {
                    self.parse_number_or_datetime(depth)
                }
            }
        }
    }

    fn parse_array(&mut self, depth: u32) -> Result<Value, SerdeError> {
        self.i += 1; // [
        let mut items = Vec::new();
        loop {
            self.skip_array_ws();
            match self.peek() {
                None => return Err(self.fail("unterminated array")),
                Some(0x5D) => {
                    self.i += 1;
                    return Ok(Value::Array(items));
                }
                _ => {}
            }
            items.push(self.parse_value(depth + 1)?);
            self.skip_array_ws();
            match self.peek() {
                Some(0x2C) => {
                    self.i += 1;
                }
                Some(0x5D) => {
                    self.i += 1;
                    return Ok(Value::Array(items));
                }
                _ => return Err(self.fail("expected ',' or ']'")),
            }
        }
    }

    fn skip_array_ws(&mut self) {
        loop {
            match self.peek() {
                Some(0x20 | 0x09 | 0x0A | 0x0D) => self.i += 1,
                Some(0x23) => {
                    while !matches!(self.peek(), None | Some(0x0A) | Some(0x0D)) {
                        self.i += 1;
                    }
                }
                _ => break,
            }
        }
    }

    fn parse_inline_table(&mut self, depth: u32) -> Result<Value, SerdeError> {
        if depth > self.limit {
            return Err(err(E_DEPTH, self.i, "depth limit exceeded"));
        }
        self.i += 1; // {
        let mut pairs: Vec<(String, Value)> = Vec::new();
        self.skip_inline_ws();
        if self.peek() == Some(0x7D) {
            self.i += 1;
            return Ok(Value::table(pairs));
        }
        loop {
            self.skip_inline_ws();
            let keys = self.parse_key_path()?;
            self.skip_inline_ws();
            if self.peek() != Some(0x3D) {
                return Err(self.fail("expected '='"));
            }
            self.i += 1;
            self.skip_inline_ws();
            let v = self.parse_value(depth + 1)?;
            if keys.len() > 1 {
                let v = nest_dotted(&keys[1..], v);
                pairs.push((keys[0].clone(), v));
            } else {
                pairs.push((keys[0].clone(), v));
            }
            self.skip_inline_ws();
            match self.peek() {
                Some(0x2C) => {
                    self.i += 1;
                }
                Some(0x7D) => {
                    self.i += 1;
                    return Value::try_table(pairs)
                        .map_err(|_| err(E_SYNTAX, self.i - 1, "duplicate key in inline table"));
                }
                _ => return Err(self.fail("expected ',' or '}' in inline table")),
            }
        }
    }

    fn parse_basic_string(&mut self) -> Result<String, SerdeError> {
        self.i += 1; // "
        let mut out = String::new();
        loop {
            let c = match self.peek() {
                None => return Err(self.fail("unterminated string")),
                Some(c) => c,
            };
            if c == 0x22 {
                self.i += 1;
                return Ok(out);
            }
            if c == 0x0A || c == 0x0D {
                return Err(self.fail("newline in basic string"));
            }
            if c == 0x5C {
                self.i += 1;
                self.parse_escape_into(&mut out)?;
                continue;
            }
            if c < 0x20 && c != 0x09 {
                return Err(self.fail("raw control character in string"));
            }
            self.take_utf8_char(&mut out);
        }
    }

    fn parse_escape_into(&mut self, out: &mut String) -> Result<(), SerdeError> {
        let e = match self.peek() {
            None => return Err(self.fail("unterminated escape")),
            Some(e) => e,
        };
        match e {
            b'b' => {
                out.push('\u{0008}');
                self.i += 1;
            }
            b't' => {
                out.push('\t');
                self.i += 1;
            }
            b'n' => {
                out.push('\n');
                self.i += 1;
            }
            b'f' => {
                out.push('\u{000C}');
                self.i += 1;
            }
            b'r' => {
                out.push('\r');
                self.i += 1;
            }
            b'"' => {
                out.push('"');
                self.i += 1;
            }
            b'\\' => {
                out.push('\\');
                self.i += 1;
            }
            b'u' | b'U' => {
                let width = if e == b'u' { 4 } else { 8 };
                self.i += 1;
                if self.i + width > self.b.len() {
                    return Err(self.fail("truncated unicode escape"));
                }
                let h = std::str::from_utf8(&self.b[self.i..self.i + width]).expect("validated");
                let cp =
                    u32::from_str_radix(h, 16).map_err(|_| self.fail("invalid unicode escape"))?;
                let ch = char::from_u32(cp).ok_or_else(|| self.fail("invalid scalar value"))?;
                out.push(ch);
                self.i += width;
            }
            0x0A | 0x0D | 0x20 | 0x09 => {
                // possible line-ending backslash (multiline strings only):
                // \ + whitespace* + at least one newline trims everything
                let mut j = self.i;
                let mut saw_nl = false;
                while j < self.b.len() && matches!(self.b[j], 0x20 | 0x09 | 0x0D | 0x0A) {
                    if matches!(self.b[j], 0x0A | 0x0D) {
                        saw_nl = true;
                    }
                    j += 1;
                }
                if saw_nl {
                    self.i = j;
                } else {
                    return Err(self.fail("invalid escape"));
                }
            }
            _ => return Err(self.fail("invalid escape")),
        }
        Ok(())
    }

    fn take_utf8_char(&mut self, out: &mut String) {
        let c = self.b[self.i];
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

    fn parse_literal_string(&mut self) -> Result<String, SerdeError> {
        self.i += 1; // '
        let s = self.i;
        loop {
            match self.peek() {
                None => return Err(self.fail("unterminated string")),
                Some(0x27) => {
                    let r = String::from_utf8_lossy(&self.b[s..self.i]).into_owned();
                    self.i += 1;
                    return Ok(r);
                }
                Some(c) if (c < 0x20 && c != 0x09) || c == 0x7F => {
                    return Err(self.fail("raw control character in literal string"));
                }
                Some(_) => self.i += 1,
            }
        }
    }

    fn parse_ml_basic(&mut self) -> Result<String, SerdeError> {
        self.i += 3;
        if self.peek() == Some(0x0A) {
            self.i += 1;
        } else if self.b[self.i..].starts_with(b"\r\n") {
            self.i += 2;
        }
        let mut out = String::new();
        loop {
            if self.i >= self.b.len() {
                return Err(self.fail("unterminated multiline string"));
            }
            if self.b[self.i..].starts_with(b"\"\"\"") {
                self.i += 3;
                let mut extra = 0;
                while self.peek() == Some(0x22) && extra < 2 {
                    out.push('"');
                    self.i += 1;
                    extra += 1;
                }
                return Ok(out);
            }
            if self.b[self.i] == 0x5C {
                self.i += 1;
                self.parse_escape_into(&mut out)?;
                continue;
            }
            let c = self.b[self.i];
            if c < 0x20 && !matches!(c, 0x09 | 0x0A | 0x0D) {
                return Err(self.fail("raw control character in multiline string"));
            }
            self.take_utf8_char(&mut out);
        }
    }

    fn parse_ml_literal(&mut self) -> Result<String, SerdeError> {
        self.i += 3;
        if self.peek() == Some(0x0A) {
            self.i += 1;
        } else if self.b[self.i..].starts_with(b"\r\n") {
            self.i += 2;
        }
        let s = self.i;
        loop {
            if self.i >= self.b.len() {
                return Err(self.fail("unterminated multiline string"));
            }
            if self.b[self.i..].starts_with(b"'''") {
                let r = String::from_utf8_lossy(&self.b[s..self.i]).into_owned();
                self.i += 3;
                return Ok(r);
            }
            let c = self.b[self.i];
            if c < 0x20 && !matches!(c, 0x09 | 0x0A | 0x0D) {
                return Err(self.fail("raw control character in multiline string"));
            }
            self.i += 1;
        }
    }

    // --- numbers & datetimes --------------------------------------------------

    fn parse_number_or_datetime(&mut self, _depth: u32) -> Result<Value, SerdeError> {
        let start = self.i;
        match self.scan_datetime() {
            Ok(Some((kind, end))) => {
                let raw = String::from_utf8_lossy(&self.b[start..end]).into_owned();
                self.i = end;
                return Ok(Value::Datetime(Datetime::new(kind, raw)));
            }
            Ok(None) => {}
            Err(e) => return Err(e),
        }
        let mut sign = 1i64;
        let mut sign_seen = false;
        if matches!(self.peek(), Some(0x2B) | Some(0x2D)) {
            if self.peek() == Some(0x2D) {
                sign = -1;
            }
            sign_seen = true;
            self.i += 1;
        }
        if self.b[self.i..].starts_with(b"inf") {
            self.i += 3;
            return Ok(Value::Float(if sign < 0 {
                f64::NEG_INFINITY
            } else {
                f64::INFINITY
            }));
        }
        if self.b[self.i..].starts_with(b"nan") {
            self.i += 3;
            return Ok(Value::Float(f64::NAN));
        }
        let digits_start = self.i;
        self.read_digits(10)?;
        let b = self.b;
        let base = if self.i - digits_start == 1
            && b[digits_start] == b'0'
            && self.peek() == Some(0x78)
        {
            Some(16u32)
        } else if self.i - digits_start == 1 && b[digits_start] == b'0' && self.peek() == Some(0x6F)
        {
            Some(8)
        } else if self.i - digits_start == 1 && b[digits_start] == b'0' && self.peek() == Some(0x62)
        {
            Some(2)
        } else {
            None
        };
        if let Some(base) = base {
            if sign_seen {
                return Err(self.fail("signs are not allowed on hex/oct/bin integers"));
            }
            self.i += 1;
            self.read_digits(base)?;
            let text = String::from_utf8_lossy(&self.b[digits_start + 2..self.i]).replace('_', "");
            let n = i128::from_str_radix(&text, base)
                .map_err(|_| err(E_SYNTAX, start, "integer out of 64-bit range"))?;
            let v = sign as i128 * n;
            if v < i64::MIN as i128 || v > i64::MAX as i128 {
                return Err(err(E_SYNTAX, start, "integer out of 64-bit range"));
            }
            return Ok(Value::Int(v as i64));
        }
        let mut is_float = false;
        if self.peek() == Some(0x2E) {
            is_float = true;
            self.i += 1;
            self.read_digits(10)?;
        }
        if matches!(self.peek(), Some(0x65) | Some(0x45)) {
            is_float = true;
            self.i += 1;
            if matches!(self.peek(), Some(0x2B) | Some(0x2D)) {
                self.i += 1;
            }
            if !self.peek().map(|c| c.is_ascii_digit()).unwrap_or(false) {
                return Err(self.fail("expected digit in exponent"));
            }
            self.read_digits(10)?;
        }
        let text = String::from_utf8_lossy(&self.b[digits_start..self.i]).replace('_', "");
        if !is_float {
            if text.len() > 1 && text.starts_with('0') {
                return Err(self.fail("leading zero in integer"));
            }
            // parse with the sign applied via i128 so i64::MIN round-trips
            let signed = if sign < 0 { format!("-{}", text) } else { text };
            let m: i128 = signed
                .parse()
                .map_err(|_| err(E_SYNTAX, start, "integer out of 64-bit range"))?;
            if m < i64::MIN as i128 || m > i64::MAX as i128 {
                return Err(err(E_SYNTAX, start, "integer out of 64-bit range"));
            }
            return Ok(Value::Int(m as i64));
        }
        let f: f64 = text.parse().map_err(|_| self.fail("invalid float"))?;
        Ok(Value::Float(f))
    }

    fn read_digits(&mut self, base: u32) -> Result<(), SerdeError> {
        let allowed: fn(u8) -> bool = match base {
            10 => |c: u8| c.is_ascii_digit(),
            16 => |c: u8| c.is_ascii_hexdigit(),
            8 => |c: u8| (b'0'..=b'7').contains(&c),
            _ => |c: u8| c == b'0' || c == b'1',
        };
        let mut count = 0;
        while self.i < self.b.len() {
            let c = self.b[self.i];
            if allowed(c) {
                count += 1;
                self.i += 1;
            } else if c == 0x5F {
                if count == 0 {
                    return Err(self.fail("leading underscore"));
                }
                let next_ok = self.b.get(self.i + 1).map(|&n| allowed(n)).unwrap_or(false);
                if !next_ok {
                    return Err(self.fail("trailing underscore"));
                }
                self.i += 1;
            } else {
                break;
            }
        }
        if count == 0 {
            return Err(self.fail("expected digit"));
        }
        Ok(())
    }

    fn scan_datetime(&mut self) -> Result<Option<(DatetimeKind, usize)>, SerdeError> {
        let i = self.i;
        let n = self.b.len();
        let mut j = i;
        while j < n && matches!(self.b[j], b'0'..=b'9' | b'-' | b':') {
            j += 1;
        }
        let seg = String::from_utf8_lossy(&self.b[i..j]).into_owned();
        let has_dash = seg.contains('-');
        let has_colon = seg.contains(':');
        if !has_dash && !has_colon {
            return Ok(None);
        }
        if has_dash && !has_colon {
            if j - i != 10 {
                return Ok(None);
            }
            if j < n && matches!(self.b[j], b'T' | b't' | 0x20) {
                let m = j + 1;
                let mut k = m;
                while k < n && matches!(self.b[k], b'0'..=b'9' | b':') {
                    k += 1;
                }
                let tseg = String::from_utf8_lossy(&self.b[m..k]).into_owned();
                if !tseg.contains(':') {
                    return self.validate_datetime(i, j, DatetimeKind::LocalDate);
                }
                let (end, had_zone) = match self.scan_frac_zone(k) {
                    Some(x) => x,
                    None => return Ok(None),
                };
                let kind = if had_zone {
                    DatetimeKind::Offset
                } else {
                    DatetimeKind::LocalDateTime
                };
                return self.validate_datetime(i, end, kind);
            }
            return self.validate_datetime(i, j, DatetimeKind::LocalDate);
        }
        if has_colon && !has_dash {
            let mut k = j;
            if k < n && self.b[k] == 0x2E {
                k += 1;
                if k < n && self.b[k].is_ascii_digit() {
                    while k < n && self.b[k].is_ascii_digit() {
                        k += 1;
                    }
                } else {
                    return Ok(None);
                }
            }
            return self.validate_datetime(i, k, DatetimeKind::LocalTime);
        }
        Ok(None)
    }

    fn scan_frac_zone(&self, k: usize) -> Option<(usize, bool)> {
        let n = self.b.len();
        let mut end = k;
        if end < n && self.b[end] == 0x2E {
            end += 1;
            if end < n && self.b[end].is_ascii_digit() {
                while end < n && self.b[end].is_ascii_digit() {
                    end += 1;
                }
            } else {
                return None;
            }
        }
        if end < n && matches!(self.b[end], b'Z' | b'z') {
            return Some((end + 1, true));
        }
        if end + 6 <= n && matches!(self.b[end], b'+' | b'-') && self.b[end + 3] == b':' {
            return Some((end + 6, true));
        }
        Some((end, false))
    }

    fn validate_datetime(
        &self,
        s: usize,
        end: usize,
        kind: DatetimeKind,
    ) -> Result<Option<(DatetimeKind, usize)>, SerdeError> {
        let text = String::from_utf8_lossy(&self.b[s..end]).into_owned();
        if datetime_ok(&text, kind) {
            Ok(Some((kind, end)))
        } else {
            // the token has datetime shape but is invalid: fail at its start
            Err(err(E_SYNTAX, s, "invalid datetime"))
        }
    }

    // --- tree -> Value -----------------------------------------------------------

    fn to_value(&self, path: &[String], depth: u32) -> Result<Value, SerdeError> {
        let node = self
            .root
            .get(path)
            .ok_or_else(|| self.fail("missing table"))?;
        if node.state == State::Aot {
            let mut elems = Vec::new();
            for (idx, el) in node.elems.as_ref().unwrap().iter().enumerate() {
                let mut base = path.to_vec();
                base.push(format!("#{}", idx));
                elems.push(self.collect_from(&el.pairs, &base, depth)?);
            }
            return Ok(Value::Array(elems));
        }
        self.collect(path, depth)
    }

    fn collect(&self, base_path: &[String], depth: u32) -> Result<Value, SerdeError> {
        let node = self
            .root
            .get(base_path)
            .ok_or_else(|| self.fail("missing table"))?;
        self.collect_from(&node.pairs, base_path, depth)
    }

    fn collect_from(
        &self,
        pairs: &BTreeMap<String, Value>,
        base_path: &[String],
        depth: u32,
    ) -> Result<Value, SerdeError> {
        let mut out: Vec<(String, Value)> =
            pairs.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        // child tables whose parent path is base_path
        for p in self.root.keys() {
            if p.len() != base_path.len() + 1 || !p.starts_with(base_path) {
                continue;
            }
            let k = p.last().unwrap();
            if is_pseudo(k) {
                continue;
            }
            if out.iter().any(|(pk, _)| pk == k) {
                return Err(err(E_DUPLICATE, self.i, "table and value share a key"));
            }
            out.push((k.clone(), self.to_value(p, depth + 1)?));
        }
        out.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        Ok(Value::Table(out))
    }
}

fn nest_dotted(keys: &[String], v: Value) -> Value {
    let mut inner = v;
    for k in keys.iter().rev() {
        inner = Value::table(vec![(k.clone(), inner)]);
    }
    inner
}

fn is_bare_key_byte(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_' || c == b'-'
}
pub fn datetime_ok(text: &str, kind: DatetimeKind) -> bool {
    let b = text.as_bytes();
    let seg = |from: usize, to: usize| -> Option<i64> {
        let s = &b[from..to];
        if s.iter().any(|c| !c.is_ascii_digit()) {
            return None;
        }
        let mut v = 0i64;
        for &c in s {
            v = v * 10 + (c - b'0') as i64;
        }
        Some(v)
    };
    match kind {
        DatetimeKind::LocalDate => {
            if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
                return false;
            }
            let (Some(_y), Some(mo), Some(d)) = (seg(0, 4), seg(5, 7), seg(8, 10)) else {
                return false;
            };
            (1..=12).contains(&mo) && (1..=31).contains(&d)
        }
        DatetimeKind::LocalTime => {
            if b.len() < 8 || b[2] != b':' || b[5] != b':' {
                return false;
            }
            let (Some(h), Some(mi), Some(se)) = (seg(0, 2), seg(3, 5), seg(6, 8)) else {
                return false;
            };
            if h > 23 || mi > 59 || se > 60 {
                return false;
            }
            if b.len() == 8 {
                return true;
            }
            b.len() > 9 && b[8] == b'.' && b[9..].iter().all(|c| c.is_ascii_digit())
        }
        DatetimeKind::LocalDateTime | DatetimeKind::Offset => {
            let min_len = if kind == DatetimeKind::LocalDateTime {
                19
            } else {
                20
            };
            if b.len() < min_len {
                return false;
            }
            if !(b[4] == b'-'
                && b[7] == b'-'
                && (b[10] == b'T' || b[10] == b't' || b[10] == 0x20)
                && b[13] == b':'
                && b[16] == b':')
            {
                return false;
            }
            let (Some(mo), Some(d)) = (seg(5, 7), seg(8, 10)) else {
                return false;
            };
            let (Some(h), Some(mi), Some(se)) = (seg(11, 13), seg(14, 16), seg(17, 19)) else {
                return false;
            };
            if !(1..=12).contains(&mo) || !(1..=31).contains(&d) || h > 23 || mi > 59 || se > 60 {
                return false;
            }
            let mut i = 19;
            if i < b.len() && b[i] == b'.' {
                i += 1;
                let start = i;
                while i < b.len() && b[i].is_ascii_digit() {
                    i += 1;
                }
                if i == start {
                    return false;
                }
            }
            if kind == DatetimeKind::LocalDateTime {
                return i == b.len();
            }
            if i == b.len() {
                return false;
            }
            if b[i] == b'Z' || b[i] == b'z' {
                return i + 1 == b.len();
            }
            if i + 6 != b.len() || !(b[i] == b'+' || b[i] == b'-') || b[i + 3] != b':' {
                return false;
            }
            let (Some(zh), Some(zm)) = (seg(i + 1, i + 3), seg(i + 4, i + 6)) else {
                return false;
            };
            zh <= 23 && zm <= 59
        }
    }
}

// ---------------------------------------------------------------------------
// Serializer
// ---------------------------------------------------------------------------

fn is_aot(v: &Value) -> bool {
    match v {
        Value::Array(items) => {
            !items.is_empty() && items.iter().all(|x| matches!(x, Value::Table(_)))
        }
        _ => false,
    }
}

fn emit_table(
    tbl: &Value,
    path: &[String],
    out: &mut String,
    depth: u32,
    limit: u32,
) -> Result<(), SerdeError> {
    if depth > limit {
        return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
    }
    let pairs = match tbl {
        Value::Table(p) => p,
        _ => unreachable!(),
    };
    let mut scalars = Vec::new();
    let mut subtables = Vec::new();
    let mut aots = Vec::new();
    for (k, x) in pairs {
        if matches!(x, Value::Table(_)) {
            subtables.push((k, x));
        } else if is_aot(x) {
            aots.push((k, x));
        } else {
            scalars.push((k, x));
        }
    }
    let prefix = path
        .iter()
        .map(|s| toml_key(s))
        .collect::<Vec<_>>()
        .join(".");
    for (k, x) in scalars {
        out.push_str(&toml_key(k));
        out.push_str(" = ");
        out.push_str(&inline_value(x, depth, limit)?);
        out.push('\n');
    }
    for (k, x) in subtables {
        out.push('[');
        if !prefix.is_empty() {
            out.push_str(&prefix);
            out.push('.');
        }
        out.push_str(&toml_key(k));
        out.push_str("]\n");
        let mut sub_path = path.to_vec();
        sub_path.push(k.clone());
        emit_table(x, &sub_path, out, depth + 1, limit)?;
    }
    for (k, x) in aots {
        for el in match x {
            Value::Array(items) => items,
            _ => unreachable!(),
        } {
            out.push_str("[[");
            if !prefix.is_empty() {
                out.push_str(&prefix);
                out.push('.');
            }
            out.push_str(&toml_key(k));
            out.push_str("]]\n");
            let mut sub_path = path.to_vec();
            sub_path.push(k.clone());
            emit_table(el, &sub_path, out, depth + 1, limit)?;
        }
    }
    Ok(())
}

fn toml_key(k: &str) -> String {
    if !k.is_empty() && k.bytes().all(is_bare_key_byte) {
        k.to_string()
    } else {
        toml_quote(k)
    }
}

fn toml_quote(s: &str) -> String {
    let mut out = String::from("\"");
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{0009}' => out.push_str("\\t"),
            '\u{000A}' => out.push_str("\\n"),
            '\u{000C}' => out.push_str("\\f"),
            '\u{000D}' => out.push_str("\\r"),
            c if (c as u32) < 0x20 || c as u32 == 0x7F => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn inline_value(v: &Value, depth: u32, limit: u32) -> Result<String, SerdeError> {
    match v {
        Value::Null => Err(SerdeError::new(E_SYNTAX, "null is not a TOML value", None)),
        Value::Bool(b) => Ok(if *b { "true" } else { "false" }.to_string()),
        Value::Int(n) => Ok(n.to_string()),
        Value::UInt(n) => {
            if *n > i64::MAX as u64 {
                Err(SerdeError::new(
                    E_SYNTAX,
                    "unsigned value out of TOML 64-bit signed range",
                    None,
                ))
            } else {
                Ok(n.to_string())
            }
        }
        Value::Float(f) => Ok(if f.is_nan() {
            "nan".to_string()
        } else if f.is_infinite() {
            if f.is_sign_negative() { "-inf" } else { "inf" }.to_string()
        } else {
            render_float(*f)
        }),
        Value::Str(s) => Ok(toml_quote(s)),
        Value::Datetime(dt) => {
            if !datetime_ok(&dt.raw, dt.kind) {
                return Err(SerdeError::new(
                    E_DATETIME,
                    "invalid datetime raw text",
                    None,
                ));
            }
            Ok(dt.raw.clone())
        }
        Value::Bytes(_) => Err(SerdeError::new(
            E_BYTES,
            "Bytes values cannot be encoded as TOML",
            None,
        )),
        Value::Array(items) => {
            if depth > limit {
                return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
            }
            let mut parts = Vec::with_capacity(items.len());
            for x in items {
                parts.push(inline_value(x, depth + 1, limit)?);
            }
            Ok(format!("[{}]", parts.join(", ")))
        }
        Value::Table(pairs) => {
            if depth > limit {
                return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
            }
            if pairs.is_empty() {
                return Ok("{}".to_string());
            }
            let mut parts = Vec::with_capacity(pairs.len());
            for (k, x) in pairs {
                parts.push(format!(
                    "{} = {}",
                    toml_key(k),
                    inline_value(x, depth + 1, limit)?
                ));
            }
            Ok(format!("{{ {} }}", parts.join(", ")))
        }
    }
}
