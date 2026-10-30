# lombokserde (TypeScript / JavaScript)

Zero-dependency JSON (RFC 8259), TOML (v1.0) and MessagePack serialization
with byte-identical output across the five LombokSerde ports
(Rust, Go, TypeScript, Python, PHP).

Part of the [LombokSerde](https://github.com/codinglombok/LombokSerde)
monorepo — the TypeScript port passes the 176 shared deterministic vectors
bit for bit in CI (`vectors/lombokserde-vectors-v1.json`).

## Install

```bash
npm install lombokserde
```

Dual ESM + CJS build with TypeScript types included. Node >= 18,
zero runtime dependencies.

## Quick start

```typescript
import { jsonDecode, jsonEncodeText } from 'lombokserde';

const v = jsonDecode(new TextEncoder().encode('{"hello": "world"}'));
jsonEncodeText(v);                 // '{"hello":"world"}'
```

```javascript
// CommonJS works too
const { jsonDecode, jsonEncodeText, msgpackEncode, tomlEncodeText } =
  require('lombokserde');
```

## API

| Function | Notes |
|---|---|
| `jsonDecode(data: Uint8Array, opts?: JsonOptions): Value` | exactly one value; trailing characters are an error |
| `jsonEncode(v: Value, opts?: JsonOptions): Uint8Array` | sorted keys, pinned float presentation |
| `jsonEncodeText(v: Value, opts?: JsonOptions): string` | encode straight to a string |
| `tomlDecode(data: Uint8Array, opts?)` / `tomlEncode(v, opts?): Uint8Array` / `tomlEncodeText(v, opts?): string` | TOML v1.0 |
| `msgpackDecode(data: Uint8Array, opts?)` / `msgpackEncode(v, opts?): Uint8Array` | minimal-length families |
| `SerdeError` | every failure carries a stable error code |
| `Value`, `Datetime`, `DatetimeKind`, `makeTable`, `tableGet` | the value model shared by all five ports |

Deterministic by contract: table keys are sorted by UTF-8 bytewise order,
floats use shortest-roundtrip digits with pinned presentation rules
(integral floats keep one fractional digit, exponential form from `1e+21`
/ below `1e-7`), and MessagePack uses the minimal-length family for every
type. The same `Value` encodes to exactly the same bytes in every port.

See the [specification](https://github.com/codinglombok/LombokSerde/blob/main/docs/SPEC_LombokSerde_v0.1.0.md)
for the normative details.

## License

Apache-2.0
