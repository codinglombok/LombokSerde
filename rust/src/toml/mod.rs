//! TOML v1.0 parser and serializer.

pub mod parser;
pub mod serializer;

pub use parser::parse;
pub use serializer::to_string;
