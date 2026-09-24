//! Value intermediate representation.
//!
//! `Value` is the universal DOM that all formats serialize to/from.

extern crate alloc;
use alloc::string::String;
use alloc::vec::Vec;
use alloc::collections::BTreeMap;
use core::fmt;

/// Universal intermediate representation for serialized data.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    /// JSON null, MsgPack nil.
    Null,
    /// Boolean value.
    Bool(bool),
    /// Signed 64-bit integer.
    Integer(i64),
    /// IEEE 754 double-precision float.
    Float(f64),
    /// UTF-8 string.
    String(String),
    /// Ordered sequence of values.
    Array(Vec<Value>),
    /// Key-value map (string keys, preserves insertion order via BTreeMap).
    Map(BTreeMap<String, Value>),
    /// Raw binary data (MessagePack bin type).
    Bytes(Vec<u8>),
    /// Date-time string (TOML datetime types, stored as string representation).
    DateTime(DateTime),
}

/// TOML datetime variants.
#[derive(Debug, Clone, PartialEq)]
pub enum DateTime {
    /// Full offset datetime: 1979-05-27T07:32:00Z
    OffsetDateTime(String),
    /// Local datetime: 1979-05-27T07:32:00
    LocalDateTime(String),
    /// Local date: 1979-05-27
    LocalDate(String),
    /// Local time: 07:32:00
    LocalTime(String),
}

impl fmt::Display for DateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::OffsetDateTime(s) => write!(f, "{}", s),
            Self::LocalDateTime(s) => write!(f, "{}", s),
            Self::LocalDate(s) => write!(f, "{}", s),
            Self::LocalTime(s) => write!(f, "{}", s),
        }
    }
}

impl Value {
    /// Returns true if this value is Null.
    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    /// Try to get as bool.
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Value::Bool(b) => Some(*b),
            _ => None,
        }
    }

    /// Try to get as i64.
    pub fn as_integer(&self) -> Option<i64> {
        match self {
            Value::Integer(n) => Some(*n),
            _ => None,
        }
    }

    /// Try to get as f64.
    pub fn as_float(&self) -> Option<f64> {
        match self {
            Value::Float(n) => Some(*n),
            _ => None,
        }
    }

    /// Try to get as string slice.
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::String(s) => Some(s),
            _ => None,
        }
    }

    /// Try to get as array slice.
    pub fn as_array(&self) -> Option<&[Value]> {
        match self {
            Value::Array(arr) => Some(arr),
            _ => None,
        }
    }

    /// Try to get as map reference.
    pub fn as_map(&self) -> Option<&BTreeMap<String, Value>> {
        match self {
            Value::Map(map) => Some(map),
            _ => None,
        }
    }

    /// Try to get as bytes slice.
    pub fn as_bytes(&self) -> Option<&[u8]> {
        match self {
            Value::Bytes(b) => Some(b),
            _ => None,
        }
    }

    /// Get a value from a map by key.
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.as_map().and_then(|m| m.get(key))
    }

    /// Get a value from an array by index.
    pub fn index(&self, idx: usize) -> Option<&Value> {
        self.as_array().and_then(|a| a.get(idx))
    }

    /// Returns the type name as a static string.
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::Null => "null",
            Value::Bool(_) => "bool",
            Value::Integer(_) => "integer",
            Value::Float(_) => "float",
            Value::String(_) => "string",
            Value::Array(_) => "array",
            Value::Map(_) => "map",
            Value::Bytes(_) => "bytes",
            Value::DateTime(_) => "datetime",
        }
    }
}

impl From<bool> for Value {
    fn from(v: bool) -> Self { Value::Bool(v) }
}

impl From<i64> for Value {
    fn from(v: i64) -> Self { Value::Integer(v) }
}

impl From<i32> for Value {
    fn from(v: i32) -> Self { Value::Integer(v as i64) }
}

impl From<f64> for Value {
    fn from(v: f64) -> Self { Value::Float(v) }
}

impl From<String> for Value {
    fn from(v: String) -> Self { Value::String(v) }
}

impl From<&str> for Value {
    fn from(v: &str) -> Self { Value::String(String::from(v)) }
}

impl From<Vec<Value>> for Value {
    fn from(v: Vec<Value>) -> Self { Value::Array(v) }
}

impl From<BTreeMap<String, Value>> for Value {
    fn from(v: BTreeMap<String, Value>) -> Self { Value::Map(v) }
}

impl From<Vec<u8>> for Value {
    fn from(v: Vec<u8>) -> Self { Value::Bytes(v) }
}
