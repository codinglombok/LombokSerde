# changelog LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Catatan rilis (cermin `CHANGELOG.md` di root) |

## [0.1.0] - 2026-10-28

Rilis pertama LombokSerde: pustaka serialisasi JSON / TOML / MessagePack
tanpa dependensi dengan hasil byte-identik di lima port bahasa.

### Added

- Model nilai kanonik bersama semua port: `null`, `bool`, `int` (i64),
  `uint` (u64), `float` (binary64), `str`, `bytes`, `array`, `table`
  (tertortir bytewise, duplikat fail-closed), dan `datetime` TOML
  (offset / localdt / date / time, raw terjaga).
- Codec JSON (RFC 8259): parser ketat dengan diagnostik `SERDE_JSON_*`
  (syntax, UTF-8, depth, trailing, int-range, float-naninf, bytes,
  datetime), encoder kanonik kompak dengan kunci tertortir bytewise dan
  float shortest-roundtrip (integral satu digit fraksional; bentuk
  eksponensial pada `>= 1e+21` / `<= 1e-7`).
- Codec TOML v1.0: parser lengkap (kunci bare/quoted/dotted, tabel,
  array-of-tables, inline table, string dasar/literal/multiline, integer
  hex/oct/bin dengan underscore, datetime) dan serializer kanonik
  (scalar, lalu `[tabel]`, lalu `[[array-of-tables]]`).
- Codec MessagePack: family panjang-minimal, float64-only, NaN kanonik,
  dukungan `timestamp` ext (-1) pada carrier 32/64/96, penolakan fail-closed
  untuk tipe ext lain.
- Penegakan kontrak bersama: 176 vector deterministik
  (`vectors/lombokserde-vectors-v1.json`, 122 success + 54 error) dengan
  `vectors/SHA256SUMS`, dihasilkan `vectors/build_vectors.py`; semua port
  menjalankan set penuh secara bit-identik di CI.
- Lima port: Rust (crate `lombokserde`, implementasi acuan), TypeScript
  (npm `lombokserde`, dual ESM + CJS), Python (PyPI `lombokserde`, PEP 621),
  Go (module `github.com/codinglombok/lombokserde/go`), dan PHP
  (Packagist `codinglombok/lombokserde`, PSR-4, PHP >= 8.1).
- Format error `[SERDE_<FMT>_<REASON>] message (at byte N)` dengan offset
  byte identik lintas port.
- Tooling dan CI: `scripts/lombok-doctor.sh` (pemeriksaan standar v3.6),
  `scripts/bump_version.sh` (bump bertahap), `vectors/build_vectors.py`
  (generator deterministik), GitHub Actions `ci.yml` (job matrix per port,
  gerbang cakupan, diff regenerasi vector, doctor) dan workflow rilis
  bertahap (`release.yml`, `release-npm.yml`, `release-crates.yml`,
  `release-pypi.yml`, `dry_run` default `true`).
- Paket dokumentasi v3 di `docs/` (10 dokumen publik, nama file
  diverifikasi) plus `README.md` dan changelog ini.

[0.1.0]: https://github.com/codinglombok/LombokSerde/releases/tag/v0.1.0
