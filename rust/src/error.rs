//! Error type shared by every LombokSerde port.
//!
//! The wire format of an error is `[CODE] message` and, when a byte offset
//! applies, `[CODE] message (at byte N)`. Error codes are stable strings
//! shared across all language ports (see the SPEC).

use std::fmt;

/// A LombokSerde error. `code` is one of the stable `SERDE_*` codes listed
/// in the SPEC; `offset` is the byte offset into the input when one applies.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SerdeError {
    /// Stable error code, e.g. `SERDE_JSON_SYNTAX`.
    pub code: &'static str,
    /// Human-readable detail. The `[CODE]` prefix is never part of it.
    pub message: String,
    /// Byte offset into the input, when a position applies.
    pub offset: Option<usize>,
}

impl SerdeError {
    pub fn new(code: &'static str, message: impl Into<String>, offset: Option<usize>) -> Self {
        SerdeError {
            code,
            message: message.into(),
            offset,
        }
    }

    pub fn syntax(code: &'static str, offset: usize, detail: &'static str) -> Self {
        SerdeError::new(code, detail, Some(offset))
    }
}

impl fmt::Display for SerdeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.offset {
            Some(n) => write!(f, "[{}] {} (at byte {})", self.code, self.message, n),
            None => write!(f, "[{}] {}", self.code, self.message),
        }
    }
}

impl std::error::Error for SerdeError {}
