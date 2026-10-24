#!/bin/sh
# PARAMS v13: attack 9c with the 4-CPU plan of pin_cpus.py, flags off then on. Needs Docker Desktop running; images built from the current code.
cd "$(dirname "$0")/.." || exit 1
OUT=eval/output/final_run
rm -f "$OUT/ATTACK9C_NCPU4_DONE"
ATTACK_PIN_NCPU=4 LOOP_OFFLOAD=0 BLUE_INLINE=0 python attack_suite.py --only 9c --output "$OUT/attack9c_ncpu4_flags_off.json" > "$OUT/attack9c_ncpu4_flags_off.txt" 2>&1
ATTACK_PIN_NCPU=4 LOOP_OFFLOAD=1 BLUE_INLINE=1 python attack_suite.py --only 9c --output "$OUT/attack9c_ncpu4_flags_on.json" > "$OUT/attack9c_ncpu4_flags_on.txt" 2>&1
echo done > "$OUT/ATTACK9C_NCPU4_DONE"
