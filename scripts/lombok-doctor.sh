#!/usr/bin/env bash
# lombok doctor (v3.6) - pemeriksaan mesin untuk standar Lombok Ecosystem.
#
# Mencakup (PRINSIP_UNIVERSAL v3.6, MASTERPLAN_UTAMA v3.6 §5, RILIS_DISTRIBUSI §5):
#   docs     10 dokumen publik ada, versi nama berkas = versi manifest, SPEC normatif,
#            hash vector cocok, jumlah kasus vector >= 100, runner vector per port
#   claims   larangan klaim kepemilikan aplikasi/framework (ADR-019, U1)
#   style    0 emoji di *.md terlacak (ADR-025, GP-13)
#   ignore   .gitignore memuat 3 baris ADR-024, dokumen internal tidak terlacak (GP-13)
#   privacy  0 istilah klien (ADR-023, GP-12) - daftar dari $LOMBOK_PRIVACY_TERMS
#            atau ~/.lombok/client-terms.txt; dilewati bila daftar tidak tersedia
#   meta     LICENSE, SPDX manifest, README "Mengapa library ini", CHANGELOG terbaru = versi,
#            tanpa dependensi path/file: lokal
#
# Pemakaian: scripts/lombok-doctor.sh <RepoName> [--internal]
#   --internal  wajibkan juga dokumen internal (masterplan_, architecture_) ada secara lokal
#               dan tabel bukti U1-U13 lengkap (dijalankan pemilik, bukan CI).
# Variabel opsional: LOMBOK_VERSION (paksa versi), LOMBOK_VECTORS (path berkas vector).
set -u
REPO="${1:?usage: $0 <RepoName> [--internal]}"
INTERNAL=0
[ "${2:-}" = "--internal" ] && INTERNAL=1
PKG="$(echo "$REPO" | tr '[:upper:]' '[:lower:]')"
fail=0
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "ok:   $*"; }

# ---------------------------------------------------------------- versi manifest
json_version() { sed -n 's/^  "version": *"\([^"]*\)".*/\1/p' "$1" | head -1; }
VER="${LOMBOK_VERSION:-}"
if [ -z "$VER" ]; then
  for m in package.json typescript/package.json; do
    [ -f "$m" ] && { VER="$(json_version "$m")"; [ -n "$VER" ] && break; }
  done
fi
if [ -z "$VER" ]; then
  for m in rust/Cargo.toml Cargo.toml; do
    [ -f "$m" ] && { VER="$(grep -m1 '^version' "$m" | sed 's/.*"\(.*\)".*/\1/')"; [ -n "$VER" ] && break; }
  done
fi
if [ -z "$VER" ] && [ -f pyproject.toml ]; then
  VER="$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')"
fi
[ -z "$VER" ] && [ -f version.txt ] && VER="$(tr -d '[:space:]' < version.txt)"
[ -n "$VER" ] || { err "versi manifest tidak dapat ditentukan"; exit 1; }
echo "repo=$REPO version=$VER"

# semua manifest yang ada harus sama versinya (composer.json tanpa field version)
for m in package.json typescript/package.json python/pyproject.toml pyproject.toml rust/Cargo.toml version.txt; do
  [ -f "$m" ] || continue
  case "$m" in
    *.json) v="$(json_version "$m")" ;;
    version.txt) v="$(tr -d '[:space:]' < "$m")" ;;
    *) v="$(grep -m1 '^version' "$m" | sed 's/.*"\(.*\)".*/\1/')" ;;
  esac
  [ -z "$v" ] || [ "$v" = "$VER" ] || err "versi $m ($v) != $VER"
done
for c in composer.json php/composer.json; do
  [ -f "$c" ] && grep -q '"version"' "$c" && err "$c memuat field version (Packagist mengambil versi dari tag)"
done
# manifest PHP harus tunggal di root (Packagist hanya membaca composer.json root)
[ -f php/composer.json ] && err "php/composer.json masih ada - manifest PHP sudah pindah ke root composer.json"
# dokumen versi lain tidak boleh ikut ter-commit (relapse: salinan *_v<versi-lama>.md hidup kembali)
for f in docs/*_LombokSerde_v*.md; do
  [ -e "$f" ] || continue
  case "$f" in
    *_v${VER}.md) ;;
    *) err "dokumen versi lain ter-commit: $f (harus *_v${VER}.md)" ;;
  esac
done

# ---------------------------------------------------------------- docs
PUBLIC="changelog map structure_repo full_summary_project guide_how_to_use how_to_dist development_ide API Lang SPEC"
count=0
for d in $PUBLIC; do
  f="docs/${d}_${REPO}_v${VER}.md"
  if [ -f "$f" ]; then count=$((count+1)); else err "dokumen publik hilang: $f"; fi
done
echo "dokumen publik: $count/10"
if [ "$INTERNAL" -eq 1 ]; then
  for d in masterplan architecture; do
    f="docs/${d}_${REPO}_v${VER}.md"
    [ -f "$f" ] || err "dokumen internal hilang (lokal): $f"
  done
  MP="docs/masterplan_${REPO}_v${VER}.md"
  if [ -f "$MP" ]; then
    grep -q '^## 2\. Prinsip Universal' "$MP" || err "masterplan tanpa bagian '## 2. Prinsip Universal'"
    n="$(grep -c -E '^\| U(1[0-3]|[1-9]) \|' "$MP")"
    [ "$n" -eq 13 ] || err "tabel bukti U1-U13 berisi $n/13 baris"
  fi
fi

SPEC="docs/SPEC_${REPO}_v${VER}.md"
S="This document is the normative cross-language contract. Every language port MUST produce byte-identical output for all specified inputs. Deviations from this specification are bugs."
VEC="${LOMBOK_VECTORS:-vectors/${PKG}-vectors-v1.json}"
if [ -f "$SPEC" ]; then
  grep -qF "$S" "$SPEC" || err "SPEC tanpa kalimat normatif wajib"
  if [ -f "$VEC" ]; then
    ACTUAL="$(sha256sum "$VEC" | cut -d' ' -f1)"
    grep -q "$ACTUAL" "$SPEC" || err "SHA-256 vector di SPEC tidak cocok dengan $VEC (aktual $ACTUAL)"
    n="$(grep -o '"id": *"' "$VEC" | wc -l)"
    [ "$n" -ge 100 ] || err "berkas vector hanya $n kasus (<100, GP-11)"
    echo "vector: $n kasus"
  else
    err "berkas vector hilang: $VEC"
  fi
fi

# runner vector untuk setiap port yang punya manifest (GP-11)
has_runner() { ls $1 >/dev/null 2>&1; }
if [ -f package.json ] && [ -d src ]; then has_runner "tests/*vectors*" || err "runner vector TS (tests/*vectors*) tidak ada"; fi
if [ -f typescript/package.json ]; then has_runner "typescript/test*/*vectors*" || err "runner vector TS tidak ada"; fi
if [ -f rust/Cargo.toml ]; then has_runner "rust/tests/*vectors*" || has_runner "rust/*/tests/*vectors*" || has_runner "rust/*-vectors" || err "runner vector Rust tidak ada"; fi
if [ -f python/pyproject.toml ]; then has_runner "python/tests/*vectors*" || err "runner vector Python tidak ada"; fi
if [ -f go/go.mod ]; then has_runner "go/*vectors*_test.go" || err "runner vector Go tidak ada"; fi
if [ -d php/src ]; then has_runner "php/tests/*ectors*" || err "runner vector PHP tidak ada"; fi

# ---------------------------------------------------------------- claims (ADR-019)
APPS='RAG[A-Za-z]*|Clarion|DocFlow|PDF|AgenticAuto|Miner|DNSProxy|Proxy'
for f in README.md docs/*.md; do
  [ -f "$f" ] || continue
  case "$f" in docs/map_*) continue ;; esac
  hits="$(grep -n -i -E "(peran di rag|role in rag|purpose in rag|library *#[0-9]+|(part of|bagian dari|modul dari|komponen dari)[^.]{0,20}Lombok(${APPS})\\b|khusus (untuk )?(rag|Lombok[A-Za-z]+))" "$f" \
    | grep -v -i -E "bukan|tidak|not |never|jangan|salah|diperiksa|ditolak|dilarang" || true)"
  [ -z "$hits" ] || err "klaim kepemilikan di $f (ADR-019): $(echo "$hits" | head -1 | cut -c1-120)"
done

# ---------------------------------------------------------------- style (ADR-025)
EMOJI_RE='[\x{1F000}-\x{1FAFF}\x{2600}-\x{27BF}\x{2B05}-\x{2B55}\x{FE0F}\x{1F1E6}-\x{1F1FF}]'
emoji="$(git ls-files -z -- '*.md' 2>/dev/null | xargs -0 -r perl -CSD -ne "print \"\$ARGV:\$.\\n\" if /$EMOJI_RE/; close ARGV if eof" 2>/dev/null)"
if [ -n "$emoji" ]; then err "emoji di *.md: $(echo "$emoji" | head -5 | tr '\n' ' ')"; else ok "0 emoji di *.md"; fi

# ---------------------------------------------------------------- ignore (ADR-024)
for rule in '/map' '/docs/*architecture*.*' '/docs/*masterplan*.*'; do
  grep -qxF "$rule" .gitignore 2>/dev/null || err ".gitignore tanpa baris '$rule' (ADR-024)"
done
tracked="$(git ls-files 2>/dev/null | grep -E '^map/|^docs/[^/]*architecture[^/]*\.|^docs/[^/]*masterplan[^/]*\.' || true)"
[ -z "$tracked" ] || err "dokumen internal terlacak git: $(echo "$tracked" | tr '\n' ' ')"

# ---------------------------------------------------------------- privacy (ADR-023)
TERMS_FILE=""
if [ -n "${LOMBOK_PRIVACY_TERMS:-}" ]; then
  TERMS_FILE="$(mktemp)"; printf '%s\n' "$LOMBOK_PRIVACY_TERMS" | sed '/^[[:space:]]*$/d' > "$TERMS_FILE"
elif [ -f "$HOME/.lombok/client-terms.txt" ]; then
  TERMS_FILE="$(mktemp)"; sed '/^[[:space:]]*$/d' "$HOME/.lombok/client-terms.txt" > "$TERMS_FILE"
fi
if [ -n "$TERMS_FILE" ] && [ -s "$TERMS_FILE" ]; then
  # keluaran tidak mencetak istilahnya agar log CI tidak membocorkan daftar
  n1="$(git grep -I -i -F -c -f "$TERMS_FILE" -- . ':!*.lock' ':!package-lock.json' 2>/dev/null | wc -l)"
  n2="$(git log --format='%s%n%b' 2>/dev/null | grep -i -F -c -f "$TERMS_FILE" || true)"
  [ "$n1" -eq 0 ] || err "referensi klien ditemukan di $n1 berkas (ADR-023)"
  [ "${n2:-0}" -eq 0 ] || err "referensi klien ditemukan di $n2 baris pesan commit (ADR-023)"
  [ "$n1" -eq 0 ] && [ "${n2:-0}" -eq 0 ] && ok "privasi: 0 temuan"
  rm -f "$TERMS_FILE"
else
  echo "skip: privasi (LOMBOK_PRIVACY_TERMS / ~/.lombok/client-terms.txt tidak tersedia)"
fi

# ---------------------------------------------------------------- meta
SPDX=""
[ -f package.json ] && SPDX="$(sed -n 's/^  "license": *"\([^"]*\)".*/\1/p' package.json | head -1)"
[ -z "$SPDX" ] && [ -f rust/Cargo.toml ] && SPDX="$(grep -m1 '^license' rust/Cargo.toml | sed 's/.*"\(.*\)".*/\1/')"
case "$SPDX" in
  *"OR MIT"*) for f in LICENSE-APACHE LICENSE-MIT; do [ -f "$f" ] || err "lisensi $SPDX tetapi $f tidak ada"; done ;;
  "") err "SPDX lisensi tidak ditemukan di manifest" ;;
  *) [ -f LICENSE ] || err "LICENSE tidak ada" ;;
esac
for f in LICENSE LICENSE-APACHE LICENSE-MIT; do
  [ -f "$f" ] && [ "$(wc -c < "$f")" -lt 1000 ] && err "$f terlalu pendek (<1000 byte)"
done
grep -q -i 'Mengapa library ini' README.md 2>/dev/null || err "README tanpa bagian 'Mengapa library ini?'"
if [ -f CHANGELOG.md ]; then
  first="$(grep -m1 -E '^## \[[0-9]' CHANGELOG.md | sed 's/^## \[\([^]]*\)\].*/\1/')"
  [ "$first" = "$VER" ] || err "entri teratas CHANGELOG.md ($first) != versi $VER"
else
  err "CHANGELOG.md tidak ada"
fi
for m in package.json typescript/package.json; do
  [ -f "$m" ] && grep -q -E '"(file|link):' "$m" && err "$m memakai dependensi file:/link: lokal"
done
for m in rust/Cargo.toml $(ls rust/*/Cargo.toml 2>/dev/null); do
  [ -f "$m" ] && grep -E '^[a-z].*path *= *"\.\./\.\.' "$m" >/dev/null && err "$m memakai dependensi path ke repo lain"
done

[ $fail -eq 0 ] && echo "OK: lombok doctor lulus" || { echo "lombok doctor GAGAL"; exit 1; }
