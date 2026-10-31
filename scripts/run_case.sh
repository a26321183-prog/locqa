#!/usr/bin/env bash
# Reproduces every submission artefact from the organisers' data.
# Usage: scripts/run_case.sh /path/to/handout   (folder with intl_ru/kk/uz/en.arb; data is NOT part of the repo)
set -euo pipefail
DATA="${1:?path to folder with intl_*.arb}"
OUT="${2:-submission}"
cd "$(dirname "$0")/.."
mkdir -p "$OUT"
REFS=(--ref "uz=$DATA/intl_uz.arb" --ref "en=$DATA/intl_en.arb" --ref "kk=$DATA/intl_kk.arb")

# Kazakh: report + fixed file (required deliverables)
python3 -m locqa check --source "$DATA/intl_ru.arb" --target "$DATA/intl_kk.arb" --glossary glossary/glossary.csv \
  "${REFS[@]}" --out "$OUT/report.json"
python3 -m locqa fix --source "$DATA/intl_ru.arb" --target "$DATA/intl_kk.arb" --glossary glossary/glossary.csv \
  "${REFS[@]}" --curated fixes/kk_curated_fixes.csv --out-dir "$OUT"
python3 -m locqa validate --source "$DATA/intl_ru.arb" --fixed "$OUT/intl_kk_fixed.arb" || true

# Uzbek (bonus): same analysis with Uzbek rules
python3 -m locqa check --source "$DATA/intl_ru.arb" --target "$DATA/intl_uz.arb" --lang uz --glossary glossary/glossary.csv \
  "${REFS[@]}" --out "$OUT/report_uz.json"
python3 -m locqa fix --source "$DATA/intl_ru.arb" --target "$DATA/intl_uz.arb" --lang uz --glossary glossary/glossary.csv \
  "${REFS[@]}" --out-dir "$OUT"
python3 -m locqa validate --source "$DATA/intl_ru.arb" --fixed "$OUT/intl_uz_fixed.arb" || true
cp glossary/glossary.csv "$OUT/glossary.csv"
