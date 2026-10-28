# LombokSerde

[![Lombok Ecosystem](https://img.shields.io/badge/Lombok-Ecosystem-2e7d5b?logo=github)](https://github.com/codinglombok)
[![CI](https://github.com/codinglombok/LombokSerde/actions/workflows/ci.yml/badge.svg)](https://github.com/codinglombok/LombokSerde/actions/workflows/ci.yml)

**JSON · TOML · MessagePack** serialization/deserialization with **byte-identical results** across Rust, TypeScript, Python, Go, and PHP. Zero dependencies.

Part of the [Lombok Ecosystem](https://github.com/codinglombok).

## Mengapa library ini? (Why this library?)

- **Byte-identical across languages.** The same `Value` encodes to exactly the same bytes in every port: table keys are sorted by UTF-8 bytewise order, floats use shortest-roundtrip digits with pinned presentation rules (integral floats keep one fractional digit, exponential form from `1e+21` / below `1e-7`), and MessagePack uses the minimal-length family for every type. All five ports check the 176 shared cases byte for byte in CI, driven by [vectors/lombokserde-vectors-v1.json](vectors/lombokserde-vectors-v1.json) and its `SHA256SUMS`.
- **One contract, five ports, no drift.** The normative contract lives in [docs/SPEC_LombokSerde_v0.1.0.md](docs/SPEC_LombokSerde_v0.1.0.md): key sorting, float rendering, depth limits (default 128), the 64-bit integer boundary rules (`SERDE_JSON_INT_RANGE` beyond i64/u64), and per-format NaN/Infinity behavior (JSON rejects, TOML emits `inf`/`nan`, MessagePack carries the canonical quiet NaN). Deviations from the SPEC are bugs, not dialects.
- **Fail-closed errors you can match on.** Every failure is a stable `[SERDE_<FMT>_<REASON>] message (at byte N)` error with the same code and the same byte offset in every language — so a decoder written against the Rust port debugs identically against the PHP port.
- **Canonical, deterministic output.** No map-iteration order leaks, no platform float formatting differences, no optional whitespace. Encoding the same document twice — in any port, on any OS — yields the same bytes, which makes checksums, cache keys, and cross-service comparisons stable.
- **Zero dependencies.** Pure Rust, pure TypeScript (dual ESM + CJS), pure Python (stdlib only), pure Go (std only), pure PHP (>= 8.1, no extensions required) — nothing to vendor, nothing to audit.

## Installation

| Language | Package | Status |
|---|---|---|
| Rust | `lombokserde` (crates.io) | not yet published |
| TypeScript / JavaScript | `lombokserde` (npm) | not yet published |
| Python | `lombokserde` (PyPI) | not yet published |
| Go | `github.com/codinglombok/lombokserde/go` | tag `go/v0.1.0` on release |
| PHP | `codinglombok/lombokserde` (Packagist) | not yet published |

## Quick start

### Rust

```rust
use lombokserde::{json, value::Value};

let v = json::json_decode(br#"{"hello": "world"}"#, &Default::default()).unwrap();
let bytes = json::json_encode(&v, &Default::default()).unwrap();
assert_eq!(bytes, br#"{"hello":"world"}"#);
```

### TypeScript

```typescript
import { json, table } from 'lombokserde';

const v = json.decode('{"hello": "world"}');
const out = json.encode(v); // '{"hello":"world"}'
```

### Python

```python
import lombokserde as ls

v = ls.json_decode('{"hello": "world"}')
out = ls.json_encode(v)  # '{"hello":"world"}'
```

### Go

```go
import lombokserde "github.com/codinglombok/lombokserde/go"

v, err := lombokserde.JsonDecode([]byte(`{"hello": "world"}`), nil)
out, err := lombokserde.JsonEncode(v, nil) // {"hello":"world"}
```

### PHP

```php
use CodingLombok\LombokSerde\Json;
use CodingLombok\LombokSerde\Value;

$v = Json::decode('{"hello": "world"}');
$out = Json::encode($v); // '{"hello":"world"}'
```

## Ports

| | Rust | TypeScript | Python | Go | PHP |
|---|---|---|---|---|---|
| JSON (RFC 8259) | YES | YES | YES | YES | YES |
| TOML (v1.0) | YES | YES | YES | YES | YES |
| MessagePack | YES | YES | YES | YES | YES |
| timestamp ext (-1) | YES | YES | YES | YES | YES |
| shared vectors | 176/176 | 176/176 | 176/176 | 176/176 | 176/176 |
| ESM + CJS | – | YES | – | – | – |

## Known limitations

Datetime values exist only where the format has them: TOML datetimes round-trip verbatim, and only offset datetimes map to MessagePack timestamps (local datetimes raise `SERDE_MP_DATETIME`). JSON rejects `Bytes` and `Datetime` values on encode (`SERDE_JSON_BYTES`, `SERDE_JSON_DATETIME`). Duplicate keys are errors everywhere — there is no "last one wins". Details: [docs/full_summary_project_LombokSerde_v0.1.0.md](docs/full_summary_project_LombokSerde_v0.1.0.md).

## Versioning

The published version ladder starts at **0.1.0** (this release) and proceeds
in staged steps: `v0.1.0` -> `v0.2.0` -> `v0.3.0` -> ... . Registry versions
are immutable: fixes always ship as new versions and tags are never moved.
The staged release procedure — per-registry workflows, approval gates,
verification, version bumps — is in [docs/how_to_dist_LombokSerde_v0.1.0.md](docs/how_to_dist_LombokSerde_v0.1.0.md).

## Development

```bash
cd rust && cargo test --release && cargo clippy --all-targets -- -D warnings
cd typescript && npm ci && npm run coverage
cd python && python -m pytest
cd go && go test ./...
cd php && php tests/run.php
python3 vectors/build_vectors.py && bash scripts/lombok-doctor.sh LombokSerde
```

## License

Apache-2.0. See [LICENSE](LICENSE).
