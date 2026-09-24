//! JSON serializer — compact and pretty-print.

extern crate alloc;
use alloc::string::String;

use crate::value::Value;

/// Serialize a Value to a compact JSON string.
pub fn to_string(value: &Value) -> String {
    let mut out = String::new();
    write_value(value, &mut out);
    out
}

/// Serialize a Value to a pretty-printed JSON string.
pub fn to_string_pretty(value: &Value) -> String {
    to_string_pretty_indent(value, 2)
}

/// Serialize a Value to a pretty-printed JSON string with custom indent.
pub fn to_string_pretty_indent(value: &Value, indent: usize) -> String {
    let mut out = String::new();
    write_value_pretty(value, &mut out, 0, indent);
    out.push('\n');
    out
}

fn write_value(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Integer(n) => {
            let mut buf = itoa_buf(*n);
            out.push_str(&buf);
        }
        Value::Float(f) => {
            write_float(*f, out);
        }
        Value::String(s) => write_json_string(s, out),
        Value::Array(arr) => {
            out.push('[');
            for (i, v) in arr.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_value(v, out);
            }
            out.push(']');
        }
        Value::Map(map) => {
            out.push('{');
            for (i, (k, v)) in map.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_json_string(k, out);
                out.push(':');
                write_value(v, out);
            }
            out.push('}');
        }
        Value::Bytes(b) => {
            // Encode bytes as array of integers
            out.push('[');
            for (i, byte) in b.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                let buf = itoa_buf(*byte as i64);
                out.push_str(&buf);
            }
            out.push(']');
        }
        Value::DateTime(dt) => {
            write_json_string(&alloc::format!("{}", dt), out);
        }
    }
}

fn write_value_pretty(value: &Value, out: &mut String, level: usize, indent: usize) {
    match value {
        Value::Array(arr) if arr.is_empty() => out.push_str("[]"),
        Value::Array(arr) => {
            out.push_str("[\n");
            for (i, v) in arr.iter().enumerate() {
                if i > 0 {
                    out.push_str(",\n");
                }
                push_indent(out, level + 1, indent);
                write_value_pretty(v, out, level + 1, indent);
            }
            out.push('\n');
            push_indent(out, level, indent);
            out.push(']');
        }
        Value::Map(map) if map.is_empty() => out.push_str("{}"),
        Value::Map(map) => {
            out.push_str("{\n");
            for (i, (k, v)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(",\n");
                }
                push_indent(out, level + 1, indent);
                write_json_string(k, out);
                out.push_str(": ");
                write_value_pretty(v, out, level + 1, indent);
            }
            out.push('\n');
            push_indent(out, level, indent);
            out.push('}');
        }
        other => write_value(other, out),
    }
}

fn push_indent(out: &mut String, level: usize, indent: usize) {
    for _ in 0..(level * indent) {
        out.push(' ');
    }
}

fn write_json_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&alloc::format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_float(f: f64, out: &mut String) {
    if f.is_nan() {
        out.push_str("null"); // JSON has no NaN
    } else if f.is_infinite() {
        out.push_str("null"); // JSON has no Infinity
    } else {
        let s = alloc::format!("{}", f);
        out.push_str(&s);
        // Ensure it looks like a float
        if !s.contains('.') && !s.contains('e') && !s.contains('E') {
            out.push_str(".0");
        }
    }
}

fn itoa_buf(n: i64) -> String {
    alloc::format!("{}", n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::collections::BTreeMap;

    #[test]
    fn test_serialize_primitives() {
        assert_eq!(to_string(&Value::Null), "null");
        assert_eq!(to_string(&Value::Bool(true)), "true");
        assert_eq!(to_string(&Value::Bool(false)), "false");
        assert_eq!(to_string(&Value::Integer(42)), "42");
        assert_eq!(to_string(&Value::Integer(-7)), "-7");
        assert_eq!(to_string(&Value::String("hello".into())), "\"hello\"");
    }

    #[test]
    fn test_serialize_string_escapes() {
        assert_eq!(
            to_string(&Value::String("a\"b".into())),
            "\"a\\\"b\""
        );
        assert_eq!(
            to_string(&Value::String("a\nb".into())),
            "\"a\\nb\""
        );
        assert_eq!(
            to_string(&Value::String("a\\b".into())),
            "\"a\\\\b\""
        );
    }

    #[test]
    fn test_serialize_array() {
        let v = Value::Array(vec![
            Value::Integer(1),
            Value::String("two".into()),
            Value::Null,
        ]);
        assert_eq!(to_string(&v), "[1,\"two\",null]");
    }

    #[test]
    fn test_serialize_object() {
        let mut map = BTreeMap::new();
        map.insert("a".into(), Value::Integer(1));
        map.insert("b".into(), Value::Bool(true));
        let v = Value::Map(map);
        assert_eq!(to_string(&v), "{\"a\":1,\"b\":true}");
    }

    #[test]
    fn test_roundtrip() {
        let input = r#"{"array":[1,2,3],"flag":true,"name":"test","value":null}"#;
        let parsed = super::super::parser::parse(input).unwrap();
        let output = to_string(&parsed);
        assert_eq!(output, input);
    }
}
