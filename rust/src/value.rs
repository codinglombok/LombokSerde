//! The canonical value model shared by all formats and all ports.

use crate::error::SerdeError;
use std::fmt;

/// Datetime kinds expressible in TOML (and, for `Offset`, MessagePack).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DatetimeKind {
    /// `1979-05-27T07:32:00Z` or with a numeric offset.
    Offset,
    /// `1979-05-27T07:32:00` without a zone.
    LocalDateTime,
    /// `1979-05-27`.
    LocalDate,
    /// `07:32:00`.
    LocalTime,
}

/// A datetime value. `raw` preserves the exact source text for TOML decode;
/// MessagePack timestamps decode to the canonical `...Z` form (see SPEC).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Datetime {
    pub kind: DatetimeKind,
    pub raw: String,
}

impl Datetime {
    pub fn new(kind: DatetimeKind, raw: impl Into<String>) -> Self {
        Datetime {
            kind,
            raw: raw.into(),
        }
    }
}

impl fmt::Display for Datetime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.raw)
    }
}

/// The universal intermediate representation for serialized data.
///
/// Invariant: `Table` entries are always sorted bytewise by key and contain
/// no duplicate keys. Decoders and constructors enforce this.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    /// Signed 64-bit integer.
    Int(i64),
    /// Unsigned 64-bit integer; decoders produce it only for values above
    /// `i64::MAX`.
    UInt(u64),
    /// IEEE 754 binary64.
    Float(f64),
    Str(String),
    /// Raw binary data (MessagePack `bin` only).
    Bytes(Vec<u8>),
    Array(Vec<Value>),
    /// String-keyed map, sorted bytewise by key, no duplicates.
    Table(Vec<(String, Value)>),
    Datetime(Datetime),
}

impl Value {
    /// Build a table from pairs. Pairs are sorted; duplicates are an error
    /// (fail-closed, code `SERDE_TABLE_DUPLICATE`).
    pub fn try_table(mut pairs: Vec<(String, Value)>) -> Result<Value, SerdeError> {
        pairs.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        for w in pairs.windows(2) {
            if w[0].0 == w[1].0 {
                return Err(SerdeError::new(
                    "SERDE_TABLE_DUPLICATE",
                    format!("duplicate key {:?}", w[0].0),
                    None,
                ));
            }
        }
        Ok(Value::Table(pairs))
    }

    /// Build a table from pairs that are known to be duplicate-free.
    /// Pairs are sorted. Debug builds assert uniqueness.
    pub fn table(mut pairs: Vec<(String, Value)>) -> Value {
        pairs.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        debug_assert!(pairs.windows(2).all(|w| w[0].0 != w[1].0));
        Value::Table(pairs)
    }

    /// Look up a key in a table value.
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Table(pairs) => pairs
                .binary_search_by(|(k, _)| k.as_bytes().cmp(key.as_bytes()))
                .ok()
                .map(|i| &pairs[i].1),
            _ => None,
        }
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }
}
