# guide_how_to_use LombokSerde v0.1.0

| Versi | 0.1.0 |
|---|---|
| Cakupan | Panduan pemakaian: nilai, opsi, error, pola umum |

## Membangun nilai

Setiap port menyediakan konstruktor untuk model nilai bersama. Aturan yang
paling sering tersandung:

- **Tabel tersortir dan bebas duplikat.** Gunakan konstruktor tabel yang
  melakukan sort bytewise (`makeTable` di TS, `Value::table` di PHP,
  `NewTable` di Go). Duplikat adalah error `SERDE_TABLE_DUPLICATE`, bukan
  perilaku "yang terakhir menang".
- **`uint` hanya untuk rentang atas.** Nilai integer `[2^63, 2^64-1]`
  disimpan sebagai `uint`; nilai di bawahnya adalah `int`. Di TS payloadnya
  `bigint`, di PHP string desimal kanonik, di Rust/Go tipe terpisah.
- **Pertahankan raw datetime.** Datetime TOML membawa teks sumber apa adanya
  (termasuk pemisah spasi atau `t`/`z` kecil). Jangan "menormalkan" raw
  secara manual sebelum encode ulang.

## Decode dan encode

```text
JSON       : bytes -> Value -> bytes   (teks UTF-8, kanonik, tanpa spasi)
TOML       : bytes -> Value -> bytes   (root wajib tabel)
MessagePack: bytes -> Value -> bytes   (hex di vector file; biner asli di runtime)
```

Dekode selalu memvalidasi UTF-8 lebih dahulu, lalu struktur, lalu batasan
(depth, rentang integer). Encode selalu menghasilkan byte kanonik: kunci
tertortir bytewise, float shortest-roundtrip dengan aturan pin, family
MessagePack dengan panjang minimal.

## Opsi

| Opsi | Default | Efek |
|---|---|---|
| `depth_limit` | 128 | Nesting kontainer maksimum; kontainer terluar adalah depth 1 |

Melewati batas depth menghasilkan `SERDE_<FMT>_DEPTH` — pada decode dengan
offset byte, pada encode tanpa offset. Opsi lain tidak ada pada 0.1.0
(sengaja: permukaan API kecil lebih mudah dijaga identik).

## Menangani error

Error adalah nilai biasa dengan `code` (string stabil) dan `offset` (byte
ke-berapa masalah terjadi, bila relevan). Format tampilan:

```text
[SERDE_JSON_SYNTAX] unexpected character (at byte 7)
[SERDE_MP_EXT] unsupported extension type (at byte 4)
```

Cocokkan `code` untuk branching; jangan parse pesan. Offset aman dipakai
untuk diagnostik lintas bahasa karena identik di semua port (dipin oleh
vector error cases).

## Pola umum

- **Round-trip check.** Encode -> decode -> encode harus byte-identik pada
  input kanonik; gunakan ini sebagai sanity test di proyek pemakai.
- **Checksum stabil.** Karena output kanonik, `sha256(encode(v))` cocok
  dihitung di layar berbeda — berguna untuk cache key.
- **MessagePack untuk data biner.** `bytes` hanya ada di MessagePack; JSON
  dan TOML menolaknya (`SERDE_JSON_BYTES` / `SERDE_TOML_BYTES`).
- **Timestamp.** Simpan waktu sebagai offset datetime (raw `...Z` atau
  `±HH:MM`) agar dapat memeta ke timestamp MessagePack; datetime lokal akan
  gagal dengan `SERDE_MP_DATETIME`.
