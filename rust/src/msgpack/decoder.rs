//! MessagePack decoder.

extern crate alloc;
use alloc::collections::BTreeMap;
use alloc::string::String;
use alloc::vec::Vec;

use crate::error::SerdeError;
use crate::value::Value;

/// Decode MessagePack bytes into a Value.
pub fn decode(input: &[u8]) -> Result<Value, SerdeError> {
    let mut decoder = MsgPackDecoder::new(input);
    let value = decoder.decode_value()?;
    Ok(value)
}

struct MsgPackDecoder<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> MsgPackDecoder<'a> {
    fn new(data: &'a [u8]) -> Self {
        Self { data, pos: 0 }
    }

    fn decode_value(&mut self) -> Result<Value, SerdeError> {
        let byte = self.read_u8()?;
        match byte {
            // Positive fixint
            0x00..=0x7F => Ok(Value::Integer(byte as i64)),
            // Negative fixint
            0xE0..=0xFF => Ok(Value::Integer(byte as i8 as i64)),
            // Fixmap
            0x80..=0x8F => {
                let len = (byte & 0x0F) as usize;
                self.decode_map(len)
            }
            // Fixarray
            0x90..=0x9F => {
                let len = (byte & 0x0F) as usize;
                self.decode_array(len)
            }
            // Fixstr
            0xA0..=0xBF => {
                let len = (byte & 0x1F) as usize;
                self.decode_string(len)
            }
            // nil
            0xC0 => Ok(Value::Null),
            // (never used)
            0xC1 => Err(SerdeError::syntax_at_zero("reserved msgpack byte 0xC1")),
            // false
            0xC2 => Ok(Value::Bool(false)),
            // true
            0xC3 => Ok(Value::Bool(true)),
            // bin 8
            0xC4 => {
                let len = self.read_u8()? as usize;
                self.decode_bin(len)
            }
            // bin 16
            0xC5 => {
                let len = self.read_u16()? as usize;
                self.decode_bin(len)
            }
            // bin 32
            0xC6 => {
                let len = self.read_u32()? as usize;
                self.decode_bin(len)
            }
            // ext 8
            0xC7 => {
                let len = self.read_u8()? as usize;
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(len) // Store ext data as bytes
            }
            // ext 16
            0xC8 => {
                let len = self.read_u16()? as usize;
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(len)
            }
            // ext 32
            0xC9 => {
                let len = self.read_u32()? as usize;
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(len)
            }
            // float 32
            0xCA => {
                let bits = self.read_u32()?;
                Ok(Value::Float(f32::from_bits(bits) as f64))
            }
            // float 64
            0xCB => {
                let bits = self.read_u64()?;
                Ok(Value::Float(f64::from_bits(bits)))
            }
            // uint 8
            0xCC => Ok(Value::Integer(self.read_u8()? as i64)),
            // uint 16
            0xCD => Ok(Value::Integer(self.read_u16()? as i64)),
            // uint 32
            0xCE => Ok(Value::Integer(self.read_u32()? as i64)),
            // uint 64
            0xCF => {
                let u = self.read_u64()?;
                if u > i64::MAX as u64 {
                    // Store as float for values > i64::MAX
                    Ok(Value::Float(u as f64))
                } else {
                    Ok(Value::Integer(u as i64))
                }
            }
            // int 8
            0xD0 => Ok(Value::Integer(self.read_u8()? as i8 as i64)),
            // int 16
            0xD1 => Ok(Value::Integer(self.read_u16()? as i16 as i64)),
            // int 32
            0xD2 => Ok(Value::Integer(self.read_u32()? as i32 as i64)),
            // int 64
            0xD3 => {
                let bits = self.read_u64()?;
                Ok(Value::Integer(bits as i64))
            }
            // fixext 1
            0xD4 => {
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(1)
            }
            // fixext 2
            0xD5 => {
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(2)
            }
            // fixext 4
            0xD6 => {
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(4)
            }
            // fixext 8
            0xD7 => {
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(8)
            }
            // fixext 16
            0xD8 => {
                let _type_id = self.read_u8()? as i8;
                self.decode_bin(16)
            }
            // str 8
            0xD9 => {
                let len = self.read_u8()? as usize;
                self.decode_string(len)
            }
            // str 16
            0xDA => {
                let len = self.read_u16()? as usize;
                self.decode_string(len)
            }
            // str 32
            0xDB => {
                let len = self.read_u32()? as usize;
                self.decode_string(len)
            }
            // array 16
            0xDC => {
                let len = self.read_u16()? as usize;
                self.decode_array(len)
            }
            // array 32
            0xDD => {
                let len = self.read_u32()? as usize;
                self.decode_array(len)
            }
            // map 16
            0xDE => {
                let len = self.read_u16()? as usize;
                self.decode_map(len)
            }
            // map 32
            0xDF => {
                let len = self.read_u32()? as usize;
                self.decode_map(len)
            }
            _ => Err(SerdeError::syntax_at_zero("unknown msgpack format byte")),
        }
    }

    fn decode_string(&mut self, len: usize) -> Result<Value, SerdeError> {
        let bytes = self.read_bytes(len)?;
        let s = core::str::from_utf8(bytes)
            .map_err(|_| SerdeError::InvalidUnicode)?;
        Ok(Value::String(String::from(s)))
    }

    fn decode_bin(&mut self, len: usize) -> Result<Value, SerdeError> {
        let bytes = self.read_bytes(len)?;
        Ok(Value::Bytes(bytes.to_vec()))
    }

    fn decode_array(&mut self, len: usize) -> Result<Value, SerdeError> {
        let mut arr = Vec::with_capacity(len);
        for _ in 0..len {
            arr.push(self.decode_value()?);
        }
        Ok(Value::Array(arr))
    }

    fn decode_map(&mut self, len: usize) -> Result<Value, SerdeError> {
        let mut map = BTreeMap::new();
        for _ in 0..len {
            let key_val = self.decode_value()?;
            let key = match key_val {
                Value::String(s) => s,
                other => alloc::format!("{:?}", other), // Fallback for non-string keys
            };
            let val = self.decode_value()?;
            map.insert(key, val);
        }
        Ok(Value::Map(map))
    }

    // --- Read helpers ---

    fn read_u8(&mut self) -> Result<u8, SerdeError> {
        if self.pos >= self.data.len() {
            return Err(SerdeError::UnexpectedEof);
        }
        let b = self.data[self.pos];
        self.pos += 1;
        Ok(b)
    }

    fn read_u16(&mut self) -> Result<u16, SerdeError> {
        if self.pos + 2 > self.data.len() {
            return Err(SerdeError::UnexpectedEof);
        }
        let val = u16::from_be_bytes([self.data[self.pos], self.data[self.pos + 1]]);
        self.pos += 2;
        Ok(val)
    }

    fn read_u32(&mut self) -> Result<u32, SerdeError> {
        if self.pos + 4 > self.data.len() {
            return Err(SerdeError::UnexpectedEof);
        }
        let val = u32::from_be_bytes([
            self.data[self.pos],
            self.data[self.pos + 1],
            self.data[self.pos + 2],
            self.data[self.pos + 3],
        ]);
        self.pos += 4;
        Ok(val)
    }

    fn read_u64(&mut self) -> Result<u64, SerdeError> {
        if self.pos + 8 > self.data.len() {
            return Err(SerdeError::UnexpectedEof);
        }
        let val = u64::from_be_bytes([
            self.data[self.pos],
            self.data[self.pos + 1],
            self.data[self.pos + 2],
            self.data[self.pos + 3],
            self.data[self.pos + 4],
            self.data[self.pos + 5],
            self.data[self.pos + 6],
            self.data[self.pos + 7],
        ]);
        self.pos += 8;
        Ok(val)
    }

    fn read_bytes(&mut self, len: usize) -> Result<&'a [u8], SerdeError> {
        if self.pos + len > self.data.len() {
            return Err(SerdeError::UnexpectedEof);
        }
        let bytes = &self.data[self.pos..self.pos + len];
        self.pos += len;
        Ok(bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::encoder;

    #[test]
    fn test_roundtrip_nil() {
        let encoded = encoder::encode(&Value::Null);
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, Value::Null);
    }

    #[test]
    fn test_roundtrip_bool() {
        for b in [true, false] {
            let encoded = encoder::encode(&Value::Bool(b));
            let decoded = decode(&encoded).unwrap();
            assert_eq!(decoded, Value::Bool(b));
        }
    }

    #[test]
    fn test_roundtrip_integers() {
        for n in [0, 1, 127, 128, 255, 256, 65535, 65536, -1, -32, -33, -128, -129, -32768, -32769] {
            let encoded = encoder::encode(&Value::Integer(n));
            let decoded = decode(&encoded).unwrap();
            assert_eq!(decoded, Value::Integer(n), "roundtrip failed for {}", n);
        }
    }

    #[test]
    fn test_roundtrip_float() {
        let encoded = encoder::encode(&Value::Float(3.14));
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, Value::Float(3.14));
    }

    #[test]
    fn test_roundtrip_string() {
        let encoded = encoder::encode(&Value::String("hello world".into()));
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, Value::String("hello world".into()));
    }

    #[test]
    fn test_roundtrip_array() {
        let v = Value::Array(vec![Value::Integer(1), Value::String("two".into()), Value::Null]);
        let encoded = encoder::encode(&v);
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, v);
    }

    #[test]
    fn test_roundtrip_map() {
        let mut map = BTreeMap::new();
        map.insert("key".to_string(), Value::Integer(42));
        map.insert("nested".to_string(), Value::Array(vec![Value::Bool(true)]));
        let v = Value::Map(map);
        let encoded = encoder::encode(&v);
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, v);
    }

    #[test]
    fn test_roundtrip_bytes() {
        let v = Value::Bytes(vec![0xDE, 0xAD, 0xBE, 0xEF]);
        let encoded = encoder::encode(&v);
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, v);
    }
}
