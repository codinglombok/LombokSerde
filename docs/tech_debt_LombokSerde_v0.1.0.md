# tech_debt LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Status | Terdaftar dan dijadwalkan; tidak memblokir rilis 0.1.0 |

## Utang aktif

| # | Item | Dampak | Rencana |
|---|---|---|---|
| TD-1 | Cakupan Rust 93,8% line (gate CI 90) di bawah target 95% | Cabang error tertentu (Display error, jalur UTF-8 value.rs) tidak diuji unit langsung; tetap terlindungi vector | Tambah unit baterai error/edge di `rust/tests/units.rs`, naikkan gate ke 95 di v0.1.1 |
| TD-2 | Cakupan PHP digerbang 90% (pcov line) tanpa pengukuran branch | Branch PHP tidak terukur; unit battery lebih kecil dari port lain | Baterai unit PHP yang lebih dalam + gate 95 di v0.1.1 |
| TD-3 | Vector tidak meng-pin overflow float JSON (`1e999` -> Inf) karena skema vector menjalankan decode+re-encode sekaligus (re-encode Inf ke JSON error) | Perilaku didefinisikan SPEC section 2 dan diuji unit (Rust/Go/PHP), tapi tidak di vector | Perluas skema vector (kasus decode-saja) di vector set 2 |
| TD-4 | Folder `typescript/coverage/` sempat terlacak git (output vitest) | 17 artefak build ter-commit; diff CI berisik | Dilunasi di 0.1.0: `git rm --cached` + rule `.gitignore` `typescript/coverage/` |
| TD-5 | Registry belum dipublikasikan (semua manifest 0.1.0, tag belum dibuat) | Paket belum bisa di-install dari crates.io/npm/PyPI/Packagist | Rilis bertahap: push tag `v0.1.0` setelah persetujuan pemilik (runbook `how_to_dist`) |

## Utang yang dilunasi di 0.1.0

- `python/setup.py` -> `pyproject.toml` (PEP 621).
- Manifest PHP pindah ke `composer.json` root (tanpa field `version`).
- `test-vectors/` -> `vectors/` dengan generator deterministik + SHA256SUMS
  (sebelumnya 16 kasus tanpa kasus error).
- Go: layout subpaket lama (`go/json/`, `go/msgpack/`, `go/toml/`) ->
  satu paket datar; sign rule radix TOML dan perilaku overflow float
  TOML diselaraskan ke referensi Rust.
- PHP: penulisan ulang total ke kontrak v3 (error line/col lama ->
  kode+offset byte).
- Dokumen internal yang sempat ter-commit (`docs/architecture_repo.md`,
  `docs/changelog.md` lama, `docs/masterplan_repo.md`,
  `docs/map/`) dihapus dari pelacakan dan kini dicegah .gitignore
  (ADR-024) + pemeriksaan doctor.

## Aturan

Utang baru harus terdaftar di dokumen ini dengan nomor, dampak, dan
rencana sebelum di-commit. Utang tanpa rencana tidak diizinkan. Doctor
dan CI tidak boleh dilonggarkan untuk mengakomodasi utang; gate yang
lebih rendah dari target S4 (TD-1, TD-2) wajib disertai tiket pelunasan.
