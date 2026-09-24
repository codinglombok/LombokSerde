//! Error types for LombokSerde.

use core::fmt;

/// Error type for serialization/deserialization operations.
#[derive(Debug, Clone, PartialEq)]
pub enum SerdeError {
    /// JSON/TOML/MsgPack syntax error.
    SyntaxError {
        message: &'static str,
        line: usize,
        column: usize,
    },
    /// Unexpected end of input.
    UnexpectedEof,
    /// Type mismatch during deserialization.
    TypeMismatch {
        expected: &'static str,
        found: &'static str,
    },
    /// Missing required field.
    MissingField(&'static str),
    /// Unknown field encountered.
    UnknownField,
    /// Value out of range.
    OutOfRange(&'static str),
    /// Nesting depth exceeded.
    DepthExceeded(usize),
    /// Invalid Unicode escape or encoding.
    InvalidUnicode,
    /// Duplicate key in map/table.
    DuplicateKey,
    /// Feature not supported.
    Unsupported(&'static str),
    /// Generic error with message.
    Custom(#[cfg(feature = "std")] String, #[cfg(not(feature = "std"))] &'static str),
}

impl fmt::Display for SerdeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::SyntaxError { message, line, column } => {
                write!(f, "syntax error at {}:{}: {}", line, column, message)
            }
            Self::UnexpectedEof => write!(f, "unexpected end of input"),
            Self::TypeMismatch { expected, found } => {
                write!(f, "type mismatch: expected {}, found {}", expected, found)
            }
            Self::MissingField(name) => write!(f, "missing field: {}", name),
            Self::UnknownField => write!(f, "unknown field"),
            Self::OutOfRange(msg) => write!(f, "value out of range: {}", msg),
            Self::DepthExceeded(max) => write!(f, "nesting depth exceeded (max {})", max),
            Self::InvalidUnicode => write!(f, "invalid unicode"),
            Self::DuplicateKey => write!(f, "duplicate key"),
            Self::Unsupported(msg) => write!(f, "unsupported: {}", msg),
            Self::Custom(msg) => write!(f, "{}", msg),
        }
    }
}

#[cfg(feature = "std")]
impl std::error::Error for SerdeError {}

impl SerdeError {
    /// Create a syntax error with position information.
    pub fn syntax(message: &'static str, line: usize, column: usize) -> Self {
        Self::SyntaxError { message, line, column }
    }

    /// Create a syntax error at position 0:0 (for binary formats).
    pub fn syntax_at_zero(message: &'static str) -> Self {
        Self::SyntaxError { message, line: 0, column: 0 }
    }
}
