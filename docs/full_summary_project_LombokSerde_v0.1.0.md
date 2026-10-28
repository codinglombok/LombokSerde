# full_summary_project LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Ringkasan proyek menyeluruh: apa, mengapa, seberapa jauh |

## 1. Ringkasan

LombokSerde adalah pustaka serialisasi/deserialisasi JSON (RFC 8259), TOML
(v1.0), dan MessagePack dengan satu kontrak normatif dan lima port bahasa
(Rust, TypeScript, Python, Go, PHP). Janji utamanya: nilai yang sama
menghasilkan byte yang sama di semua bahasa, dan setiap kegagalan
menghasilkan kode error yang sama dengan offset byte yang sama. Rust adalah
implementasi acuan; keempat port lain adalah port persis dari kontrak dan
divalidasi oleh 176 vector bersama yang dijalankan bit-identik di CI.

## 2. Fitur utama

- **JSON** — parser ketat (UTF-8, surrogate pair, batas integer i64/u64,
  depth limit) dan encoder kanonik (kunci tertortir bytewise, tanpa spasi,
  float shortest-roundtrip).
- **TOML** — parser v1.0 lengkap (tabel, array-of-tables, inline table,
  dotted key, string dasar/literal/multiline, integer hex/oct/bin,
  datetime empat jenis) dan serializer kanonik (scalar -> tabel ->
  array-of-tables, array inline satu baris).
- **MessagePack** — encoder/decoder semua tipe inti dengan family
  panjang-minimal, float64 + NaN kanonik, timestamp ext (-1) pada carrier
  32/64/96, penolakan fail-closed untuk ext lain.
- **Error fail-closed** — 24 kode stabil `SERDE_*` dengan offset byte yang
  identik lintas port.
- **Zero dependencies** — tidak ada dependensi runtime di kelima port;
  PHP bahkan tidak butuh ekstensi (aritmetika u64 murni string).

## 3. Metrik 0.1.0

| Metrik | Nilai |
|---|---|
| Kasus vector bersama | 176 (122 success + 54 error), SHA256SUMS terkunci |
| Uji per port | Rust 11, TypeScript 271, Python 16 (unit+fuzz+vectors), Go 188, PHP 194 assertion (18 unit + 176 vector) |
| Cakupan TS | 96,44% stmt / 96,16% branch (gate 95/90) |
| Cakupan Python | 96% (branch, gate 95) |
| Cakupan Go | 95,5% statement (gate 95) |
| Cakupan Rust | 93,8% line (gate 90 — lihat tech debt) |
| Cakupan PHP | pcov line gate 90 |
| Dependensi runtime | 0 di semua port |

## 4. Batasan yang diketahui

- `datetime` tidak memiliki representasi JSON; encode datetime ke JSON
  selalu error (`SERDE_JSON_DATETIME`).
- `bytes` hanya bermakna di MessagePack; JSON/TOML menolaknya.
- Hanya datetime offset yang memeta ke timestamp MessagePack; datetime
  lokal gagal dengan `SERDE_MP_DATETIME`.
- TOML tidak menerima `null`; JSON tidak menerima trailing data; duplikat
  kunci selalu error di semua format (tidak ada "last one wins").
- TOML array harus satu tipe (aturan v1.0); tidak ada dukungan array
  heterogen.
- Belum ada opsi pemformatan (pretty-print, `preserve_key_order`, dsb.)
  — output selalu kanonik pada 0.1.0.

## 5. Arah setelah 0.1.0

Versi berikutnya mengikuti tangga semver bertahap (`v0.2.0`, ...). Kandidat
yang sudah teridentifikasi: opsi pretty-print JSON dengan aturan kanonik
yang dipin, dukungan ext MessagePack terdaftar (bila kontrak menetapkan),
dan penarikan cakupan Rust/PHP ke gate 95 (lihat
[tech_debt](tech_debt_LombokSerde_v0.1.0.md)). Perubahan kontrak selalu
lewat SPEC-first protocol: SPEC -> generator vector -> semua runner.
