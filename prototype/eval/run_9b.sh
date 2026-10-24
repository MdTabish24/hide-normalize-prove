#!/bin/sh
# PARAMS v12: attack 9b three times with the final flags and once without. Sequential; nothing else should run.
cd "$(dirname "$0")/.." || exit 1
OUT=eval/output/final_run
mkdir -p "$OUT"
rm -f "$OUT/ATTACK9B_DONE"
FLAGS='{"LOOP_OFFLOAD":"1","WINDOW_CONTINUE":"1","AUDIT_BATCH":"50","BLUE_INLINE":"1"}'
for r in 1 2 3; do
  ATTACK_EXTRA_ENV="$FLAGS" python attack_suite.py --only 9b --output "$OUT/attack9b_flags_r$r.json" > "$OUT/attack9b_flags_r$r.txt" 2>&1
done
python attack_suite.py --only 9b --output "$OUT/attack9b_noflags.json" > "$OUT/attack9b_noflags.txt" 2>&1
echo done > "$OUT/ATTACK9B_DONE"
