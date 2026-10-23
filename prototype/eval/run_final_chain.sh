#!/bin/sh
# PARAMS v10 final chain (mock model, sequential, laptop must stay awake and idle). Writes eval/output/final_run/*.json and *.txt.
# The real-model cell is separate (needs the key): python -m eval.load_observer --cell real_final --diagnostics
cd "$(dirname "$0")/.." || exit 1
OUT=eval/output/final_run
mkdir -p "$OUT"
for cell in final_profile; do
  python -m eval.load_observer --cell "$cell" --output "$OUT" > "$OUT/$cell.txt" 2>&1
done
FLAGS='{"LOOP_OFFLOAD":"1","WINDOW_CONTINUE":"1","AUDIT_BATCH":"50","BLUE_INLINE":"1"}'
ATTACK_EXTRA_ENV="$FLAGS" python attack_suite.py --only 4 9 9b --output "$OUT/attack_final_flags.json" > "$OUT/attack_final_flags.txt" 2>&1
python attack_suite.py --only 4 9 9b --output "$OUT/attack_final_noflags.json" > "$OUT/attack_final_noflags.txt" 2>&1
for cell in bucket_hard_old final_no_offload final_no_batch final_no_inline; do
  python -m eval.load_observer --cell "$cell" --output "$OUT" > "$OUT/$cell.txt" 2>&1
done
echo done > "$OUT/ALL_DONE"
