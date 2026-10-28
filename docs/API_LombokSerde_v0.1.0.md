# API LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | API publik kelima port |

## Rust (crate `lombokserde`)

```rust
use lombokserde::{json_decode, json_encode, toml_decode, toml_encode,
                  msgpack_decode, msgpack_encode, JsonOptions, TomlOptions,
                  MsgPackOptions, Value, SerdeError};

let v: Result<Value, SerdeError> = json_decode(br#"{"a":1}"#, &JsonOptions::default());
let out: Result<Vec<u8>, SerdeError> = json_encode(&v.unwrap(), &JsonOptions::default());
```

- `Value` — tagged enum (`Null`, `Bool`, `Int(i64)`, `UInt(u64)`, `Float(f64)`,
  `Str`, `Bytes`, `Array`, `Table`, `Datetime`).
- Options structs expose `depth_limit` (default 128).
- `SerdeError` carries `code: String` and `offset: Option<usize>`;
  `Display` renders `[CODE] message (at byte N)`.

## TypeScript (npm `lombokserde`)

```typescript
import { json, toml, msgpack, type Value, JsonOptions, TomlOptions, MsgPackOptions } from 'lombokserde';

const v: Value = json.decode('{"a":1}');           // accepts string | Uint8Array
const out: string = json.encode(v);
const mb: Uint8Array = msgpack.encode(v);
```

- `Value` is a discriminated union on the `t` field (`null`, `bool`, `int`,
  `uint`, `float`, `str`, `bytes`, `array`, `table`, `datetime`); `int`/`uint`
  payloads are `bigint`.
- Constructors: `makeTable(pairs)` (sorts, fails closed on duplicates) and
  `tableUnchecked(pairs)`.
- `SerdeError` extends `Error` with `code: string` and `offset: number | null`.

## Python (PyPI `lombokserde`)

```python
import lombokserde as ls

v = ls.json_decode('{"a":1}', ls.JsonOptions(depth=128))
out = ls.json_encode(v)
```

- Values are tagged tuples: `("null",)`, `("bool", b)`, `("int", i)`,
  `("uint", u)`, `("float", f)`, `("str", s)`, `("bytes", b)`,
  `("array", [..])`, `("table", ((k, v), ..))`, `("datetime", kind, raw)`.
- Options: `ls.JsonOptions(depth=...)`, `ls.TomlOptions(depth=...)`,
  `ls.MsgPackOptions(depth=...)`.
- `ls.SerdeError` carries `code: str` and `offset: int | None`.

## Go (module `github.com/codinglombok/lombokserde/go`)

```go
import lombokserde "github.com/codinglombok/lombokserde/go"

v, err := lombokserde.JsonDecode(data, nil)        // *JsonOptions or nil
out, err := lombokserde.JsonEncode(v, nil)          // []byte
```

- `Value` is a struct with `Kind` plus typed fields; constructors
  `NewNull`, `NewBool`, `NewInt`, `NewUint`, `NewFloat`, `NewStr`,
  `NewBytes`, `NewArray`, `NewTable`, `TableUnchecked`, `NewDatetime`.
- `TableGet(key) (Value, bool)` performs a bytewise binary search.
- Options structs: `JsonOptions`, `TomlOptions`, `MsgPackOptions`
  (`DepthLimit`, default 128); `nil` options mean the defaults.
- `*Error` implements `error` with `Code string` and `Offset *int`.

## PHP (Packagist `codinglombok/lombokserde`)

```php
use CodingLombok\LombokSerde\Json;
use CodingLombok\LombokSerde\Toml;
use CodingLombok\LombokSerde\Msgpack;
use CodingLombok\LombokSerde\JsonOptions;
use CodingLombok\LombokSerde\Value;

$v = Json::decode('{"a":1}', new JsonOptions(128));
$out = Json::encode($v);
```

- `Value` is a final class with a `kind` discriminator and typed readonly
  fields; constructors are static factories (`Value::int`, `Value::uint`,
  `Value::table`, ...). `uint` payloads are canonical decimal strings
  (PHP ints are signed 64-bit).
- `Value::tableGet(string $key): ?Value` performs the bytewise binary search.
- Options: `JsonOptions`, `TomlOptions`, `MsgPackOptions` with
  `depthLimit` (default 128); `null` means the defaults.
- `SerdeError extends RuntimeException` exposes `code(): string` and
  `offset: ?int` (the `code` accessor is a method because `\Exception`
  reserves a `$code` property).

## Cross-port conventions

- Error codes are identical strings in all ports; byte offsets match exactly.
- Options are value objects; `depth_limit: 0` (Go/PHP) or `0`/`null` means
  "use the default 128", mirroring the reference Rust behavior.
- Every port ships a vector runner that loads
  `vectors/lombokserde-vectors-v1.json` and fails on any mismatch; CI runs
  them all (see `docs/structure_repo_LombokSerde_v0.1.0.md`).
