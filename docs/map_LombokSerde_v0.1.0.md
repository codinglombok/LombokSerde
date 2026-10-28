# map LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Peta dokumen: apa yang dibahas di mana |

## Dokumen publik (terlacak)

| Dokumen | Isi |
|---|---|
| [SPEC](SPEC_LombokSerde_v0.1.0.md) | Kontrak normatif lintas bahasa: model nilai, aturan kanonik, kode error, vector |
| [API](API_LombokSerde_v0.1.0.md) | Referensi API publik kelima port + konvensi lintas port |
| [Lang](Lang_LombokSerde_v0.1.0.md) | Catatan implementasi per bahasa dan bagaimana byte-identitas dipertahankan |
| [structure_repo](structure_repo_LombokSerde_v0.1.0.md) | Struktur direktori dan peran tiap bagian |
| [map](map_LombokSerde_v0.1.0.md) | Dokumen ini |
| [guide_how_to_use](guide_how_to_use_LombokSerde_v0.1.0.md) | Panduan pemakaian: decode/encode, opsi, penanganan error |
| [how_to_dist](how_to_dist_LombokSerde_v0.1.0.md) | Distribusi: registry, workflow rilis bertahap, runbook tag |
| [development_ide](development_ide_LombokSerde_v0.1.0.md) | Menyiapkan lingkungan pengembangan dan perintah harian |
| [full_summary_project](full_summary_project_LombokSerde_v0.1.0.md) | Ringkasan proyek menyeluruh: fitur, batasan, metrik |
| [changelog](changelog_LombokSerde_v0.1.0.md) | Catatan rilis versi ini (cermin CHANGELOG.md) |
| [tech_debt](tech_debt_LombokSerde_v0.1.0.md) | Utang teknis terdaftar + rencana pelunasan |

## Dokumen internal (lokal, tidak terlacak — ADR-024)

| Dokumen | Isi |
|---|---|
| `docs/masterplan_LombokSerde_v0.1.0.md` | Rencana induk, prinsip universal, tabel bukti U1-U13 |
| `docs/architecture_LombokSerde_v0.1.0.md` | Arsitektur teknis lintas port |

Dua dokumen internal di atas wajib ada secara lokal (verifikasi:
`bash scripts/lombok-doctor.sh LombokSerde --internal`) tetapi tidak
pernah di-commit.

## Artefak kontrak

| Artefak | Peran |
|---|---|
| `vectors/lombokserde-vectors-v1.json` | 176 kasus uji deterministik (122 success + 54 error) |
| `vectors/SHA256SUMS` | Kunci checksum vector file |
| `vectors/build_vectors.py` | Generator deterministik (sumber tunggal kontrak) |
| `docs/SPEC_LombokSerde_v0.1.0.md` | Spesifikasi normatif (SPEC-first protocol) |
