//! MessagePack codec — canonical, byte-precise (see SPEC).
//!
//! Encoding pins: minimal-length integer/str/bin/array/map families; floats
//! always `float64`; timestamps use `timestamp32/64/96` per the spec's
//! compact forms; `ext` types other than `-1` are rejected (fail-closed).

use crate::error::SerdeError;
use crate::value::{Datetime, DatetimeKind, Value};

/// Options for the MessagePack codec.
#[derive(Debug, Clone)]
pub struct MsgPackOptions {
    pub depth_limit: u32,
}

impl Default for MsgPackOptions {
    fn default() -> Self {
        MsgPackOptions {
            depth_limit: crate::DEFAULT_DEPTH_LIMIT,
        }
    }
}

const E_TRUNCATED: &str = "SERDE_MP_TRUNCATED";
const E_UNEXPECTED: &str = "SERDE_MP_UNEXPECTED";
const E_TRAILING: &str = "SERDE_MP_TRAILING";
const E_UTF8: &str = "SERDE_MP_UTF8";
const E_EXT: &str = "SERDE_MP_EXT";
const E_DEPTH: &str = "SERDE_MP_DEPTH";
const E_DUPLICATE: &str = "SERDE_MP_DUPLICATE";
const E_DATETIME: &str = "SERDE_MP_DATETIME";

/// Decode exactly one MessagePack value; trailing bytes are an error.
pub fn msgpack_decode(data: &[u8], opts: &MsgPackOptions) -> Result<Value, SerdeError> {
    let mut p = MpParser {
        b: data,
        i: 0,
        limit: opts.depth_limit,
    };
    let v = p.read_value(1)?;
    if p.i != data.len() {
        return Err(SerdeError::syntax(
            E_TRAILING,
            p.i,
            "trailing bytes after the top-level value",
        ));
    }
    Ok(v)
}

/// Encode a value with the canonical (minimal) encoding rules.
pub fn msgpack_encode(v: &Value, opts: &MsgPackOptions) -> Result<Vec<u8>, SerdeError> {
    let mut out = Vec::new();
    write_value(&mut out, v, 1, opts.depth_limit)?;
    Ok(out)
}

struct MpParser<'a> {
    b: &'a [u8],
    i: usize,
    limit: u32,
}

impl<'a> MpParser<'a> {
    fn need(&self, n: usize) -> Result<(), SerdeError> {
        if self.i + n > self.b.len() {
            return Err(SerdeError::syntax(
                E_TRUNCATED,
                self.b.len(),
                "unexpected end of input",
            ));
        }
        Ok(())
    }

    fn take(&mut self, n: usize) -> Result<&'a [u8], SerdeError> {
        self.need(n)?;
        let s = &self.b[self.i..self.i + n];
        self.i += n;
        Ok(s)
    }

    fn read_value(&mut self, depth: u32) -> Result<Value, SerdeError> {
        let m = *self.take(1)?.first().unwrap();
        match m {
            0x00..=0x7F => Ok(Value::Int(m as i64)),
            0xE0..=0xFF => Ok(Value::Int(m as i8 as i64)),
            0x80..=0x8F => self.read_map((m & 0x0F) as usize, depth),
            0x90..=0x9F => self.read_array((m & 0x0F) as usize, depth),
            0xA0..=0xBF => self.read_str((m & 0x1F) as usize),
            0xC0 => Ok(Value::Null),
            0xC1 => Err(SerdeError::syntax(
                E_UNEXPECTED,
                self.i - 1,
                "reserved type code 0xc1",
            )),
            0xC2 => Ok(Value::Bool(false)),
            0xC3 => Ok(Value::Bool(true)),
            0xC4..=0xC6 => {
                let n = self.read_len(m - 0xC4, 1)?;
                Ok(Value::Bytes(self.take(n)?.to_vec()))
            }
            0xC7..=0xC9 => {
                let n = self.read_len(m - 0xC7, 1)?;
                self.read_ext(n)
            }
            0xCA => {
                let raw = self.take(4)?;
                let f = f32::from_bits(u32::from_be_bytes(raw.try_into().unwrap()));
                Ok(Value::Float(f as f64))
            }
            0xCB => {
                let raw = self.take(8)?;
                let f = f64::from_bits(u64::from_be_bytes(raw.try_into().unwrap()));
                Ok(Value::Float(f))
            }
            0xCC..=0xCF => {
                let n = 1usize << (m - 0xCC);
                let raw = self.take(n)?;
                let v = read_uint_be(raw);
                Ok(int_or_uint(v))
            }
            0xD0..=0xD3 => {
                let n = 1usize << (m - 0xD0);
                let raw = self.take(n)?;
                Ok(Value::Int(read_int_be(raw)))
            }
            0xD4..=0xD8 => {
                let n = 1usize << (m - 0xD4);
                self.read_ext(n)
            }
            0xD9..=0xDB => {
                let n = self.read_len(m - 0xD9, 1)?;
                self.read_str(n)
            }
            0xDC | 0xDD => {
                let n = self.read_len(m - 0xDC, 2)?;
                self.read_array(n, depth)
            }
            0xDE | 0xDF => {
                let n = self.read_len(m - 0xDE, 2)?;
                self.read_map(n, depth)
            }
        }
    }

    fn read_len(&mut self, size_class: u8, min_bytes: usize) -> Result<usize, SerdeError> {
        let n = match size_class {
            0 => {
                let raw = self.take(1)?;
                raw[0] as usize
            }
            1 => {
                let raw = self.take(2)?;
                u16::from_be_bytes(raw.try_into().unwrap()) as usize
            }
            _ => {
                let raw = self.take(4)?;
                u32::from_be_bytes(raw.try_into().unwrap()) as usize
            }
        };
        if n < min_bytes {
            return Err(SerdeError::syntax(
                E_UNEXPECTED,
                self.i,
                "length field below the minimum for this type",
            ));
        }
        Ok(n)
    }

    fn read_str(&mut self, n: usize) -> Result<Value, SerdeError> {
        let start = self.i;
        let raw = self.take(n)?;
        match std::str::from_utf8(raw) {
            Ok(s) => Ok(Value::Str(s.to_string())),
            Err(_) => Err(SerdeError::syntax(E_UTF8, start, "invalid UTF-8 in string")),
        }
    }

    fn read_array(&mut self, n: usize, depth: u32) -> Result<Value, SerdeError> {
        if depth > self.limit {
            return Err(SerdeError::syntax(E_DEPTH, self.i, "depth limit exceeded"));
        }
        let mut items = Vec::with_capacity(n.min(4096));
        for _ in 0..n {
            items.push(self.read_value(depth + 1)?);
        }
        Ok(Value::Array(items))
    }

    fn read_map(&mut self, n: usize, depth: u32) -> Result<Value, SerdeError> {
        if depth > self.limit {
            return Err(SerdeError::syntax(E_DEPTH, self.i, "depth limit exceeded"));
        }
        let mut pairs = Vec::with_capacity(n.min(4096));
        for _ in 0..n {
            let k = self.read_value(depth + 1)?;
            let ks = match k {
                Value::Str(s) => s,
                _ => {
                    return Err(SerdeError::syntax(
                        E_UNEXPECTED,
                        self.i,
                        "map key is not a string",
                    ))
                }
            };
            let v = self.read_value(depth + 1)?;
            pairs.push((ks, v));
        }
        Value::try_table(pairs)
            .map_err(|_| SerdeError::syntax(E_DUPLICATE, self.i, "duplicate map key"))
    }

    fn read_ext(&mut self, n: usize) -> Result<Value, SerdeError> {
        let type_raw = *self.take(1)?.first().unwrap();
        let etype = type_raw as i8;
        if etype != -1 {
            return Err(SerdeError::syntax(
                E_EXT,
                self.i - 1,
                "unsupported extension type",
            ));
        }
        match n {
            4 => {
                let raw = self.take(4)?;
                let sec = u32::from_be_bytes(raw.try_into().unwrap()) as i64;
                Ok(datetime_from_timestamp(sec, 0))
            }
            8 => {
                let raw = self.take(8)?;
                let bits = u64::from_be_bytes(raw.try_into().unwrap());
                let ns = (bits >> 34) as u32;
                let sec = (bits & ((1u64 << 34) - 1)) as i64;
                if ns > 999_999_999 {
                    return Err(SerdeError::syntax(
                        E_UNEXPECTED,
                        self.i - 8,
                        "nanoseconds out of range",
                    ));
                }
                Ok(datetime_from_timestamp(sec, ns))
            }
            12 => {
                let raw = self.take(12)?;
                let ns = u32::from_be_bytes(raw[0..4].try_into().unwrap());
                let sec = i64::from_be_bytes(raw[4..12].try_into().unwrap());
                if ns > 999_999_999 {
                    return Err(SerdeError::syntax(
                        E_UNEXPECTED,
                        self.i - 12,
                        "nanoseconds out of range",
                    ));
                }
                Ok(datetime_from_timestamp(sec, ns))
            }
            _ => Err(SerdeError::syntax(
                E_EXT,
                self.i - 1,
                "unsupported timestamp payload length",
            )),
        }
    }
}

fn read_uint_be(raw: &[u8]) -> u64 {
    let mut v: u64 = 0;
    for &b in raw {
        v = (v << 8) | b as u64;
    }
    v
}

fn read_int_be(raw: &[u8]) -> i64 {
    let mut v: i64 = if raw[0] & 0x80 != 0 { -1 } else { 0 };
    for &b in raw {
        v = (v << 8) | b as i64;
    }
    v
}

fn int_or_uint(v: u64) -> Value {
    if v <= i64::MAX as u64 {
        Value::Int(v as i64)
    } else {
        Value::UInt(v)
    }
}

fn datetime_from_timestamp(sec: i64, ns: u32) -> Value {
    Value::Datetime(Datetime::new(
        DatetimeKind::Offset,
        format_timestamp(sec, ns),
    ))
}

fn write_value(out: &mut Vec<u8>, v: &Value, depth: u32, limit: u32) -> Result<(), SerdeError> {
    match v {
        Value::Null => out.push(0xC0),
        Value::Bool(b) => out.push(if *b { 0xC3 } else { 0xC2 }),
        Value::Int(n) => write_int(out, *n),
        Value::UInt(n) => {
            let n = *n;
            if n <= 0x7F {
                out.push(n as u8);
            } else if n <= 0xFF {
                out.push(0xCC);
                out.push(n as u8);
            } else if n <= 0xFFFF {
                out.push(0xCD);
                out.extend_from_slice(&(n as u16).to_be_bytes());
            } else if n <= 0xFFFF_FFFF {
                out.push(0xCE);
                out.extend_from_slice(&(n as u32).to_be_bytes());
            } else {
                out.push(0xCF);
                out.extend_from_slice(&n.to_be_bytes());
            }
        }
        Value::Float(f) => {
            out.push(0xCB);
            out.extend_from_slice(&f.to_bits().to_be_bytes());
        }
        Value::Str(s) => {
            let sb = s.as_bytes();
            let n = sb.len();
            if n <= 31 {
                out.push(0xA0 | n as u8);
            } else if n <= 0xFF {
                out.push(0xD9);
                out.push(n as u8);
            } else if n <= 0xFFFF {
                out.push(0xDA);
                out.extend_from_slice(&(n as u16).to_be_bytes());
            } else {
                out.push(0xDB);
                out.extend_from_slice(&(n as u32).to_be_bytes());
            }
            out.extend_from_slice(sb);
        }
        Value::Bytes(bs) => {
            let n = bs.len();
            if n <= 0xFF {
                out.push(0xC4);
                out.push(n as u8);
            } else if n <= 0xFFFF {
                out.push(0xC5);
                out.extend_from_slice(&(n as u16).to_be_bytes());
            } else {
                out.push(0xC6);
                out.extend_from_slice(&(n as u32).to_be_bytes());
            }
            out.extend_from_slice(bs);
        }
        Value::Array(items) => {
            if depth > limit {
                return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
            }
            let n = items.len();
            if n <= 15 {
                out.push(0x90 | n as u8);
            } else if n <= 0xFFFF {
                out.push(0xDC);
                out.extend_from_slice(&(n as u16).to_be_bytes());
            } else {
                out.push(0xDD);
                out.extend_from_slice(&(n as u32).to_be_bytes());
            }
            for x in items {
                write_value(out, x, depth + 1, limit)?;
            }
        }
        Value::Table(pairs) => {
            if depth > limit {
                return Err(SerdeError::new(E_DEPTH, "depth limit exceeded", None));
            }
            let n = pairs.len();
            if n <= 15 {
                out.push(0x80 | n as u8);
            } else if n <= 0xFFFF {
                out.push(0xDE);
                out.extend_from_slice(&(n as u16).to_be_bytes());
            } else {
                out.push(0xDF);
                out.extend_from_slice(&(n as u32).to_be_bytes());
            }
            for (k, x) in pairs {
                write_value(out, &Value::Str(k.clone()), depth, limit)?;
                write_value(out, x, depth + 1, limit)?;
            }
        }
        Value::Datetime(dt) => write_datetime(out, dt)?,
    }
    Ok(())
}

fn write_int(out: &mut Vec<u8>, n: i64) {
    if (0..=0x7F).contains(&n) {
        out.push(n as u8);
    } else if n > 0 {
        if n <= 0xFF {
            out.push(0xCC);
            out.push(n as u8);
        } else if n <= 0xFFFF {
            out.push(0xCD);
            out.extend_from_slice(&(n as u16).to_be_bytes());
        } else if n <= 0xFFFF_FFFF {
            out.push(0xCE);
            out.extend_from_slice(&(n as u32).to_be_bytes());
        } else {
            out.push(0xCF);
            out.extend_from_slice(&(n as u64).to_be_bytes());
        }
    } else if (-32..0).contains(&n) {
        out.push((0xE0 | (n + 32)) as u8);
    } else if (-128..0).contains(&n) {
        out.push(0xD0);
        out.push((n & 0xFF) as u8);
    } else if (-32768..0).contains(&n) {
        out.push(0xD1);
        out.extend_from_slice(&(n as i16).to_be_bytes());
    } else if (i32::MIN as i64..0).contains(&n) {
        out.push(0xD2);
        out.extend_from_slice(&(n as i32).to_be_bytes());
    } else {
        out.push(0xD3);
        out.extend_from_slice(&n.to_be_bytes());
    }
}

fn write_datetime(out: &mut Vec<u8>, dt: &Datetime) -> Result<(), SerdeError> {
    if dt.kind != DatetimeKind::Offset {
        return Err(SerdeError::new(
            E_DATETIME,
            "only Offset datetimes map to MessagePack timestamps",
            None,
        ));
    }
    let (sec, ns) = match parse_offset_datetime(&dt.raw) {
        Some(x) => x,
        None => {
            return Err(SerdeError::new(
                E_DATETIME,
                "datetime raw text is not a valid RFC 3339 offset datetime",
                None,
            ))
        }
    };
    if ns == 0 && (0..=0xFFFF_FFFF).contains(&sec) {
        out.push(0xD6);
        out.push(0xFF);
        out.extend_from_slice(&(sec as u32).to_be_bytes());
    } else if (0..=(1i64 << 34) - 1).contains(&sec) {
        let bits = ((ns as u64) << 34) | sec as u64;
        out.push(0xD7);
        out.push(0xFF);
        out.extend_from_slice(&bits.to_be_bytes());
    } else {
        out.push(0xC7);
        out.push(12);
        out.push(0xFF);
        out.extend_from_slice(&ns.to_be_bytes());
        out.extend_from_slice(&sec.to_be_bytes());
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Calendar math (identical integer arithmetic in every port)
// ---------------------------------------------------------------------------

/// Days since 1970-01-01 for a civil date (Howard Hinnant's algorithm).
pub fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = y - if m <= 2 { 1 } else { 0 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = if m > 2 { m - 3 } else { m + 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// Civil date from days since 1970-01-01 (Howard Hinnant's algorithm).
pub fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (y + if m <= 2 { 1 } else { 0 }, m, d)
}

/// RFC 3339 offset datetime -> (epoch seconds, nanoseconds), or None.
pub fn parse_offset_datetime(raw: &str) -> Option<(i64, u32)> {
    let b = raw.as_bytes();
    let digits = |s: &[u8]| -> Option<i64> {
        if s.is_empty() || !s.iter().all(|c| c.is_ascii_digit()) {
            return None;
        }
        s.iter().try_fold::<i64, _, _>(0i64, |acc, c| {
            acc.checked_mul(10)
                .and_then(|a| a.checked_add((c - b'0') as i64))
        })
    };
    if b.len() < 20 {
        return None;
    }
    if !(b[4] == b'-'
        && b[7] == b'-'
        && (b[10] == b'T' || b[10] == b't' || b[10] == b' ')
        && b[13] == b':'
        && b[16] == b':')
    {
        return None;
    }
    let y = digits(&b[0..4])?;
    let mo = digits(&b[5..7])?;
    let d = digits(&b[8..10])?;
    let h = digits(&b[11..13])?;
    let mi = digits(&b[14..16])?;
    let s = digits(&b[17..19])?;
    let mut i = 19;
    let mut ns: u32 = 0;
    if i < b.len() && b[i] == b'.' {
        i += 1;
        let start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == start {
            return None;
        }
        let mut buf = [b'0'; 9];
        for j in 0..9 {
            if start + j >= i {
                break; // stop at the end of the digit run
            }
            buf[j] = b[start + j];
        }
        ns = digits(&buf)? as u32;
    }
    if s == 60 {
        return None; // leap seconds are not representable in MessagePack
    }
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) || h > 23 || mi > 59 {
        return None;
    }
    let sec: i64 = if i < b.len() && (b[i] == b'Z' || b[i] == b'z') {
        if i + 1 != b.len() {
            return None;
        }
        days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s
    } else if i + 5 < b.len() && (b[i] == b'+' || b[i] == b'-') && b[i + 3] == b':' {
        if i + 6 != b.len() {
            return None;
        }
        let oh = digits(&b[i + 1..i + 3])?;
        let om = digits(&b[i + 4..i + 6])?;
        if oh > 23 || om > 59 {
            return None;
        }
        let off = oh * 3600 + om * 60;
        let base = days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s;
        if b[i] == b'+' {
            base - off
        } else {
            base + off
        }
    } else {
        return None;
    };
    Some((sec, ns))
}

/// Epoch seconds + nanoseconds -> canonical `YYYY-MM-DDTHH:MM:SS[.fff]Z`.
pub fn format_timestamp(sec: i64, ns: u32) -> String {
    let days = sec.div_euclid(86400);
    let rem = sec.rem_euclid(86400);
    let (y, mo, d) = civil_from_days(days);
    let h = rem / 3600;
    let mi = (rem % 3600) / 60;
    let s = rem % 60;
    let frac = if ns != 0 {
        let mut t = format!(".{:09}", ns);
        while t.ends_with('0') {
            t.pop();
        }
        t
    } else {
        String::new()
    };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}{}Z",
        y, mo, d, h, mi, s, frac
    )
}
