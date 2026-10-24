#!/bin/sh
# PARAMS v11 part (a): attack 9c in Docker, flags off then on. Needs Docker Desktop running; images already built from the current code.
cd "$(dirname "$0")/.." || exit 1
OUT=eval/output/final_run
mkdir -p "$OUT"
LOOP_OFFLOAD=0 BLUE_INLINE=0 python attack_suite.py --only 9c --output "$OUT/attack9c_flags_off.json" > "$OUT/attack9c_flags_off.txt" 2>&1
LOOP_OFFLOAD=1 BLUE_INLINE=1 python attack_suite.py --only 9c --output "$OUT/attack9c_flags_on.json" > "$OUT/attack9c_flags_on.txt" 2>&1
echo done > "$OUT/ATTACK9C_DONE"
