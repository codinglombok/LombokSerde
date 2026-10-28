# how_to_dist LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Distribusi: registry target, workflow rilis, runbook bertahap |

## Registry target

| Port | Registry | Paket | Mekanisme |
|---|---|---|---|
| Rust | crates.io | `lombokserde` | `cargo publish` (token `CARGO_REGISTRY_TOKEN`) |
| TypeScript | npm | `lombokserde` | `npm publish --provenance --access public` (`NPM_TOKEN`) |
| Python | PyPI | `lombokserde` | trusted publishing (environment `pypi`, tanpa token) |
| Go | GitHub tags | `github.com/codinglombok/lombokserde/go` | tag `go/v<versi>` otomatis saat rilis |
| PHP | Packagist | `codinglombok/lombokserde` | mirror tag `v<versi>` (tanpa field `version` di composer.json) |

## Dua jalur rilis

1. **Tag-driven (jalur penuh).** Push tag `v*` menjalankan `release.yml`:
   `check-version` (tag == semua manifest + doctor) -> `crates` -> `npm` ->
   `pypi` -> `go-tag` (mendorong `go/v<versi>`, idempoten) ->
   `github-release` (bundle sumber via `git archive` + `SHA256SUMS`).
2. **Staged per registry (jalur hati-hati).** `release-npm.yml`,
   `release-crates.yml`, `release-pypi.yml` dijalankan manual
   (workflow_dispatch) dengan `dry_run` default `true`: build + test +
   `npm pack --dry-run` / `cargo publish --dry-run` / `twine check` saja.
   Publish nyata mensyaratkan `dry_run=false` DAN input `tag` yang cocok
   dengan manifest (fail-closed).

## Runbook rilis versi baru

1. `bash scripts/bump_version.sh X.Y.Z` — memindahkan semua manifest, marker
   `__version__`, dan nama file `docs/*_v<lama>.md`.
2. Tulis entri `CHANGELOG.md` teratas `[X.Y.Z]` dan baris yang cocok di
   `docs/changelog_LombokSerde_vX.Y.Z.md` (doctor memeriksa).
3. Bila kontrak berubah: ubah `docs/SPEC_LombokSerde_v<baru>.md` lebih
   dahulu, jalankan `python3 vectors/build_vectors.py`, perbarui
   `vectors/SHA256SUMS`, porting ke semua runner dalam satu changeset.
4. Verifikasi: `bash scripts/lombok-doctor.sh LombokSerde` + suite kelima
   port (lihat README bagian Development).
5. Commit di `main`, lalu `git tag -a vX.Y.Z -m "..."` dan
   `git push origin vX.Y.Z`. Pantau `release.yml` sampai hijau.
6. Untuk registry individual yang perlu diulang, gunakan workflow staged
   dengan `dry_run=true` lebih dahulu, baru `dry_run=false`.

## Persiapan sekali saja

- Secrets: `CARGO_REGISTRY_TOKEN`, `NPM_TOKEN` (environment `crates`, `npm`).
- PyPI: daftarkan trusted publisher pada proyek `lombokserde` untuk
  workflow `release.yml`/`release-pypi.yml` (environment `pypi`).
- Packagist: submit `https://github.com/codinglombok/LombokSerde` sekali;
  versi mengikuti tag.
- Versi registry bersifat imutabel — tag tidak pernah digeser; perbaikan
  selalu versi baru.

## Aturan versi Go

Modul `go/` adalah subdirektori, sehingga butuh tag `go/vX.Y.Z` di samping
`vX.Y.Z` agar `go get github.com/codinglombok/lombokserde/go@vX.Y.Z`
berfungsi. Workflow `go-tag` membuatnya otomatis dan melewati bila sudah ada.
