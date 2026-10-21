"""Feedback meter evaluation: leakage (A vs B) and utility (planted bypass). See PARAMS.md; values are fixed there.

    python -m eval.meter_eval            # ~10 min, CPU only, mock/simulated: production meter + Store code
    python -m eval.meter_eval --smoke    # tiny sizes, only to check that the harness runs (not for results)

Label: simulated (production meter code). No real model, no timing channel.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import tempfile
import time

from meter import Params, STATES, transition
from stats import wilson
from storage import Store

KEY = hashlib.sha256(b"meter-eval-fixed-gateway-key").digest()
FAMILIES = [f"F{i}" for i in range(1, 13)]
BLOCK = {0: set(FAMILIES[:6]), 1: set(FAMILIES[6:])}  # secret A blocks F1-F6, secret B blocks F7-F12
CODE = {state: i for i, state in enumerate(STATES)}
LEAK_SEED, UTILITY_SEED = 20261021, 20261022
ARMS = ("none", "exact", "meter q=0", "meter q=0.15", "meter repeated reads")
LABEL = "simulated (production meter code)"


def meter_params(arm):
    return Params(noise_q=0.15 if arm == "meter q=0.15" else 0.0)


def leak_plan():
    """Red's fixed probe plan: four batches of ten (PARAMS.md, evaluation 1)."""
    return [[FAMILIES[i % 6] for i in range(10)], [FAMILIES[6 + i % 6] for i in range(10)],
            [FAMILIES[i % 6] if i < 5 else FAMILIES[6 + i % 6] for i in range(10)], ["N"] * 10]


def leak_run(arm, secret, index, store):
    owner, run_id, params = f"id-{arm}-{index}", f"leak-{arm}-{index}", meter_params(arm)
    bits, reads = [], []
    for batch, families in enumerate(leak_plan()):
        for i, family in enumerate(families):
            passed = family == "N" or family not in BLOCK[secret]
            if arm.startswith("meter"):  # none/exact need no gateway state
                store.end(store.begin(run_id, owner, f"{run_id}-{batch}-{i}-{family}", "v1"), passed)
            bits.append(int(passed))
        if arm.startswith("meter"):
            store.meter_update(run_id, owner, params, KEY)
            for _ in range(3 if arm == "meter repeated reads" else 1):
                reads.append(CODE[store.meter_read(owner, run_id, params)])
    return bits if arm == "exact" else reads if reads else [0]


def leak_arm(arm, n_train, n_test, directory):
    from sklearn.tree import DecisionTreeClassifier
    store = Store(Path(directory) / arm.replace(" ", "_").replace("=", ""), KEY)
    rows = []
    for split, size in (("train", n_train), ("test", n_test)):
        for k in range(size):
            secret = k % 2  # balanced between A and B
            rows.append((split, secret, leak_run(arm, secret, f"{split}{k}", store)))
    train, test = [[r for r in rows if r[0] == s] for s in ("train", "test")]
    tree = DecisionTreeClassifier(max_depth=3, random_state=LEAK_SEED).fit([r[2] for r in train], [r[1] for r in train])
    correct = sum(int(p == r[1]) for p, r in zip(tree.predict([r[2] for r in test]), test))
    low, high = wilson(correct, len(test))
    return dict(arm=arm, test_runs=len(test), accuracy=correct / len(test), wilson_95=[low, high],
                train_accuracy=float(tree.score([r[2] for r in train], [r[1] for r in train])))


class Red:
    """Scripted adaptive Red (PARAMS.md, evaluation 2). Knows the published design (B, thresholds, budgets)."""
    LIMIT = 150

    def __init__(self, arm, store, planted, trial):
        self.arm, self.store, self.planted, self.trial = arm, store, planted, trial
        self.params, self.owner = meter_params(arm), f"red-{trial}"
        self.queries = self.reads = self.run_reads = 0
        self.run_no, self.chain, self.batch_no = 0, None, 0

    def passes(self, family):
        return family == self.planted  # Blue blocks everything (K included) except the planted family

    def new_run(self):
        self.run_no += 1
        self.run_reads = 0
        self.run_id = f"util-{self.trial}-{self.run_no}"
        self.batch_no = 0
        self.send(["K"] * 10)  # calibration batch (score 0, never read)
        self.chain = ("STABLE", 0.0)

    def send(self, families):
        self.batch_no += 1
        for i, family in enumerate(families):
            self.store.end(self.store.begin(self.run_id, self.owner, f"{self.run_id}-{self.batch_no}-{i}-{family}", "v1"),
                           self.passes(family))
        self.queries += len(families)
        self.store.meter_update(self.run_id, self.owner, self.params, KEY)

    def test(self, families):
        """Returns True (hit), False (miss) or None (no answer: budget/limit, or a state that fits neither hypothesis)."""
        batch = [f for f in families for _ in range(3)] + ["K"] * (10 - 3 * len(families))
        for _ in range(3):  # at most two re-tests with new probe text when a state fits no hypothesis
            if self.chain is None or self.run_reads >= self.params.reads_per_run:
                if self.queries + 20 > self.LIMIT or self.reads >= self.params.reads_total:
                    return None
                self.new_run()
            if self.queries + 10 > self.LIMIT or self.reads >= self.params.reads_total:
                return None
            self.send(batch)
            seen = self.store.meter_read(self.owner, self.run_id, self.params)
            self.reads += 1
            self.run_reads += 1
            fits = {name: transition(*self.chain, score, self.params) for name, score in (("hit", 0.3), ("miss", 0.0))}
            matching = [name for name, (state, _) in fits.items() if state == seen]
            if len(matching) == 1:
                self.chain = fits[matching[0]]
                return matching[0] == "hit"
            self.chain = None  # out of sync with the meter: start a new run next time
        return None

    def find(self):
        groups = [FAMILIES[i:i + 3] for i in range(0, 12, 3)]
        hit_group = None
        for index, group in enumerate(groups):
            if index == 3 and hit_group is None:
                hit_group = group  # three misses: the planted family must be in the last group
                break
            outcome = self.test(group)
            if outcome is None:
                return random.Random(self.trial).choice(FAMILIES)
            if outcome:
                hit_group = group
                break
        if hit_group is None:
            return random.Random(self.trial).choice(FAMILIES)
        for index, family in enumerate(hit_group):
            if index == 2:
                return family  # the other two missed
            outcome = self.test([family])
            if outcome is None:
                return random.Random(self.trial).choice(hit_group)
            if outcome:
                return family
        return hit_group[0]


def utility_arm(arm, trials, directory):
    store = Store(Path(directory) / ("u_" + arm.replace(" ", "_").replace("=", "")), KEY)
    rng = random.Random(UTILITY_SEED)
    wins, queries, reads = 0, [], []
    for trial in range(trials):
        planted = rng.choice(FAMILIES)
        if arm == "none":
            guess, used, read_count = random.Random(UTILITY_SEED + trial).choice(FAMILIES), 0, 0
        elif arm == "exact":
            used = 0
            for family in FAMILIES:
                used += 1
                if family == planted:
                    break
            guess, read_count = planted, 0
        else:
            red = Red(arm, store, planted, ("q0-" if arm == "meter q=0" else "q15-") + str(trial))
            guess, used, read_count = red.find(), red.queries, red.reads
        if guess == planted:
            wins += 1
            queries.append(used)
            reads.append(read_count)
    low, high = wilson(wins, trials)
    return dict(arm=arm, trials=trials, success_rate=wins / trials, wilson_95=[low, high], query_limit=Red.LIMIT,
                median_queries=statistics.median(queries) if queries else None,
                mean_queries=round(statistics.mean(queries), 1) if queries else None,
                median_reads=statistics.median(reads) if reads else None)


def table(results):
    lines = ["# Feedback meter: leakage vs utility", "", f"Label: {LABEL}. Parameters fixed in PARAMS.md (v1) before this run. "
             "50% leak accuracy = this attacker could not tell A from B; it is not proof of no leak.", "",
             "| Arm | Red's A-vs-B accuracy (unseen runs, 95% Wilson) | Finds planted bypass within 150 probes | Median / mean probes (successes) | Median reads |",
             "|---|---:|---:|---:|---:|"]
    leak = {r["arm"]: r for r in results["leak"]}
    use = {r["arm"]: r for r in results["utility"]}
    for arm in ARMS:
        a, u = leak.get(arm), use.get(arm)
        acc = f"{a['accuracy']:.1%} ({a['wilson_95'][0]:.1%}-{a['wilson_95'][1]:.1%}), n={a['test_runs']}" if a else "NOT RUN"
        win = f"{u['success_rate']:.1%} ({u['wilson_95'][0]:.1%}-{u['wilson_95'][1]:.1%}), n={u['trials']}" if u else "NOT RUN"
        qs = f"{u['median_queries']} / {u['mean_queries']}" if u and u["median_queries"] is not None else "n/a"
        lines.append(f"| {arm} | {acc} | {win} | {qs} | {u['median_reads'] if u else 'NOT RUN'} |")
    return "\n".join(lines) + "\n"


def chart(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    leak = {r["arm"]: r for r in results["leak"]}
    use = {r["arm"]: r for r in results["utility"]}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=False)
    for ax, data, key, title in ((axes[0], leak, "accuracy", "Leak: Red's accuracy at telling Blue's rule A from B"),
                                 (axes[1], use, "success_rate", "Utility: Red finds the planted bypass within 150 probes")):
        names = [a for a in ARMS if a in data]
        values = [100 * data[a][key] for a in names]
        errors = [[max(0.0, 100 * (data[a][key] - data[a]["wilson_95"][0])) for a in names],
                  [max(0.0, 100 * (data[a]["wilson_95"][1] - data[a][key])) for a in names]]
        ax.bar(range(len(names)), values, yerr=errors, color="#4f7cac", capsize=4)
        ax.set_xticks(range(len(names)), names, rotation=20, ha="right", fontsize=8)
        ax.set_ylim(0, 105)
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("%")
    axes[0].axhline(50, color="#aa4444", linestyle="--", linewidth=1)
    axes[0].text(0.02, 52, "50% = guessing", color="#aa4444", fontsize=8)
    fig.suptitle(f"{LABEL}; parameters fixed in PARAMS.md v1", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("eval/output/meter"))
    args = parser.parse_args()
    n_train, n_test, trials = (20, 20, 12) if args.smoke else (300, 300, 300)
    started = time.time()
    results = dict(label=LABEL, params_version=1, smoke=args.smoke, leak_seed=LEAK_SEED, utility_seed=UTILITY_SEED, leak=[], utility=[])
    with tempfile.TemporaryDirectory(prefix="meter-eval-") as directory:
        for arm in ARMS:
            results["leak"].append(leak_arm(arm, n_train, n_test, directory))
            print("leak", results["leak"][-1], flush=True)
        for arm in ("none", "exact", "meter q=0", "meter q=0.15"):
            results["utility"].append(utility_arm(arm, trials, directory))
            print("utility", results["utility"][-1], flush=True)
    results["minutes"] = round((time.time() - started) / 60, 1)
    args.output.mkdir(parents=True, exist_ok=True)
    suffix = "-smoke" if args.smoke else ""
    (args.output / f"results{suffix}.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (args.output / f"results_table{suffix}.md").write_text(table(results), encoding="utf-8")
    chart(results, args.output / f"leak_vs_utility{suffix}.png")
    print(table(results))


if __name__ == "__main__":
    main()
