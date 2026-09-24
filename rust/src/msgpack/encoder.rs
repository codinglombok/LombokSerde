//! MessagePack encoder.

extern crate alloc;
use alloc::vec::Vec;

use crate::value::Value;

/// Encode a Value to MessagePack bytes.
pub fn encode(value: &Value) -> Vec<u8> {
    let mut buf = Vec::new();
    encode_value(value, &mut buf);
    buf
}

fn encode_value(value: &Value, buf: &mut Vec<u8>) {
    match value {
        Value::Null => buf.push(0xC0),
        Value::Bool(false) => buf.push(0xC2),
        Value::Bool(true) => buf.push(0xC3),
        Value::Integer(n) => encode_integer(*n, buf),
        Value::Float(f) => encode_float64(*f, buf),
        Value::String(s) => encode_string(s, buf),
        Value::Array(arr) => encode_array(arr, buf),
        Value::Map(map) => encode_map(map, buf),
        Value::Bytes(b) => encode_bin(b, buf),
        Value::DateTime(dt) => {
            // Encode datetime as string
            let s = alloc::format!("{}", dt);
            encode_string(&s, buf);
        }
    }
}

fn encode_integer(n: i64, buf: &mut Vec<u8>) {
    if n >= 0 {
        let u = n as u64;
        if u <= 127 {
            // positive fixint
            buf.push(u as u8);
        } else if u <= 0xFF {
            buf.push(0xCC);
            buf.push(u as u8);
        } else if u <= 0xFFFF {
            buf.push(0xCD);
            buf.extend_from_slice(&(u as u16).to_be_bytes());
        } else if u <= 0xFFFF_FFFF {
            buf.push(0xCE);
            buf.extend_from_slice(&(u as u32).to_be_bytes());
        } else {
            buf.push(0xCF);
            buf.extend_from_slice(&u.to_be_bytes());
        }
    } else {
        if n >= -32 {
            // negative fixint
            buf.push(n as u8); // two's complement
        } else if n >= -128 {
            buf.push(0xD0);
            buf.push(n as i8 as u8);
        } else if n >= -32768 {
            buf.push(0xD1);
            buf.extend_from_slice(&(n as i16).to_be_bytes());
        } else if n >= -2147483648 {
            buf.push(0xD2);
            buf.extend_from_slice(&(n as i32).to_be_bytes());
        } else {
            buf.push(0xD3);
            buf.extend_from_slice(&n.to_be_bytes());
        }
    }
}

fn encode_float64(f: f64, buf: &mut Vec<u8>) {
    buf.push(0xCB);
    buf.extend_from_slice(&f.to_be_bytes());
}

fn encode_string(s: &str, buf: &mut Vec<u8>) {
    let bytes = s.as_bytes();
    let len = bytes.len();
    if len <= 31 {
        // fixstr
        buf.push(0xA0 | len as u8);
    } else if len <= 0xFF {
        buf.push(0xD9);
        buf.push(len as u8);
    } else if len <= 0xFFFF {
        buf.push(0xDA);
        buf.extend_from_slice(&(len as u16).to_be_bytes());
    } else {
        buf.push(0xDB);
        buf.extend_from_slice(&(len as u32).to_be_bytes());
    }
    buf.extend_from_slice(bytes);
}

fn encode_bin(data: &[u8], buf: &mut Vec<u8>) {
    let len = data.len();
    if len <= 0xFF {
        buf.push(0xC4);
        buf.push(len as u8);
    } else if len <= 0xFFFF {
        buf.push(0xC5);
        buf.extend_from_slice(&(len as u16).to_be_bytes());
    } else {
        buf.push(0xC6);
        buf.extend_from_slice(&(len as u32).to_be_bytes());
    }
    buf.extend_from_slice(data);
}

fn encode_array(arr: &[Value], buf: &mut Vec<u8>) {
    let len = arr.len();
    if len <= 15 {
        // fixarray
        buf.push(0x90 | len as u8);
    } else if len <= 0xFFFF {
        buf.push(0xDC);
        buf.extend_from_slice(&(len as u16).to_be_bytes());
    } else {
        buf.push(0xDD);
        buf.extend_from_slice(&(len as u32).to_be_bytes());
    }
    for v in arr {
        encode_value(v, buf);
    }
}

fn encode_map(map: &alloc::collections::BTreeMap<alloc::string::String, Value>, buf: &mut Vec<u8>) {
    let len = map.len();
    if len <= 15 {
        // fixmap
        buf.push(0x80 | len as u8);
    } else if len <= 0xFFFF {
        buf.push(0xDE);
        buf.extend_from_slice(&(len as u16).to_be_bytes());
    } else {
        buf.push(0xDF);
        buf.extend_from_slice(&(len as u32).to_be_bytes());
    }
    for (k, v) in map {
        encode_string(k, buf);
        encode_value(v, buf);
    }
}

/// Encode an extension type.
pub fn encode_ext(type_id: i8, data: &[u8], buf: &mut Vec<u8>) {
    let len = data.len();
    match len {
        1 => { buf.push(0xD4); buf.push(type_id as u8); }
        2 => { buf.push(0xD5); buf.push(type_id as u8); }
        4 => { buf.push(0xD6); buf.push(type_id as u8); }
        8 => { buf.push(0xD7); buf.push(type_id as u8); }
        16 => { buf.push(0xD8); buf.push(type_id as u8); }
        _ if len <= 0xFF => {
            buf.push(0xC7);
            buf.push(len as u8);
            buf.push(type_id as u8);
        }
        _ if len <= 0xFFFF => {
            buf.push(0xC8);
            buf.extend_from_slice(&(len as u16).to_be_bytes());
            buf.push(type_id as u8);
        }
        _ => {
            buf.push(0xC9);
            buf.extend_from_slice(&(len as u32).to_be_bytes());
            buf.push(type_id as u8);
        }
    }
    buf.extend_from_slice(data);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encode_nil() {
        assert_eq!(encode(&Value::Null), vec![0xC0]);
    }

    #[test]
    fn test_encode_bool() {
        assert_eq!(encode(&Value::Bool(false)), vec![0xC2]);
        assert_eq!(encode(&Value::Bool(true)), vec![0xC3]);
    }

    #[test]
    fn test_encode_positive_fixint() {
        assert_eq!(encode(&Value::Integer(0)), vec![0x00]);
        assert_eq!(encode(&Value::Integer(127)), vec![0x7F]);
    }

    #[test]
    fn test_encode_negative_fixint() {
        assert_eq!(encode(&Value::Integer(-1)), vec![0xFF]);
        assert_eq!(encode(&Value::Integer(-32)), vec![0xE0]);
    }

    #[test]
    fn test_encode_uint8() {
        assert_eq!(encode(&Value::Integer(128)), vec![0xCC, 128]);
        assert_eq!(encode(&Value::Integer(255)), vec![0xCC, 255]);
    }

    #[test]
    fn test_encode_fixstr() {
        let result = encode(&Value::String("hi".into()));
        assert_eq!(result, vec![0xA2, b'h', b'i']);
    }

    #[test]
    fn test_encode_array() {
        let v = Value::Array(vec![Value::Integer(1), Value::Integer(2)]);
        let result = encode(&v);
        assert_eq!(result, vec![0x92, 1, 2]);
    }
}
