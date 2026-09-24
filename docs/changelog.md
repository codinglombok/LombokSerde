# LombokSerde — Changelog

## [0.1.0] - 2026-09-18

### Added
- **Core:** Value IR enum (Null, Bool, Integer, Float, String, Array, Map, Bytes, DateTime)
- **Core:** Serialize/Deserialize trait definitions
- **JSON:** Full RFC 8259 parser (recursive descent, configurable depth limit)
- **JSON:** Serializer with compact and pretty-print modes
- **JSON:** Streaming tokenizer for large documents
- **TOML:** Full v1.0 parser (bare/quoted/dotted keys, all value types, tables, array-of-tables)
- **TOML:** Serializer (normalized output)
- **MessagePack:** Encoder (all core types + extension types)
- **MessagePack:** Decoder (all core types + extension types)
- **Rust:** `no_std` support (json + msgpack features, TOML requires std)
- **Rust:** Feature flags: json, toml, msgpack, std (all default except toml)
- **TypeScript:** ES2022, dual CJS+ESM
- **Python:** 3.10+, type hints, protocol-based traits
- **Go:** 1.21+, interface-based, struct tags
- **PHP:** 8.1+, PSR-4, interface-based
- **CI:** GitHub Actions workflows for all 5 languages
- **Test:** Cross-language test vectors
