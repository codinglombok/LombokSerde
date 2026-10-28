//! LombokSerde — zero-dependency serialization library with byte-identical
//! behavior across languages: JSON (RFC 8259), TOML (v1.0), MessagePack.
//!
//! The Rust crate is the reference implementation of the cross-language
//! contract; every port must pass the shared deterministic vectors in
//! `vectors/lombokserde-vectors-v1.json` bit-identically. See
//! `docs/SPEC_LombokSerde_v0.1.0.md` for the normative specification.
//!
//! # Quick start
//! ```
//! use lombokserde::{json_decode, json_encode, JsonOptions, Value};
//!
//! let v = json_decode(br#"{"b":1,"a":2}"#, &JsonOptions::default()).unwrap();
//! assert_eq!(
//!     json_encode(&v, &JsonOptions::default()).unwrap(),
//!     br#"{"a":2,"b":1}"#.to_vec()
//! );
//! assert_eq!(v.get("a"), Some(&Value::Int(2)));
//! ```

mod error;
mod float;
mod json;
mod msgpack;
mod toml;
mod value;

pub use error::SerdeError;
pub use json::{json_decode, json_encode, JsonOptions};
pub use msgpack::{msgpack_decode, msgpack_encode, MsgPackOptions};
pub use toml::{toml_decode, toml_encode, TomlOptions};
pub use value::{Datetime, DatetimeKind, Value};

/// Default maximum container nesting depth for every format and port.
pub const DEFAULT_DEPTH_LIMIT: u32 = 128;
