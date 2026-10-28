# Lang LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Catatan implementasi per bahasa (perbedaan platform yang sudah dipin) |

Setiap port mengikuti `docs/SPEC_LombokSerde_v0.1.0.md`. Dokumen ini mencatat
keputusan implementasi yang muncul karena perbedaan platform, dan bagaimana
setiap port tetap menghasilkan byte yang identik.

## Rust (referensi)

- Implementasi acuan; perubahan kontrak mendarat di sini lebih dahulu.
- `f64` dirender dengan `strconv.FormatFloat(.., 'e', -1, 64)` untuk digit
  shortest-roundtrip, lalu dirender ulang dengan aturan pin SPEC.
- Integer: `i64`/`u64` native; `u64 > i64::MAX` menjadi `Value::UInt`.
- `std::str::FromStr` untuk float tidak pernah gagal pada literal tervalidasi
  grammar; overflow menghasilkan `±Inf` (diterima saat decode).

## TypeScript

- `int`/`uint` memakai `bigint`, sehingga seluruh rentang i64/u64 aman.
- Digit float: `Number.prototype.toString` (V8) shortest-roundtrip, lalu
  dirender ulang dengan aturan pin; NaN dikanonkan ke quiet NaN saat encode
  MessagePack.
- Decode menerima `string` maupun `Uint8Array`; validasi UTF-8 memakai
  `TextDecoder` dengan `fatal: true` pada jalur byte.
- Build ganda: `dist/esm` (import) dan `dist/cjs` (require), dengan marker
  `{"type":"commonjs"}` pada `dist/cjs/package.json`.

## Python

- `int` Python arbitrer; klasifikasi tepat `("int", ..)` vs `("uint", ..)`
  dilakukan pada batas `2^63` saat decode, dan rentang i64/u64 divalidasi
  secara eksplisit agar `SERDE_JSON_INT_RANGE` identik.
- Digit float memakai `repr(float)` (shortest-roundtrip CPython), dirender
  ulang dengan aturan pin.
- Kode hanya stdlib; `pyproject.toml` (PEP 621) tanpa dependensi runtime.

## Go

- `int64`/`uint64` native; `Value` memisahkan `Int` dan `Uint` seperti Rust.
- Digit float memakai `strconv.FormatFloat(.., 'e', -1, 64)` — algoritme
  Ryu yang sama dengan Rust, sehingga digitnya identik.
- `math.Float64bits` dipakai untuk carrier MessagePack; NaN dikanonkan ke
  `0x7FF8000000000000` sebelum diserialisasi.
- Modul berada di subdirektori `go/` dan ditag `go/v<versi>` pada rilis.

## PHP

- `int` PHP bertanda 64-bit; nilai `uint >= 2^63` disimpan sebagai string
  desimal kanonik (`Value::$uintStr`) dengan aritmetika string murni
  (`U64`), tanpa ekstensi tambahan.
- Digit float memakai `json_encode` (serialize_precision=-1, benar-benar
  shortest-roundtrip), dirender ulang dengan aturan pin.
- Dua complement i64 pada carrier 96-bit ditangani `U64::i64ToBytes8`
  (termasuk `PHP_INT_MIN` tanpa negasi int).
- `SerdeError::code()` berupa metode karena `\Exception` sudah memesan
  properti `$code`. Namespace PSR-4 `CodingLombok\LombokSerde`.

## Kesamaan yang diuji, bukan dianggap

Perbedaan platform di atas dipin oleh 176 vector bersama: nilai decode,
byte encode, kode error, dan offset byte dibandingkan pada setiap port di
CI. Port baru wajib menambahkan runner vector sebelum dianggap lulus
(standar ecosystem, GP-11).
