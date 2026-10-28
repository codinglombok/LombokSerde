# SPEC LombokSerde v0.1.0

| Versi SPEC | 0.1.0 |
|---|---|
| Status | Normatif (contract) |
| Berlaku untuk | Rust, TypeScript, Python, Go, PHP ports |
| Vector set | vectors/lombokserde-vectors-v1.json (vector set 1) |
| Vector SHA-256 | fc2b8268748f4af52a199e823ddbb9ba6ff6f1be65b081a36e95ce6bb2bb82f1 |

This document is the normative cross-language contract. Every language port MUST produce byte-identical output for all specified inputs. Deviations from this specification are bugs.

## 1. Value model

All formats operate on one canonical tagged-union value:

| Kind | Payload | Notes |
|---|---|---|
| `null` | – | JSON `null`, MessagePack nil; illegal in TOML |
| `bool` | boolean | JSON `true`/`false`, TOML `true`/`false`, MP 0xc2/0xc3 |
| `int` | 64-bit signed | Range `[-2^63, 2^63-1]` |
| `uint` | 64-bit unsigned | Range `[2^63, 2^64-1]` only (values below `2^63` are `int`) |
| `float` | binary64 | IEEE 754; NaN carries the canonical quiet bit pattern |
| `str` | Unicode text | Must be valid UTF-8 when decoded |
| `bytes` | byte string | MessagePack bin family only |
| `array` | list of values | Heterogeneous allowed except in TOML (single-type arrays only) |
| `table` | ordered key/value pairs | Sorted bytewise by key (section 3); duplicates fail closed |
| `datetime` | kind + raw text | TOML only: `offset`, `localdt`, `date`, `time` |

Table invariants: entries are sorted by UTF-8 bytewise order of the key, and a
duplicate key is an error (`SERDE_TABLE_DUPLICATE` at construction; the
per-format codecs re-wrap it, see section 7).

## 2. Canonical encoding rules

1. **Key order** — table keys are sorted by their UTF-8 byte sequences
   (unsigned byte-wise comparison). This is the Unicode code-point order for
   valid UTF-8, and it is stable across every port without locale dependence.
2. **Float presentation** — a finite float renders as its
   shortest-roundtrip decimal digits (the platform formatter must be
   correctly rounded), then is re-rendered with the pinned rules:
   - zero renders as `0.0` / `-0.0` (sign preserved);
   - integral values keep one fractional digit: `1` renders as `1.0`;
   - exponential form iff the decimal exponent is `>= 21` or `<= -7`;
   - the exponent is always signed and never zero-padded: `1e+21`, `1.5e-7`.
3. **Float overflow/underflow on decode** — JSON and TOML number literals
   round per IEEE 754 nearest: overflow yields `±Inf` and underflow yields
   `±0`; neither is an error on decode. Re-encoding a non-finite float to
   JSON is an error (section 7); TOML renders `inf`/`-inf`/`nan`; MessagePack
   carries the bits.
4. **Integer boundaries** — JSON integers beyond `[-2^63, 2^64-1]` fail with
   `SERDE_JSON_INT_RANGE`. TOML integers are signed 64-bit only; unsigned
   values above `2^63-1` fail encoding with `SERDE_TOML_SYNTAX`. MessagePack
   integers round-trip exactly; values in `[2^63, 2^64-1]` decode as `uint`.
5. **Depth limit** — container nesting is limited by the port's options
   (default 128, per-port overridable). The outermost container is depth 1.
   Exceeding it fails with `SERDE_<FMT>_DEPTH`.
6. **Trailing input** — after exactly one top-level value, any remaining
   non-whitespace (JSON) or any remaining byte (MessagePack) fails with
   `SERDE_JSON_TRAILING` / `SERDE_MP_TRAILING`.
7. **Duplicate keys** — JSON objects, TOML documents, inline tables, and
   MessagePack maps with duplicate keys fail closed. MessagePack duplicate
   keys fail with `SERDE_MP_DUPLICATE`; JSON with `SERDE_JSON_SYNTAX`;
   TOML with `SERDE_TOML_DUPLICATE` (or `SERDE_TOML_SYNTAX` inside inline
   tables).

## 3. JSON rules (RFC 8259, strict)

Decode: UTF-8 is validated first (`SERDE_JSON_UTF8` at the first bad byte).
Literals are `true`, `false`, `null` (anything else starting with those
letters fails as syntax). Numbers follow the RFC grammar without leading
zeros. `\uXXXX` escapes must form valid pairs: lone surrogates fail as
syntax. Raw control characters in strings fail. Exactly one top-level value
is consumed.

Encode: compact separators (`,`, `:`), bytewise key order, the pinned float
presentation of section 2. `/` is not escaped; control characters `< 0x20`
use lowercase `\u00xx`. `bytes` and `datetime` values fail with
`SERDE_JSON_BYTES` / `SERDE_JSON_DATETIME`; non-finite floats fail with
`SERDE_JSON_FLOAT_NANINF`.

## 4. TOML rules (v1.0, strict)

Decode: the document root is a table. Table headers `[a.b]`, array-of-tables
headers `[[a]]`, dotted keys, inline tables, and all string/number/datetime
forms of TOML v1.0 are supported. Signs are not allowed on hex/oct/bin
integers. Dotted keys cannot extend array-of-tables elements. A table header
may not redefine an explicitly defined table or a dotted-key table. Datetime
tokens are validated by shape; invalid shape-shaped tokens fail with
`SERDE_TOML_SYNTAX` at the token start. Local time may contain a leap second
(`:60`); offset datetimes may not.

Encode: the root must be a table (`SERDE_TOML_ROOT` otherwise). Output order
is scalars first, then `[sub-tables]`, then `[[array-of-tables]]`, each
group in bytewise key order; every array value renders as a single-line
inline array. Strings use basic-string quoting with the escapes
`\" \\ \b \t \n \f \r` and `\u00xx` for other control characters and DEL.
Non-finite floats render as `nan`/`inf`/`-inf`. `null` and `bytes` fail.

## 5. MessagePack rules

Decode: all core type codes are supported. `0xc1` fails with
`SERDE_MP_UNEXPECTED`. Extension types other than `-1` fail with
`SERDE_MP_EXT`. The `timestamp` extension (`-1`) decodes from the 4-byte
(timestamp32), 8-byte (timestamp64) and 12-byte (timestamp96) carriers into
an offset `datetime` whose raw text is the canonical `YYYY-MM-DDTHH:MM:SS[.fff]Z`
form. Map keys must be strings. Length fields below the minimum for their
type fail. UTF-8 in strings is validated (`SERDE_MP_UTF8`).

Encode: minimal-length families (positive fixint / fixmap / fixarray /
fixstr, then u8/u16/u32 widths; negative fixint for `[-32, -1]`; int8/16/32/64
and uint8/16/32/64 by magnitude). Floats always use float64 with the
canonical quiet NaN. Timestamps use the compact carrier: timestamp32 when
the nanoseconds are zero and the seconds fit in u32, else timestamp64 when
the seconds are below `2^34`, else timestamp96. Only offset datetimes map to
timestamps; other datetime kinds fail with `SERDE_MP_DATETIME`.

## 6. Datetime

`datetime` values carry a kind (`offset`, `localdt`, `date`, `time`) and the
exact raw source text. TOML preserves raw text verbatim (including the
space separator and lowercase `t`/`z` when decoded). MessagePack timestamps
decode to the canonical `...Z` form. There is no datetime representation in
JSON; encoding one fails (section 3).

## 7. Error codes

Display format: `[CODE] message` or `[CODE] message (at byte N)`, where N is
the byte offset into the input. The offsets are part of the contract and are
pinned by the shared vectors.

| Code | Meaning |
|---|---|
| `SERDE_JSON_SYNTAX` | malformed JSON (also duplicate object keys) |
| `SERDE_JSON_UTF8` | invalid UTF-8 in the input |
| `SERDE_JSON_DEPTH` | nesting exceeds the depth limit |
| `SERDE_JSON_TRAILING` | trailing characters after the top-level value |
| `SERDE_JSON_INT_RANGE` | integer literal outside i64/u64 |
| `SERDE_JSON_FLOAT_NANINF` | non-finite float on encode |
| `SERDE_JSON_BYTES` | bytes value on JSON encode |
| `SERDE_JSON_DATETIME` | datetime value on JSON encode |
| `SERDE_TOML_SYNTAX` | malformed TOML (including signed radix integers) |
| `SERDE_TOML_UTF8` | invalid UTF-8 in the input |
| `SERDE_TOML_DUPLICATE` | duplicate key or table definition |
| `SERDE_TOML_DEPTH` | nesting exceeds the depth limit |
| `SERDE_TOML_ROOT` | encode root is not a table |
| `SERDE_TOML_BYTES` | bytes value on TOML encode |
| `SERDE_TOML_DATETIME` | invalid datetime raw text on encode |
| `SERDE_MP_TRUNCATED` | input ends mid-value |
| `SERDE_MP_UNEXPECTED` | reserved/invalid type code, bad key type, bad length |
| `SERDE_MP_TRAILING` | trailing bytes after the top-level value |
| `SERDE_MP_UTF8` | invalid UTF-8 in a string |
| `SERDE_MP_EXT` | unsupported extension type or payload length |
| `SERDE_MP_DEPTH` | nesting exceeds the depth limit |
| `SERDE_MP_DUPLICATE` | duplicate map key |
| `SERDE_MP_DATETIME` | datetime cannot map to a timestamp |
| `SERDE_TABLE_DUPLICATE` | duplicate key when a table is built |

## 8. Test vectors

`vectors/lombokserde-vectors-v1.json` holds 176 deterministic cases
(122 success, 54 error) across JSON, TOML and MessagePack in both
directions. The generator is `vectors/build_vectors.py`; its output is
byte-stable, and `vectors/SHA256SUMS` pins the file. The vector file for
vector set 1 has SHA-256:

```
fc2b8268748f4af52a199e823ddbb9ba6ff6f1be65b081a36e95ce6bb2bb82f1  vectors/lombokserde-vectors-v1.json
```

Every port must pass every case: success cases compare the decoded value and
the re-encoded bytes; error cases compare the code and the byte offset.
Contract changes follow the SPEC-first protocol: change this document,
regenerate the vectors, refresh the checksums, then port the change to all
runners in the same change set.
