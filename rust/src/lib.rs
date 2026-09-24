//! LombokSerde — zero-dependency serialization library.
//!
//! Supports JSON (RFC 8259), TOML (v1.0), and MessagePack.
//!
//! # Features
//! - `json` (default) — JSON parser/serializer
//! - `toml` — TOML parser/serializer (requires std)
//! - `msgpack` (default) — MessagePack encoder/decoder
//! - `std` (default) — std library support

#![cfg_attr(not(feature = "std"), no_std)]

extern crate alloc;

pub mod error;
pub mod value;
pub mod traits;

#[cfg(feature = "json")]
pub mod json;

#[cfg(feature = "toml")]
pub mod toml;

#[cfg(feature = "msgpack")]
pub mod msgpack;

// Re-exports
pub use error::SerdeError;
pub use value::{Value, DateTime};
pub use traits::{Serialize, Deserialize};
