# development_ide LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Lingkungan pengembangan: toolchain, perintah harian, alur kerja |

## Toolchain per port

| Port | Alat | Catatan |
|---|---|---|
| Rust | stable toolchain + `clippy`, `rustfmt`, `llvm-tools-preview` | coverage via `cargo-llvm-cov` |
| TypeScript | Node >= 18 (CI: 20/22/24) + npm | dev deps: vitest, @vitest/coverage-v8, typescript |
| Python | CPython 3.9-3.13 + pip | dev: pytest, coverage, build |
| Go | 1.22 atau 1.24 | gofmt + go vet wajib bersih |
| PHP | >= 8.1 (CI: 8.1/8.3) + pcov | tanpa composer install untuk menjalankan test |

## Perintah harian

```bash
# Rust (referensi)
cd rust && cargo test --release
cargo clippy --all-targets -- -D warnings
cargo fmt --check
cargo llvm-cov --summary-only          # cakupan

# TypeScript
cd typescript && npm ci
npm test && npm run coverage && npm run build

# Python
cd python
python -m coverage run --branch --source=lombokserde -m pytest -q
python -m coverage report -m --fail-under=95

# Go
cd go && gofmt -l . && go vet ./... && go test ./...

# PHP (bootstrap sendiri, tanpa vendor/)
cd php && php tests/run.php --coverage=90   # pcov bila tersedia

# Kontrak
python3 vectors/build_vectors.py            # regenerasi deterministik
sha256sum -c vectors/SHA256SUMS
bash scripts/lombok-doctor.sh LombokSerde   # standar ecosystem
```

## Alur kerja perubahan kontrak (SPEC-first)

1. Ubah `docs/SPEC_LombokSerde_v<versi>.md` — jelaskan aturan baru.
2. Ubah `vectors/build_vectors.py` sehingga generator memproduksi kasus baru;
   regenerasi `vectors/lombokserde-vectors-v1.json` + `SHA256SUMS`.
3. Porting ke kelima implementasi + runner dalam satu changeset; semua port
   harus hijau bersama — port yang tertinggal adalah bug.
4. Jalankan doctor dan semua suite sebelum commit.

## Alur kerja perubahan biasa (non-kontrak)

1. Tulis unit test di port yang bersangkutan; bila perilaku terlihat lintas
   port, tambahkan kasus ke generator vector, bukan hanya ke satu port.
2. `cargo fmt` / `gofmt -w` / `npm run lint` sesuai port sebelum commit.
3. CI menjalankan semua port + standards job; commit yang membuat port mana
   pun merah tidak boleh di-push ke `main`.

## IDE

- Rust: rust-analyzer; aktifkan clippy on save
  (`rust-analyzer.check.command = "clippy"`).
- TypeScript: tsserver bawaan; `npm run lint` adalah `tsc --noEmit`.
- Python: konfigurasi minimal; test via pytest.
- Go: gopls; gofmt otomatis on save.
- PHP: intelephense; autoload PSR-4 dari `composer.json` root
  (`CodingLombok\LombokSerde` -> `php/src/`).
