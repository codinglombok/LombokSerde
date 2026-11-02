# lombokserde (Python)

Zero-dependency JSON (RFC 8259), TOML (v1.0) and MessagePack serialization
with byte-identical output across the five LombokSerde ports
(Rust, Go, TypeScript, Python, PHP).

Part of the [LombokSerde](https://github.com/codinglombok/LombokSerde)
monorepo — the Python port passes the 176 shared deterministic vectors
bit for bit in CI (`vectors/lombokserde-vectors-v1.json`).

## Install

```bash
pip install lombokserde
```

Requires Python >= 3.9. No dependencies.

## Quick start

```python
import lombokserde as ls

v = ls.json_decode(b'{"hello": "world"}')
out = ls.json_encode(v)            # b'{"hello":"world"}'

t = ls.json_decode(b'{"b": 2, "a": 1}')
ls.json_encode(t)                  # b'{"a":1,"b":2}' — keys sorted bytewise

ls.toml_encode(ls.json_decode(b'{"n": 1}'))    # b'n = 1\n'
ls.msgpack_encode(ls.json_decode(b'[1, 2]'))   # minimal-width families
```

## API

| Function | Notes |
|---|---|
| `json_decode(data: bytes, opts: JsonOptions \| None = None) -> Any` | exactly one value; trailing characters are an error |
| `json_encode(v, opts: JsonOptions \| None = None) -> bytes` | sorted keys, pinned float presentation |
| `toml_decode(data: bytes, opts: TomlOptions \| None = None)` / `toml_encode(v, opts: TomlOptions \| None = None) -> bytes` | TOML v1.0 |
| `msgpack_decode(data: bytes, opts: MsgPackOptions \| None = None)` / `msgpack_encode(v, opts: MsgPackOptions \| None = None) -> bytes` | minimal-length families |
| `SerdeError` | every failure carries a stable error code (`error.SerdeErrorCode`) |
| `Value`, `Datetime`, `DatetimeKind`, `make_table`, `table_get` | the value model shared by all five ports |

Deterministic by contract: table keys are sorted by UTF-8 bytewise order,
floats use shortest-roundtrip digits with pinned presentation rules
(integral floats keep one fractional digit, exponential form from `1e+21`
/ below `1e-7`), and MessagePack uses the minimal-length family for every
type. The same `Value` encodes to exactly the same bytes in every port.

See the [specification](https://github.com/codinglombok/LombokSerde/blob/main/docs/SPEC_LombokSerde_v0.1.0.md)
for the normative details.

## License

Apache-2.0
