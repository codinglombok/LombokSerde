# structure_repo LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Struktur direktori repositori dan peran tiap bagian |

```
LombokSerde/
├── .github/workflows/     CI + staged release workflows (SHA-pinned actions)
│   ├── ci.yml             per-port matrix jobs, coverage gates, standards job
│   ├── release.yml        tag v* -> check-version -> crates/npm/pypi/go-tag/gh-release
│   ├── release-npm.yml    staged npm publish (workflow_dispatch, dry_run default true)
│   ├── release-crates.yml staged crates.io publish (dry_run default true)
│   └── release-pypi.yml   staged PyPI publish (dry_run default true)
├── docs/                  documentation pack v3 (10 public docs, versioned names)
├── go/                    Go port (module github.com/codinglombok/lombokserde/go)
│   ├── json.go            JSON parser
│   ├── json_write.go      JSON writer
│   ├── toml.go            TOML parser + serializer
│   ├── msgpack.go         MessagePack codec + calendar math
│   ├── float.go           pinned float renderer
│   ├── value.go           tagged value model
│   ├── error.go           stable error codes + Error type
│   ├── units_test.go      unit battery
│   └── vectors_test.go    shared vector runner (176 cases)
├── php/                   PHP port (PSR-4 CodingLombok\LombokSerde)
│   ├── src/               Value, SerdeError(+codes), U64, FloatFormat, Json,
│   │                      Toml, TomlParser, Msgpack
│   └── tests/             bootstrap.php, vectors.php, units.php, run.php
├── python/                Python port (PEP 621, stdlib only)
│   ├── lombokserde/       __init__, value, error, _float, _json, _toml, _msgpack
│   └── tests/             test_units.py, test_vectors.py, vectors_common.py
├── rust/                  Rust reference implementation (crate lombokserde)
│   ├── src/               lib, value, error, float, json, toml, msgpack
│   └── tests/             units.rs, vectors.rs
├── typescript/            TypeScript port (dual ESM + CJS)
│   ├── src/               value, error, float, json, toml, msgpack, index
│   ├── tests/             units.test.ts, vectors.test.ts, fuzz.test.ts, vve.ts
│   └── vitest.config.ts   coverage thresholds 95/90
├── vectors/               shared contract artifacts
│   ├── build_vectors.py   deterministic generator (embedded reference codec)
│   ├── lombokserde-vectors-v1.json   176 cases (122 success + 54 error)
│   └── SHA256SUMS         checksum pin for the vector file
├── scripts/
│   ├── lombok-doctor.sh   v3.6 ecosystem standards checks
│   └── bump_version.sh    staged version bump across manifests + docs
├── composer.json          PHP manifest (root only; no "version" field)
├── CHANGELOG.md           Keep-a-Changelog
├── LICENSE                Apache-2.0
└── README.md              English with the bilingual "Mengapa library ini?" section
```

## Aturan penataan

- Bahasa folder berada di root (`rust/`, `typescript/`, `python/`, `go/`,
  `php/`) — pola terkunci ecosystem (S6).
- Satu manifest per port: `rust/Cargo.toml`, `typescript/package.json`,
  `python/pyproject.toml`, `go/go.mod`, dan `composer.json` di root (tanpa
  field `version`; Packagist mengambil versi dari tag).
- `vectors/` adalah satu-satunya sumber kontrak; runner di tiap port
  membaca file yang sama dan SHA256SUMS menguncinya.
- Dokumen internal (masterplan_, architecture_) hidup lokal di `docs/` dan
  tidak dilacak git (ADR-024, dikelola .gitignore).
