//! TOML serializer — outputs normalized TOML v1.0.

use std::collections::BTreeMap;
use crate::value::{Value, DateTime};

/// Serialize a Value to a TOML string.
///
/// The input must be a Value::Map (TOML root is always a table).
pub fn to_string(value: &Value) -> Result<String, crate::error::SerdeError> {
    match value {
        Value::Map(map) => {
            let mut out = String::new();
            write_table(map, &mut out, &[]);
            Ok(out)
        }
        _ => Err(crate::error::SerdeError::TypeMismatch {
            expected: "map",
            found: value.type_name(),
        }),
    }
}

fn write_table(map: &BTreeMap<String, Value>, out: &mut String, path: &[String]) {
    // First write all simple key-value pairs
    for (key, value) in map {
        if !is_table_or_array_of_tables(value) {
            write_key(key, out);
            out.push_str(" = ");
            write_value(value, out);
            out.push('\n');
        }
    }

    // Then write sub-tables
    for (key, value) in map {
        match value {
            Value::Map(sub_map) if !is_inline_table(sub_map) => {
                let mut new_path = path.to_vec();
                new_path.push(key.clone());

                out.push('\n');
                out.push('[');
                write_path(&new_path, out);
                out.push_str("]\n");
                write_table(sub_map, out, &new_path);
            }
            Value::Array(arr) if is_array_of_tables(arr) => {
                let mut new_path = path.to_vec();
                new_path.push(key.clone());

                for item in arr {
                    if let Value::Map(sub_map) = item {
                        out.push('\n');
                        out.push_str("[[");
                        write_path(&new_path, out);
                        out.push_str("]]\n");
                        write_table(sub_map, out, &new_path);
                    }
                }
            }
            _ => {} // Already handled above
        }
    }
}

fn is_table_or_array_of_tables(value: &Value) -> bool {
    match value {
        Value::Map(m) if !is_inline_table(m) => true,
        Value::Array(arr) if is_array_of_tables(arr) => true,
        _ => false,
    }
}

fn is_inline_table(_map: &BTreeMap<String, Value>) -> bool {
    // Always use standard [table] sections for maps — more readable and idiomatic TOML
    false
}

fn is_array_of_tables(arr: &[Value]) -> bool {
    !arr.is_empty() && arr.iter().all(|v| matches!(v, Value::Map(_)))
}

fn write_path(path: &[String], out: &mut String) {
    for (i, key) in path.iter().enumerate() {
        if i > 0 {
            out.push('.');
        }
        write_key(key, out);
    }
}

fn write_key(key: &str, out: &mut String) {
    if is_bare_key(key) {
        out.push_str(key);
    } else {
        write_basic_string(key, out);
    }
}

fn is_bare_key(key: &str) -> bool {
    !key.is_empty() && key.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn write_value(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("\"null\""), // TOML has no null; serialize as string
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Integer(n) => out.push_str(&format!("{}", n)),
        Value::Float(f) => {
            if f.is_nan() {
                out.push_str("nan");
            } else if f.is_infinite() {
                if *f < 0.0 { out.push_str("-inf"); } else { out.push_str("inf"); }
            } else {
                let s = format!("{}", f);
                out.push_str(&s);
                if !s.contains('.') && !s.contains('e') && !s.contains('E') {
                    out.push_str(".0");
                }
            }
        }
        Value::String(s) => write_basic_string(s, out),
        Value::Array(arr) => {
            out.push('[');
            for (i, v) in arr.iter().enumerate() {
                if i > 0 { out.push_str(", "); }
                write_value(v, out);
            }
            out.push(']');
        }
        Value::Map(map) => {
            // Inline table
            out.push('{');
            for (i, (k, v)) in map.iter().enumerate() {
                if i > 0 { out.push_str(", "); }
                write_key(k, out);
                out.push_str(" = ");
                write_value(v, out);
            }
            out.push('}');
        }
        Value::Bytes(b) => {
            // Encode as array of integers
            out.push('[');
            for (i, byte) in b.iter().enumerate() {
                if i > 0 { out.push_str(", "); }
                out.push_str(&format!("{}", byte));
            }
            out.push(']');
        }
        Value::DateTime(dt) => {
            out.push_str(&format!("{}", dt));
        }
    }
}

fn write_basic_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\u{0C}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04X}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_table() {
        let mut map = BTreeMap::new();
        map.insert("name".to_string(), Value::String("test".to_string()));
        map.insert("version".to_string(), Value::Integer(1));
        let result = to_string(&Value::Map(map)).unwrap();
        assert!(result.contains("name = \"test\""));
        assert!(result.contains("version = 1"));
    }

    #[test]
    fn test_nested_table() {
        let mut inner = BTreeMap::new();
        inner.insert("host".to_string(), Value::String("localhost".to_string()));
        inner.insert("port".to_string(), Value::Integer(8080));
        let mut root = BTreeMap::new();
        root.insert("server".to_string(), Value::Map(inner));
        let result = to_string(&Value::Map(root)).unwrap();
        assert!(result.contains("[server]"));
        assert!(result.contains("host = \"localhost\""));
    }

    #[test]
    fn test_roundtrip() {
        let input = "flag = true\nname = \"hello\"\nnum = 42\n";
        let parsed = super::super::parser::parse(input).unwrap();
        let output = to_string(&parsed).unwrap();
        let reparsed = super::super::parser::parse(&output).unwrap();
        assert_eq!(parsed, reparsed);
    }
}
