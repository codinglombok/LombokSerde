# LombokSerde

**JSON · TOML · MessagePack** — zero-dependency serialization/deserialization library.

Part of the [LombokRAGFrameworks](https://github.com/codinglombok/LombokRAGFrameworks) ecosystem (Library #04).

## Features

- **JSON** (RFC 8259) — full parser with configurable depth limit, surrogate pair handling, pretty-printer
- **TOML** (v1.0) — complete parser/serializer with all value types, tables, array-of-tables, datetime
- **MessagePack** — full encoder/decoder for all core types
- **Zero dependencies** — no external libraries required in any language
- **Multi-language** — Rust (core), TypeScript, Python, Go, PHP

## Quick Start

### Rust
```rust
use lombokserde::json;
let value = json::parse(r#"{"hello": "world"}"#).unwrap();
let output = json::to_string(&value);
```

### TypeScript
```typescript
import { json, toml, msgpack } from 'lombokserde';
const value = json.parse('{"hello": "world"}');
const output = json.stringify(value);
```

### Python
```python
from lombokserde import json, toml, msgpack
value = json.parse('{"hello": "world"}')
output = json.to_string(value)
```

### Go
```go
import jsonpkg "github.com/codinglombok/LombokSerde/go/json"
value, _ := jsonpkg.Parse(`{"hello": "world"}`)
output := jsonpkg.ToString(value)
```

### PHP
```php
use LombokSerde\Json\JsonParser;
use LombokSerde\Json\JsonSerializer;
$value = JsonParser::parse('{"hello": "world"}');
$output = JsonSerializer::toString($value);
```

## License

Apache-2.0
