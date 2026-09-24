//! Serialize and Deserialize trait definitions.

use crate::error::SerdeError;
use crate::value::Value;

/// Trait for types that can be serialized to a Value.
pub trait Serialize {
    /// Convert this value to the intermediate Value representation.
    fn serialize(&self) -> Result<Value, SerdeError>;
}

/// Trait for types that can be deserialized from a Value.
pub trait Deserialize: Sized {
    /// Construct this type from the intermediate Value representation.
    fn deserialize(value: &Value) -> Result<Self, SerdeError>;
}

// --- Primitive implementations ---

impl Serialize for bool {
    fn serialize(&self) -> Result<Value, SerdeError> {
        Ok(Value::Bool(*self))
    }
}

impl Deserialize for bool {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        value.as_bool().ok_or(SerdeError::TypeMismatch {
            expected: "bool",
            found: value.type_name(),
        })
    }
}

impl Serialize for i64 {
    fn serialize(&self) -> Result<Value, SerdeError> {
        Ok(Value::Integer(*self))
    }
}

impl Deserialize for i64 {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        value.as_integer().ok_or(SerdeError::TypeMismatch {
            expected: "integer",
            found: value.type_name(),
        })
    }
}

impl Serialize for i32 {
    fn serialize(&self) -> Result<Value, SerdeError> {
        Ok(Value::Integer(*self as i64))
    }
}

impl Deserialize for i32 {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        let n = i64::deserialize(value)?;
        i32::try_from(n).map_err(|_| SerdeError::OutOfRange("i32"))
    }
}

impl Serialize for f64 {
    fn serialize(&self) -> Result<Value, SerdeError> {
        Ok(Value::Float(*self))
    }
}

impl Deserialize for f64 {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        match value {
            Value::Float(f) => Ok(*f),
            Value::Integer(n) => Ok(*n as f64),
            _ => Err(SerdeError::TypeMismatch {
                expected: "float",
                found: value.type_name(),
            }),
        }
    }
}

impl Serialize for alloc::string::String {
    fn serialize(&self) -> Result<Value, SerdeError> {
        Ok(Value::String(self.clone()))
    }
}

impl Deserialize for alloc::string::String {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        value.as_str().map(|s| s.to_string()).ok_or(SerdeError::TypeMismatch {
            expected: "string",
            found: value.type_name(),
        })
    }
}

impl<T: Serialize> Serialize for alloc::vec::Vec<T> {
    fn serialize(&self) -> Result<Value, SerdeError> {
        let arr: Result<alloc::vec::Vec<Value>, _> = self.iter().map(|v| v.serialize()).collect();
        Ok(Value::Array(arr?))
    }
}

impl<T: Deserialize> Deserialize for alloc::vec::Vec<T> {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        match value {
            Value::Array(arr) => arr.iter().map(|v| T::deserialize(v)).collect(),
            _ => Err(SerdeError::TypeMismatch {
                expected: "array",
                found: value.type_name(),
            }),
        }
    }
}

impl<T: Serialize> Serialize for Option<T> {
    fn serialize(&self) -> Result<Value, SerdeError> {
        match self {
            Some(v) => v.serialize(),
            None => Ok(Value::Null),
        }
    }
}

impl<T: Deserialize> Deserialize for Option<T> {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        if value.is_null() {
            Ok(None)
        } else {
            T::deserialize(value).map(Some)
        }
    }
}

// Value itself implements both traits (identity transform)
impl Serialize for Value {
    fn serialize(&self) -> Result<Value, SerdeError> {
        Ok(self.clone())
    }
}

impl Deserialize for Value {
    fn deserialize(value: &Value) -> Result<Self, SerdeError> {
        Ok(value.clone())
    }
}
