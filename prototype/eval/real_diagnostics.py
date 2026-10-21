"""Diagnosis helpers for PARAMS.md v6: why does the fixed release time slip, and is a below-chance accuracy unusual?

Pure functions plus one collector that reads the gateway's opt-in demo trace and loop-lag files (numeric fields only, no model text).
"""
import json
from pathlib import Path
import random
import statistics

from sklearn.tree import DecisionTreeClassifier

from stats import percentile

PERMUTATION_SEED = 20261031
SLIP_MARGIN = 0.5      # a request "slipped" if its client release time exceeds W + 0.5 s
GATEWAY_SIDE = 0.25    # "gateway-side" if the gateway itself released more than 0.25 s after the scheduled time


def _lines(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def collect(lab):
    """Server-side lateness per request (actual minus scheduled release) and every recorded event-loop stall, both worlds."""
    trace, lags = [], []
    for index in (0, 1):
        data = Path(lab.worlds[index].config["DATA_DIR"])
        for row in _lines(data / "demo-trace.jsonl"):
            if isinstance(row.get("released_seconds"), (int, float)) and isinstance(row.get("scheduled_release_seconds"), (int, float)):
                trace.append(dict(world=index, lateness=row["released_seconds"] - row["scheduled_release_seconds"],
                                  compute=row.get("compute_seconds"), allowed=row.get("blue_allowed")))
        lags += [dict(row, world=index) for row in _lines(data / "loop-lag.jsonl")]
    return trace, lags


def quantiles(values):
    if not values:
        return None
    return {q: round(percentile(values, q), 3) for q in (50, 95, 99)} | {"max": round(max(values), 3), "n": len(values)}


def slips(observations, trace, lags, window):
    """observations: dicts with total and started_at (client side). Counts slipped requests by class and overlap with loop stalls."""
    slipped = [o for o in observations if o["total"] > window + SLIP_MARGIN]
    overlapping = 0
    for o in slipped:
        start, end = o["started_at"], o["started_at"] + o["total"]
        if any(start <= event["t"] and event["t"] - event["lag"] <= end for event in lags):
            overlapping += 1
    lateness = [row["lateness"] for row in trace]
    gateway_side = sum(1 for value in lateness if value > GATEWAY_SIDE)
    return dict(window_seconds=window, requests_observed=len(observations), slipped_requests=len(slipped),
                client_release=quantiles([o["total"] for o in observations]),
                server_lateness_seconds=quantiles(lateness), server_side_late_over_0_25_s=gateway_side,
                server_side_late_over_1_s=sum(1 for value in lateness if value > 1.0),
                slipped_overlapping_a_loop_lag_event=overlapping,
                loop_lag=dict(events=len(lags), max_seconds=max((e["lag"] for e in lags), default=0.0),
                              events_over_1_s=sum(1 for e in lags if e["lag"] > 1.0),
                              max_background_tasks=max((e["background"] for e in lags), default=0),
                              max_inflight=max((e["inflight"] for e in lags), default=0),
                              max_asyncio_tasks=max((e["tasks"] for e in lags), default=0)),
                reading=("no request slipped" if not slipped else
                         "slips coincide with gateway-side lateness and/or loop stalls" if (gateway_side or overlapping) else
                         "slips without gateway-side lateness or loop stalls: outside the gateway (client, network, OS)"))


def permutation_check(rows, repetitions=500, seed=PERMUTATION_SEED):
    """rows: dicts with split, secret, features. Null distribution of test accuracy under shuffled labels, and the swapped-split accuracy."""
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]

    def accuracy(fit, score, fit_labels, score_labels):
        tree = DecisionTreeClassifier(max_depth=3, random_state=seed).fit([r["features"] for r in fit], fit_labels)
        predictions = tree.predict([r["features"] for r in score])
        return sum(int(p == y) for p, y in zip(predictions, score_labels)) / len(score)
    observed = accuracy(train, test, [r["secret"] for r in train], [r["secret"] for r in test])
    swapped = accuracy(test, train, [r["secret"] for r in test], [r["secret"] for r in train])
    rng, null = random.Random(seed), []
    for _ in range(repetitions):
        a = [r["secret"] for r in train]
        b = [r["secret"] for r in test]
        rng.shuffle(a)
        rng.shuffle(b)
        null.append(accuracy(train, test, a, b))
    extreme = sum(1 for value in null if abs(value - 0.5) >= abs(observed - 0.5) - 1e-12)
    return dict(repetitions=repetitions, observed_test_accuracy=round(observed, 3), swapped_split_accuracy=round(swapped, 3),
                null_mean=round(statistics.mean(null), 3), null_sd=round(statistics.pstdev(null), 3),
                two_sided_p=round((extreme + 1) / (repetitions + 1), 3))
