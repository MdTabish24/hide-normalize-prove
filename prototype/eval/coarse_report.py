"""Exact-count recovery from Red's report range: current `run` mode vs opt-in `coarse` mode (PARAMS v8). Simulation with production code.

    python -m eval.coarse_report          # writes eval/output/coarse_report/results.json
Attacker: knows total (16), the mode and a uniform prior over the safe count; learns P(range | count) from a training sample and guesses the most
likely count for each range of a fresh test sample (MAP). Reported: exact-recovery accuracy overall and at the extreme counts 0 and 16, and whether the
true count is always inside the range (utility). Label: simulated (Monte Carlo).
"""
import json
from collections import Counter, defaultdict
from pathlib import Path
import random

from range_feedback import generate_range

TOTAL, DRAWS, SEED = 16, 4000, 20261102
KEY = bytes(range(32))
OUTPUT = Path("eval/output/coarse_report")


def draw(mode, count, rng):
    probes = "p%d" % rng.getrandbits(64)  # a fresh probe set per run, like a fresh run id and probes
    value = generate_range(count, TOTAL, mode=mode, key=KEY, identity="red", probes=probes, version="v", randbelow=rng.randrange)
    return tuple(value["safe_range"])


def evaluate(mode):
    rng = random.Random(SEED)
    table = defaultdict(Counter)  # range -> Counter(count)
    for count in range(TOTAL + 1):
        for _ in range(DRAWS):
            table[draw(mode, count, rng)][count] += 1
    guess = {r: counts.most_common(1)[0][0] for r, counts in table.items()}  # MAP under a uniform prior (equal draws per count)
    hits, inside, per_count = 0, 0, {}
    for count in range(TOTAL + 1):
        correct = 0
        for _ in range(DRAWS):
            r = draw(mode, count, rng)
            correct += guess.get(r) == count
            inside += r[0] <= count <= r[1]
        per_count[count] = round(correct / DRAWS, 3)
        hits += correct
    total = (TOTAL + 1) * DRAWS
    return dict(mode=mode, exact_recovery_overall=round(hits / total, 3), exact_recovery_count_0=per_count[0], exact_recovery_count_16=per_count[TOTAL],
                truth_inside_range=round(inside / total, 4), distinct_ranges=len(table), per_count=per_count)


def main():
    results = [evaluate("run"), evaluate("coarse")]
    # Repeating identical probes cannot be averaged in coarse mode: same probe set -> same range.
    same = {generate_range(7, TOTAL, mode="coarse", key=KEY, identity="red", probes="same", version="v")["safe_range"].__str__() for _ in range(5)}
    out = dict(label="simulated (Monte Carlo, production generate_range)", params_version=8, total=TOTAL, draws_per_count=DRAWS, seed=SEED, results=results,
               coarse_same_probes_distinct_outputs=len(same))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "results.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for r in results:
        print({k: v for k, v in r.items() if k != "per_count"})
    print("coarse: distinct outputs for 5 repeats of the same probe set:", len(same))


if __name__ == "__main__":
    main()
