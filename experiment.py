"""Hide, Normalize, Prove: local simulated PoC. No model/API calls.

Install: python -m pip install matplotlib scikit-learn cryptography
Run: python experiment.py
Outputs: simulated_results.json, simulated_leakage.png, demo_audit/.
All latency release times here are simulated, without wall-clock sleeps.
"""

import base64
from contextlib import closing
import hashlib
import hmac
import json
import math
from pathlib import Path
import random
import secrets
import sqlite3
import statistics
import tempfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sklearn.tree import DecisionTreeClassifier

from experiment_real import release_time

LABEL = "simulated, local PoC"
SEED = 7391
RANGE_WIDTH = 12
MAX_BATCHES_PER_IDENTITY = 2
MAX_PROMPTS_PER_BATCH = 100
MAX_OUTPUT_TOKENS = 256


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pending_response():
    """A simulated HTTP envelope, identical for pass/fail/error/denial."""
    body = b'{"status":"pending"}'.ljust(64, b" ")
    return {"status_code": 202,
            "headers": {"Content-Type": "application/json", "Content-Length": "64"},
            "body": body.decode("ascii"), "streaming": False}


class RangeFeedback:
    """Trusted SQLite store: repeat batches reuse one random, asymmetric range.

    Principal and defense_version must come from trusted authentication/config.
    Sessions do not reset the budget. New prompt multisets spend the budget.
    This heuristic range is NOT differential privacy or a confidence interval.
    """

    def __init__(self, database, secret_key):
        self.database = str(database)
        self.secret_key = secret_key
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback (
                principal TEXT, defense TEXT, batch TEXT, payload TEXT,
                PRIMARY KEY (principal, defense, batch))""")

    def finalize(self, principal, defense_version, prompts, safe_count, test_finished):
        if not test_finished:
            return pending_response()
        if not prompts or len(prompts) > MAX_PROMPTS_PER_BATCH:
            raise ValueError("Batch must contain 1..100 prompts.")
        if not 0 <= safe_count <= len(prompts):
            raise ValueError("Invalid safe count.")
        # Ignore order but preserve duplicates; identical repeated batches cannot
        # sample fresh noise. Run/session IDs deliberately do not enter the key.
        batch = hmac.new(self.secret_key, canonical(sorted(prompts)).encode(),
                         hashlib.sha256).hexdigest()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM feedback WHERE principal=? AND defense=? AND batch=?",
                (principal, defense_version, batch)).fetchone()
            if row:
                return json.loads(row[0])
            used = connection.execute(
                "SELECT COUNT(*) FROM feedback WHERE principal=? AND defense=?",
                (principal, defense_version)).fetchone()[0]
            if used >= MAX_BATCHES_PER_IDENTITY:
                return {"status": "unavailable"}
            width = min(RANGE_WIDTH, len(prompts))
            # Uniformly choose a valid left endpoint. The true count need not be
            # centered. Near 0/100 the range still leaks coarse information.
            lowest = max(0, safe_count - width)
            highest = min(safe_count, len(prompts) - width)
            lower = lowest + secrets.randbelow(highest - lowest + 1)
            payload = {"status": "complete", "safe_range": [lower, lower + width]}
            connection.execute("INSERT INTO feedback VALUES (?, ?, ?, ?)",
                               (principal, defense_version, batch, canonical(payload)))
            return payload


class SessionCache:
    """Mock cache. Session reset PLUS principal/role/run/session namespaces."""

    def __init__(self):
        self.entries = {}

    def begin_session(self, principal, role, run_id, session_id):
        namespace = (principal, role, run_id, session_id)
        # Retire this role's old sessions without flushing concurrent other roles.
        for existing in list(self.entries):
            if existing[:2] == namespace[:2]:
                del self.entries[existing]
        self.entries[namespace] = {}
        return namespace

    def put(self, namespace, prompt, value):
        self.entries[namespace][prompt] = value

    def get(self, namespace, prompt):
        return self.entries[namespace].get(prompt)


def write_audit(events, run_id, signing_key, log_path, checkpoint_path):
    """Hash chain + signed external checkpoint with count and serialized length."""
    previous = "0" * 64
    records = []
    events = list(events) + [{"type": "complete", "events_before_complete": len(events)}]
    for sequence, event in enumerate(events, start=1):
        record = {"run_id": run_id, "sequence": sequence,
                  "previous_hash": previous, "event": event}
        record["hash"] = hashlib.sha256(canonical(record).encode()).hexdigest()
        previous = record["hash"]
        records.append(record)
    data = ("\n".join(canonical(record) for record in records) + "\n").encode()
    log_path.write_bytes(data)
    checkpoint = {"run_id": run_id, "event_count": len(records),
                  "byte_length": len(data), "character_length": len(data.decode()),
                  "head_hash": previous}
    checkpoint["signature"] = base64.b64encode(
        signing_key.sign(canonical(checkpoint).encode())).decode()
    checkpoint_path.write_text(canonical(checkpoint) + "\n", encoding="utf-8")
    return checkpoint


def verify_audit(log_path, checkpoint_path, trusted_public_key, expected_run_id):
    """Caller must independently trust public key and expected checkpoint/run."""
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        signature = base64.b64decode(checkpoint.pop("signature"), validate=True)
        trusted_public_key.verify(signature, canonical(checkpoint).encode())
        data = log_path.read_bytes()
        if checkpoint["run_id"] != expected_run_id:
            return False
        if len(data) != checkpoint["byte_length"] or len(data.decode()) != checkpoint["character_length"]:
            return False
        records = [json.loads(line) for line in data.decode().splitlines()]
        if len(records) != checkpoint["event_count"] or not records:
            return False
        previous = "0" * 64
        for sequence, record in enumerate(records, start=1):
            claimed_hash = record.pop("hash")
            if (record["run_id"] != expected_run_id or record["sequence"] != sequence
                    or record["previous_hash"] != previous):
                return False
            previous = hashlib.sha256(canonical(record).encode()).hexdigest()
            if not hmac.compare_digest(previous, claimed_hash):
                return False
        return (previous == checkpoint["head_hash"]
                and records[-1]["event"]["type"] == "complete"
                and records[-1]["event"]["events_before_complete"] == len(records) - 1)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, InvalidSignature):
        return False


def audit_demo(directory):
    directory.mkdir(exist_ok=True)
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key()
    # Public key is a local demo artifact, not an independent production witness.
    (directory / "public_key.bin").write_bytes(public_key.public_bytes_raw())
    log = directory / "events.jsonl"
    checkpoint = directory / "checkpoint.json"
    write_audit([{"type": "start"}, {"type": "request", "observation": "pending"}],
                "demo-run", key, log, checkpoint)
    results = {"intact": verify_audit(log, checkpoint, public_key, "demo-run")}
    data = log.read_bytes()
    variants = {
        "edited": data.replace(b'"pending"', b'"changed"'),
        "tail_deleted": b"\n".join(data.splitlines()[:-1]) + b"\n",
        "reordered": b"\n".join(reversed(data.splitlines())) + b"\n",
    }
    for name, changed in variants.items():
        path = directory / f"{name}.jsonl"
        path.write_bytes(changed)
        results[name] = verify_audit(path, checkpoint, public_key, "demo-run")
    results["wrong_run_replay"] = verify_audit(log, checkpoint, public_key, "different-run")
    modified = json.loads(checkpoint.read_text())
    tail = directory / "tail_deleted.jsonl"
    modified["event_count"] -= 1
    modified["byte_length"] = len(tail.read_bytes())
    modified["character_length"] = len(tail.read_text())
    altered_checkpoint = directory / "altered_checkpoint.json"
    altered_checkpoint.write_text(canonical(modified), encoding="utf-8")
    results["tail_and_count_changed"] = verify_audit(tail, altered_checkpoint, public_key, "demo-run")
    return results


def make_runs(cohort, split, seed, runs=200):
    """Synthetic secrets; NO labels are inferred from saved DeepSeek latencies."""
    rng = random.Random(seed)
    rows = []
    for index in range(runs):
        secret = index % 2
        base = {"ordinary": (0.9, 1.8), "boundary": (2.9, 3.1),
                "overflow": (9.4, 10.4)}[cohort][secret]
        run_noise = rng.gauss(0, 0.05)
        latencies = [max(0.01, base + run_noise + rng.gauss(0, 0.08)) for _ in range(6)]
        rows.append({"run_id": f"{cohort}-{split}-{index}",
                     "secret": secret, "raw_seconds": latencies})
    rng.shuffle(rows)
    return rows


def features(values):
    return [statistics.mean(values), min(values), max(values),
            sum(value == 3 for value in values) / len(values),
            sum(value == 6 for value in values) / len(values),
            sum(value > 9 for value in values) / len(values)]


def timed_observation(value, mode):
    """Simulated observable deadline; does not cancel a real model process."""
    if mode == "raw":
        return value
    if mode == "buckets":
        return release_time(value)
    if mode == "hard_timeout":
        return min(release_time(value), 9.0)
    raise ValueError("Unknown timing mode")


def timeout_response(value):
    """Generic timeout envelope has the same public shape as other outcomes."""
    return pending_response()


def accuracy_interval(correct, total):
    """Wilson 95% interval; each observation is an independent simulated run."""
    proportion = correct / total
    z = 1.96
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return [center - half, center + half]


def evaluate(cohort, train, unseen, mode):
    assert not {row["run_id"] for row in train} & {row["run_id"] for row in unseen}
    def observe(row):
        return [timed_observation(value, mode) for value in row["raw_seconds"]]
    classifier = DecisionTreeClassifier(max_depth=3, random_state=SEED)
    classifier.fit([features(observe(row)) for row in train], [row["secret"] for row in train])
    def score(rows):
        predictions = classifier.predict([features(observe(row)) for row in rows])
        correct = sum(int(prediction == row["secret"]) for prediction, row in zip(predictions, rows))
        return {"accuracy": correct / len(rows), "n_runs": len(rows),
                "wilson_95_interval": accuracy_interval(correct, len(rows))}
    train_score, unseen_score = score(train), score(unseen)
    all_times = [value for row in unseen for value in row["raw_seconds"]]
    return {"label": LABEL, "cohort": cohort, "mode": mode,
            "train": train_score, "unseen_test": unseen_score,
            "train_plus_unseen_diagnostic_only": score(train + unseen),
            "train_test_gap": train_score["accuracy"] - unseen_score["accuracy"],
            "mean_added_seconds": statistics.mean(release_time(value) - value for value in all_times) if mode == "buckets" else 0,
            "timeout_rate": sum(value > 9 for value in all_times) / len(all_times) if mode == "hard_timeout" else 0,
            "overrun_rate_past_3s": sum(value > 3 for value in all_times) / len(all_times),
            "overflow_rate_past_9s": sum(value > 9 for value in all_times) / len(all_times)}


def feedback_demo():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "feedback.sqlite"
        key = secrets.token_bytes(32)
        feedback = RangeFeedback(path, key)
        prompts = ["benign prompt"] * 100
        pending = feedback.finalize("red-1", "blue-v1", prompts, 13, False)
        final = feedback.finalize("red-1", "blue-v1", prompts, 13, True)
        # New service object represents restart/new session; storage persists.
        restarted = RangeFeedback(path, key)
        repeated = restarted.finalize("red-1", "blue-v1", prompts, 13, True)
        restarted.finalize("red-1", "blue-v1", ["second prompt"] * 100, 50, True)
        exhausted = restarted.finalize("red-1", "blue-v1", ["third prompt"] * 100, 50, True)
        return {"pending": pending, "final": final, "repeat_same_range": final == repeated,
                "third_unique_batch": exhausted,
                "extreme_count_limit": "With width 12, count 0 yields [0,12] and count 100 yields [88,100]; trivially distinguishable.",
                "guarantee": "Heuristic obfuscation only; no differential privacy guarantee."}


def cache_demo():
    cache = SessionCache()
    red = cache.begin_session("tenant", "red", "run-1", "s1")
    blue = cache.begin_session("tenant", "blue", "run-1", "s1")
    cache.put(red, "same prompt", "red cached value")
    isolated = cache.get(blue, "same prompt") is None
    reset = cache.begin_session("tenant", "red", "run-1", "s1")
    return {"mock_role_isolation": isolated, "mock_session_reset": cache.get(reset, "same prompt") is None,
            "hosted_deepseek_internal_cache_reset": "Unavailable to this client; not tested."}


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory = Path(__file__).resolve().parent
    results = []
    for index, cohort in enumerate(("ordinary", "boundary", "overflow")):
        train = make_runs(cohort, "train", SEED + index * 10)
        unseen = make_runs(cohort, "unseen", SEED + index * 10 + 1)
        for mode in ("raw", "buckets"):
            results.append(evaluate(cohort, train, unseen, mode))
    audit = audit_demo(directory / "demo_audit")
    # Only overflow receives the additional arm. Keep original cohorts unchanged.
    timeout_arm = evaluate("overflow", make_runs("overflow", "train", SEED + 20),
                           make_runs("overflow", "unseen", SEED + 21), "hard_timeout")
    data = {"label": LABEL, "seed": SEED, "no_api_calls": True,
            "headline_metric": "Accuracy on unseen runs only; pooled accuracy is diagnostic only.",
            "timing_policy": "3/6/9s ceiling buckets; above 9s release at actual time (unbounded timing disclosure).",
            "response_policy": "Identical pending envelope; no per-prompt safety result; range only after completion.",
            "timing_experiment": results, "feedback_demo": feedback_demo(),
            "overflow_comparison": {
                "actual_time_after_9s": next(row for row in results if row["cohort"] == "overflow" and row["mode"] == "buckets"),
                "hard_timeout": timeout_arm,
                "timeout_response": timeout_response(10),
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "limitation": "Deadline and token cap are modeled only. A token cap does not bound runtime. Live model cancellation and fixed network release are not implemented. All overflow observations in this cohort time out, so timeout utility is zero.",
            },
            "cache_demo": cache_demo(), "audit_demo": audit,
            "limitations": ["Synthetic latency model and simulated HTTP envelope, not a live sandbox.",
                            "Random-range feedback is heuristic and can still reveal a defense through repeated/adaptive batches.",
                            "SQLite budget requires protected storage and trusted principal/defense identities.",
                            "Mock cache isolation is not evidence about hosted DeepSeek or a real vLLM cache.",
                            "Checkpoint and public key are local demo files, not an independent audit witness.",
                            "Audit integrity is separate from a leakage pass; no universal VALID security verdict is issued."]}
    (directory / "simulated_results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    fig, axis = plt.subplots(figsize=(9, 5))
    for offset, mode, color in ((-0.18, "raw", "#d65f45"), (0.18, "buckets", "#3578a8")):
        selected = [row for row in results if row["mode"] == mode]
        values = [row["unseen_test"]["accuracy"] for row in selected]
        bars = axis.bar([index + offset for index in range(3)], values, 0.36, label=mode, color=color)
        intervals = [row["unseen_test"]["wilson_95_interval"] for row in selected]
        axis.errorbar([index + offset for index in range(3)], values,
                      yerr=[[value - interval[0] for value, interval in zip(values, intervals)],
                            [interval[1] - value for value, interval in zip(values, intervals)]],
                      fmt="none", color="black", capsize=3)
        axis.bar_label(bars, labels=[f"{value:.0%}" for value in values], padding=5)
    axis.set_xticks(range(3), ("Ordinary", "3s boundary probes", ">9s overflow probes"))
    axis.axhline(0.5, linestyle="--", color="gray", label="Balanced chance baseline")
    axis.set_ylim(0, 1.15)
    axis.set_ylabel("Secret-guessing accuracy (unseen runs)")
    axis.set_title(f"{LABEL}\n200 train + 200 unseen runs per cohort; Wilson 95% intervals")
    axis.legend(loc="upper left", bbox_to_anchor=(0, -0.10), ncol=3)
    fig.tight_layout()
    fig.savefig(directory / "simulated_leakage.png", dpi=160)
    plt.close(fig)
    print(f"{LABEL}: no API calls. Headline = unseen-run accuracy.")
    print("Cohort    Mode      Train   Unseen   Pooled*  Padding")
    for row in results:
        print(f"{row['cohort']:9} {row['mode']:8} {row['train']['accuracy']:6.1%} "
              f"{row['unseen_test']['accuracy']:7.1%} "
              f"{row['train_plus_unseen_diagnostic_only']['accuracy']:7.1%} "
              f"{row['mean_added_seconds']:6.2f}s")
    print("*Pooled is diagnostic only, includes training data.")
    print(f"Simulated overflow: actual-time-after-9s 100%; hard_timeout "
          f"{timeout_arm['unseen_test']['accuracy']:.1%}, n={timeout_arm['unseen_test']['n_runs']}; "
          f"timeout rate={timeout_arm['timeout_rate']:.0%}.")
    print("Audit signature/chain checks:", audit)
    for name, valid in audit.items():
        print(f"AUDIT {name}: {'VALID' if valid else 'INVALID'}")
    print("Random-range replay/budget demo:", data["feedback_demo"])


if __name__ == "__main__":
    main()
