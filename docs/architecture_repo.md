# LombokSerde — Architecture

## Overview

LombokSerde is a zero-dependency serialization/deserialization library supporting JSON (RFC 8259), TOML (v1.0), and MessagePack. Part of the LombokRAGFrameworks ecosystem, it replaces `serde` + `serde_json` + `toml` with a focused, multi-language implementation.

## ADR-001: Trait-Based Architecture

**Decision:** Define `Serialize` and `Deserialize` traits that formats implement against, with a `Value` intermediate representation.

**Rationale:**
- Decouples data types from wire formats
- Same data structure serializes to JSON, TOML, or MessagePack without changes
- Matches serde's proven design pattern but with smaller scope
- `Value` enum serves as universal DOM: `Null`, `Bool`, `Integer`, `Float`, `String`, `Array`, `Map`, `Bytes` (MsgPack), `DateTime` (TOML)

**Consequences:**
- Each format implements `to_value`/`from_value` for its wire format
- Rust proc-macro derives trait impls; other languages use reflection or manual impl
- `Value` is the common interchange between formats

## ADR-002: JSON Implementation (RFC 8259)

**Decision:** Full RFC 8259 compliant JSON parser and serializer.

**Features:**
- Recursive descent parser with configurable depth limit (default 128)
- UTF-8 string handling with `\uXXXX` escape sequences (including surrogate pairs)
- Number parsing: integers (i64 range) and IEEE 754 doubles
- Pretty-print with configurable indent
- Streaming tokenizer for large documents (token-by-token without full DOM)

**Trade-offs:**
- No streaming writer (full DOM serialization only) — acceptable for RAG payloads
- No JSON5 or JSONC extensions

## ADR-003: TOML Implementation (v1.0)

**Decision:** TOML v1.0 parser and serializer for configuration files.

**Features:**
- Full key types: bare keys, quoted keys, dotted keys
- All value types: string (basic/literal/multiline), integer, float, bool, datetime, array, inline table
- Table and array-of-tables (`[[section]]`)
- Offset DateTime, Local DateTime, Local Date, Local Time

**Trade-offs:**
- Write support outputs normalized form (not preserving original formatting)
- no_std not supported for TOML (requires alloc + string processing)

## ADR-004: MessagePack Implementation

**Decision:** MessagePack (msgpack.org spec) binary format for IPC.

**Features:**
- All core types: nil, bool, int (positive/negative fixint through uint64/int64), float32/float64
- Raw bytes (bin 8/16/32) and strings (str 8/16/32)
- Arrays (fixarray through array32) and maps (fixmap through map32)
- Extension types (fixext 1/2/4/8/16, ext 8/16/32) — encode/decode with type ID + data

**Trade-offs:**
- No timestamp extension type (app-level concern)
- Big-endian wire format (network byte order per spec)

## ADR-005: no_std Support

**Decision:** Core traits + JSON + MessagePack work in no_std (with alloc). TOML requires std.

**Rationale:**
- JSON and MessagePack are common in embedded/WASM contexts
- TOML config parsing is inherently a std operation
- `alloc` needed for `String`, `Vec`, `BTreeMap`

**Feature Flags (Rust):**
- `json` (default) — JSON parser/serializer
- `toml` — TOML parser/serializer (requires std)
- `msgpack` (default) — MessagePack encoder/decoder
- `std` (default) — std library support

## ADR-006: Cross-Language Port Strategy

**Decision:** Each language implements the same algorithms natively.

| Language | Traits | JSON | TOML | MsgPack | Notes |
|----------|--------|------|------|---------|-------|
| Rust | derive macro | ✅ | ✅ | ✅ | `#![no_std]` with features |
| TypeScript | interface | ✅ | ✅ | ✅ | ES2022, dual CJS+ESM |
| Python | protocol | ✅ | ✅ | ✅ | 3.10+, type hints |
| Go | interface | ✅ | ✅ | ✅ | 1.21+, struct tags |
| PHP | interface | ✅ | ✅ | ✅ | 8.1+, PSR-4 |

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
