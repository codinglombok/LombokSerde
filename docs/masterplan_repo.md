# LombokSerde — Masterplan

## Mission

Zero-dependency serialization/deserialization library for the LombokRAGFrameworks ecosystem, replacing `serde` + `serde_json` + `toml` with a focused, multi-language implementation covering JSON (RFC 8259), TOML (v1.0), and MessagePack.

## Phase 1: Core Architecture (Rust)

### 1.1 Value IR & Traits
- `Value` enum: Null, Bool, Integer(i64), Float(f64), String, Array, Map, Bytes, DateTime
- `Serialize` trait: `fn serialize(&self) -> Result<Value, SerdeError>`
- `Deserialize` trait: `fn deserialize(value: &Value) -> Result<Self, SerdeError>`
- Error types: `SerdeError` with format-specific variants

### 1.2 JSON (RFC 8259)
- Recursive descent parser with configurable depth limit (default 128)
- UTF-8 with `\uXXXX` escape sequences (including surrogate pairs)
- Number parsing: i64 integers + f64 doubles
- Pretty-print with configurable indent
- Streaming tokenizer (token-by-token without full DOM)

### 1.3 TOML (v1.0)
- Full key types: bare, quoted, dotted
- All value types: string (basic/literal/multiline), integer, float, bool, datetime, array, inline table
- Table and array-of-tables (`[[section]]`)
- DateTime variants: Offset, Local DateTime, Local Date, Local Time

### 1.4 MessagePack
- All core types: nil, bool, int (fixint through uint64/int64), float32/float64
- Raw bytes (bin 8/16/32) and strings (str 8/16/32)
- Arrays (fixarray through array32) and maps (fixmap through map32)
- Extension types (fixext 1/2/4/8/16, ext 8/16/32)

### 1.5 Derive Macro
- `#[derive(LombokSerialize, LombokDeserialize)]` proc-macro
- Struct field mapping with `#[lombok(rename = "...")]`
- Optional fields with `#[lombok(default)]`
- Enum variant serialization

## Phase 2: Language Ports

### 2.1 TypeScript
- ES2022, dual CJS+ESM output
- Interface-based Serialize/Deserialize
- Uint8Array for binary data
- Full test parity with Rust

### 2.2 Python
- Python 3.10+, type hints throughout
- Protocol-based Serialize/Deserialize
- `bytes` for binary data
- dataclass integration

### 2.3 Go
- Go 1.21+, interface-based
- Struct tags for field mapping (`lombok:"name,omitempty"`)
- `[]byte` for binary data

### 2.4 PHP
- PHP 8.1+, PSR-4 autoloading
- Interface-based with attributes for field mapping
- Full type declarations

## Phase 3: Cross-Language Verification

- Shared test vectors in `test-vectors/serde_vectors.json`
- Round-trip tests: value → JSON → value, value → TOML → value, value → MsgPack → value
- Cross-format: JSON → Value → TOML (where types overlap)
- Edge cases: Unicode, large numbers, nested depth, empty structures

## Performance Targets

| Operation | Target |
|-----------|--------|
| JSON parse 1KB | < 50μs |
| JSON serialize 1KB | < 30μs |
| MsgPack encode 1KB | < 20μs |
| MsgPack decode 1KB | < 20μs |
| TOML parse 1KB config | < 100μs |
| Max JSON depth | 128 (configurable) |
| Max string length | 256MB |

## Feature Flags (Rust)

- `json` (default) — JSON parser/serializer
- `toml` — TOML parser/serializer (requires std)
- `msgpack` (default) — MessagePack encoder/decoder
- `std` (default) — std library support
- `derive` (default) — proc-macro derives

## Success Criteria

1. All 5 languages pass shared test vectors
2. JSON roundtrip matches RFC 8259 test suite
3. TOML roundtrip matches TOML v1.0 test suite
4. MessagePack roundtrip matches msgpack spec
5. `no_std` builds for Rust (json + msgpack features)
6. Zero external dependencies in all languages
