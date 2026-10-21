"""Plain-language 'why did it pass or fail' tables, built from saved files.

Numbers come from saved evidence. Reasons are fixed explanations of the mechanism and
are labelled with their basis: MEASURED (a saved number), NOTE (written in the saved
results) or DESIGN (how the code is built, not separately measured). Nothing here is run.
"""
from pathlib import Path
import re

from .data import evidence, matrix, number, read_json
from .history import text_of
from .story import timing_verdict, validity

ORDER = ("raw", "bucket", "bucket_hard", "window_hard", "window_continue")
COHORTS = ("ordinary", "boundary", "overflow", "deadline_near", "deadline_far")
CONTINUE_RUNS = ("eval/output/round2c/results.json", "eval/output/round2d/results.json")  # two repeats, same settings

# One request, step by step. 'control' is what our design does at that step.
STEPS = (
    ("1", "Red sends a prompt", "Red has only a token for its own role and can reach only the gateway.", "Separate + mediate", "isolation"),
    ("2", "Gateway checks the request", "The prompt is stored encrypted in a fixed-size record; Blue and Red cannot read each other's records.", "Separate (vault)", None),
    ("3", "Blue's private filter decides", "Blue's rule is stored encrypted and is never sent to Red. Red is not told why anything is blocked.", "Separate + normalize errors", "shapes"),
    ("4", "Model is called (only if allowed)", "Fresh salted message, no history, no tools. Blocked prompts never reach the model.", "Separate (no shared session)", None),
    ("5", "Gateway holds the reply until a fixed time", "Fast reject and slow model look the same to Red's stopwatch.", "Normalize (timing)", "timing"),
    ("6", "Red gets one generic 'pending' answer", "Same status, size and headers for blocked, allowed and error. Raw model text is withheld.", "Normalize (shape) + output scoring", "disclosure"),
    ("7", "Every event is written to a signed audit chain", "Count, size and hash only; editing one event breaks the chain.", "Measure + prove", "audit"),
)

NOT_COVERED = (
    ("CPU / memory pressure (noisy neighbour)", "Red's load could slow Blue's filter. Not measured; mock model on a shared laptop."),
    ("Hosted model KV-cache across tenants", "A fresh random prefix reduces reuse, but the provider's cache is outside our control."),
    ("Blue author learning Red's attacks (reverse direction)", "Payloads are encrypted at rest, but the measured A/B test only covers Red guessing Blue's secret."),
    ("Monitoring / dashboard as a leak", "Dashboard shows metadata only; no test tried to extract secrets from it."),
    ("Host kernel / hardware side channels, compromised gateway", "Out of scope for this prototype."),
    ("Attack suite and external agent red team", "Harness written, not run."),
)


def cell(rows, cohort, policy):
    return next((r for r in rows if r["cohort"] == cohort and r["policy"] == policy), None)


def describe(row):
    if row is None or row["status"] != "SAVED":
        return dict(value="NOT RUN", verdict="NOT RUN")
    interval = row["interval"]
    verdict = timing_verdict(row["accuracy"], row["n"], interval)["status"]
    text = f"{100 * row['accuracy']:.1f}%" + (f" ({100 * interval[0]:.1f}–{100 * interval[1]:.1f}%)" if interval else "")
    return dict(value=text, verdict=verdict, gap=row.get("gap"))


TIMING = {
    "ordinary": (
        "Blocked prompts are rejected inside the gateway before the model is called, so they come back fast; allowed ones wait for the model. "
        "Red reads that difference with a stopwatch.  [DESIGN + MEASURED]",
        dict(good="Every reply is held to a fixed bucket (0.3 / 0.6 / 0.9 s here), so fast rejects and model calls usually land in the same bucket.",
             uncertain="Buckets hide most of the difference, but the result is not clean: the interval still includes values above chance and Red did better on training runs than on unseen runs.",
             bad="Buckets did not hide the difference.")),
    "boundary": (
        "Same stopwatch leak, and here Red controls how long compute takes (worst case, test hook).  [NOTE]",
        dict(good="The bucket did not move with the filter decision.", uncertain="Partly hidden, not proven.",
             bad="Red picks a delay just under or over a bucket edge. A blocked request lands in bucket 1 and an allowed one in bucket 2, so the bucket number itself reveals the filter decision. Rounding time to buckets does not remove the dependence on time.  [NOTE]")),
    "deadline_near": (
        "Same stopwatch leak; Red picks compute times just under or over the compute deadline.  [NOTE]",
        dict(good="Replies stayed on the fixed schedule.", uncertain="Partly hidden, not proven.",
             bad="A soft bucket or a hard cap can still reveal which requests ran past the deadline.  [NOTE]")),
    "deadline_far": (
        "Same stopwatch leak; allowed compute runs far past the window.  [NOTE]",
        dict(good="Replies stayed on the fixed schedule.", uncertain="Partly hidden, not proven.",
             bad="Compute far past the window is cut off or released late, which shows in timing.  [NOTE]")),
    "overflow": (
        "Same stopwatch leak, and long compute makes the difference larger.  [NOTE]",
        dict(good="Replies stayed in the fixed schedule.", uncertain="Partly hidden, not proven.",
             bad="When compute runs past the last bucket the real finish time is released, and the slow-slot pattern also tells Red which requests were slow. A soft bucket cannot hide which request is slow.  [NOTE]")),
}
CONTINUE_WHY = ("window_continue keeps the fixed release window but does NOT cancel compute at the deadline: it continues in the background "
                "(capped at 4x the window, counted against the per-identity in-flight limit) and its result joins the sealed run record. "
                "Two repeats of the same 5 cohorts; the worse result per cohort is shown.  [MEASURED, mock model]")
WINDOW = "Designed to fix this: every reply is released at exactly one window W and anything slower than D is cancelled (a cost: added latency and some timeouts). Not measured yet, so no claim."


def variant_runs(saved):
    runs = []
    for relative in CONTINUE_RUNS:
        data = read_json(Path(saved) / relative)
        if data.get("cells"):
            runs.append(data)
    return runs


def variant_rows(saved):
    """Synthetic matrix rows for policy 'window_continue': per cohort, the WORSE of the repeat runs (higher accuracy)."""
    rows = []
    for cohort in COHORTS:
        cells = [c for run in variant_runs(saved) for c in run["cells"]
                 if c.get("cohort") == cohort and number(c.get("test_accuracy")) is not None]
        if not cells:
            continue
        c = max(cells, key=lambda x: x["test_accuracy"])
        rows.append(dict(cohort=cohort, policy="window_continue", status="SAVED", accuracy=c["test_accuracy"],
                         interval=c.get("wilson_95"), n=number(c.get("test_runs")), gap=number(c.get("train_test_gap"))))
    return rows


def channel_rows(saved):
    mx = matrix(saved)["rows"] + variant_rows(saved)
    rows = []
    for cohort in COHORTS:
        base = describe(cell(mx, cohort, "raw"))
        ours = {p: describe(cell(mx, cohort, p)) for p in ORDER[1:]}
        measured = [(p, d) for p, d in ours.items() if d["verdict"] != "NOT RUN"]
        base_why, ours_why = TIMING[cohort]
        if measured:
            worst = max(measured, key=lambda item: ("NO LEAK FOUND", "BOUNDED LEAK", "LEAKED").index(item[1]["verdict"]))
            key = {"NO LEAK FOUND": "good", "BOUNDED LEAK": "uncertain", "LEAKED": "bad"}[worst[1]["verdict"]]
            why = ours_why[key]
        else:
            why = "Nothing measured for our policies yet."
        if ours["window_hard"]["verdict"] == "NOT RUN" and ours["window_continue"]["verdict"] == "NOT RUN":
            why += "  " + (WINDOW if cohort == "ordinary" else "window_hard is also not measured here.")
        if ours["window_continue"]["verdict"] != "NOT RUN":
            why += "  " + CONTINUE_WHY
        rows.append(dict(channel=f"Timing: {cohort} traffic", baseline=base, baseline_why=base_why, ours=ours, ours_why=why))
    return rows


def other_rows(saved):
    ev = {r["test"]: r for r in evidence(saved)["rows"]}

    def get(name):
        return ev.get(name, dict(result="NOT RUN", metric="NOT RUN"))

    audit_text = ""
    try:
        audit_text = text_of(Path(saved) / "evidence/audit-docker.txt")
    except OSError:
        pass
    cases = re.findall(r"^(edit one event|delete middle event|delete last \d+ events|reorder two events|duplicate/replay event|"
                       r"rehash without signing key|edit log and stored count)\s+INVALID\s+(.+?) /", audit_text, re.M)
    iso, tamper = get("Isolation demo inside red-client"), get("Audit tamper demo")
    leak, gated = get("Real-model rule disclosure in raw outputs (keyword scan + manual review)"), get("Same outputs behind score-only gateway")
    return [
        dict(channel="Direct access (network, files, host, internet)", baseline=dict(value="NOT MEASURED", verdict="NOT RUN"),
             baseline_why="No un-isolated baseline was run. By design, containers on one network can call each other directly.  [DESIGN]",
             ours=dict(ours=dict(value=iso["metric"], verdict=iso["result"])),
             ours_why="Red sits on its own internal network and can reach only the gateway. Each probe (Blue, model, their IPs, host ports, DNS, internet, Docker socket) was refused.  [MEASURED]"),
        dict(channel="Audit tampering", baseline=dict(value="NOT MEASURED", verdict="NOT RUN"),
             baseline_why="A plain log has no signature, so an edited line cannot be detected.  [DESIGN]",
             ours=dict(ours=dict(value=tamper["metric"], verdict=tamper["result"])),
             ours_why="Each tampered copy fails a different check: " + "; ".join(f"{a} → {b}" for a, b in cases) + ".  [MEASURED]" if cases else
             "Tamper results not available.  [NOT RUN]"),
        dict(channel="Model text leaking Blue's rule", baseline=dict(value=leak["metric"], verdict=leak["result"]),
             baseline_why="A real model sometimes repeats or paraphrases the rule it was shown, so raw text reaching Red reveals Blue's defence.  [MEASURED]",
             ours=dict(ours=dict(value=gated["metric"], verdict=gated["result"])),
             ours_why="The gateway never sends model text to Red, only a score/range after the run, so there is nothing to read. Offline replay of the same 20 outputs; not a fresh API run.  [MEASURED]"),
    ]


def attack_rows(saved):
    """Attack-suite results (noisy neighbour, CPU load, feedback) as extra channels; NOT RUN when the file is absent."""
    results = read_json(Path(saved) / "attack_suite_results.json").get("results", [])
    results = [r for r in results if isinstance(r, dict)]

    def find(attack, policy=None, prefix=None, contains=None):
        for r in results:
            if str(r.get("attack")) == attack and (policy is None or r.get("policy") == policy) and                     (prefix is None or str(r.get("name", "")).startswith(prefix)) and                     (contains is None or contains in str(r.get("name", ""))):
                return dict(value=str(r.get("summary", ""))[:90], verdict=r.get("result") if r.get("result") in
                            ("BLOCKED", "BOUNDED LEAK", "LEAKED") else "NOT RUN")
        return dict(value="NOT RUN", verdict="NOT RUN")

    none = dict(value="NOT MEASURED", verdict="NOT RUN")
    per_policy = [
        ("Noisy neighbour: Red's burst slows Blue's release (attack 9)", "9",
         "Red's traffic and Blue's filter share the same CPU, so a Red burst moves Blue's reply times. Padding to a fixed time shrinks the shift but did not remove it in this local-process test. Whether Docker CPU limits and per-service CPU pinning reduce it is measured separately (attack 9c).  [MEASURED, mock model, local processes]"),
        ("CPU load slips the release time (attack 9b)", "9b",
         "When every core is busy the gateway releases replies late, which is a timing signal. Linux containers are tighter than this Windows host.  [MEASURED]"),
    ]
    rows = [dict(channel=name, baseline=none, baseline_why="No un-padded baseline was run for this attack.  [NOT MEASURED]",
                 ours={p: find(a, p) for p in ("bucket_hard", "window_hard")}, ours_why=why) for name, a, why in per_policy]
    docker_why = ("Red floods from inside its own CPU-limited container (32 workers) while Blue's reply times are measured from outside. "
                  "The median barely moves, but the slow tail grows a lot (some Blue replies take several seconds). One run, 45 samples per condition, Docker Desktop VM. "
                  "CPU pinning did not remove it, which suggests the shared single gateway worker, not CPU cores, is the bottleneck. That explanation is a hypothesis, not tested.  [MEASURED + inference]")
    for label, tag in (("no CPU pinning", "no pinning"), ("with CPU pinning (cpuset)", "CPU pinned")):
        rows.append(dict(channel=f"Noisy neighbour inside Docker, {label} (attack 9c)", baseline=none,
                         baseline_why="No un-padded baseline was run for this attack.  [NOT MEASURED]",
                         ours={p: find("9c", p, contains=tag) for p in ("bucket_hard", "window_hard")}, ours_why=docker_why))
    shared = [
        ("Extreme counts (0 or 16 safe) identifiable from the noisy range (attack 7)", "Feedback: extreme",
         "The noisy final range is deterministic at the edges: 0 always gives [0,12] and 16 always gives [4,16], so Red can tell an all-blocked or all-allowed set.  [MEASURED]"),
        ("Averaging ranges over many fresh runs (attack 7)", "Feedback: cross-run",
         "Each run's range is noisy, but averaging over many fresh runs of the same probes reduces Red's error. The per-run budget does not stop that.  [MEASURED, Monte Carlo]"),
    ]
    for name, prefix, why in shared:
        match = next((r for r in results if str(r.get("attack")) == "7" and str(r.get("name", "")).startswith(prefix)
                      and (prefix != "Feedback: cross-run" or r.get("policy") == "run")), None)
        row = dict(value=str(match.get("summary", ""))[:90], verdict=match.get("result")) if match else none
        rows.append(dict(channel=name, baseline=none, baseline_why="Not measured without the noise scheme.  [NOT MEASURED]",
                         ours=dict(ours=row), ours_why=why))
    return rows


def cost_rows(saved):
    """Does testing stay usable? Completion, cancellation and latency per policy and cohort, from the saved matrix."""
    cells = [c for c in read_json(Path(saved) / "eval/output/round2/results.json").get("cells", []) if isinstance(c, dict)]
    raw = {c.get("cohort"): number(c.get("mean_latency_seconds")) for c in cells if c.get("policy") == "raw"}
    rows = []
    for c in cells:
        rate, latency = number(c.get("timeout_rate_of_allowed")), number(c.get("mean_latency_seconds"))
        if rate is None or latency is None:
            continue
        cancelled = min(max(rate, 0), 1)
        base = raw.get(c.get("cohort"))
        rows.append(dict(policy=c.get("policy"), cohort=c.get("cohort"), completed=round(100 * (1 - cancelled), 1),
                         cancelled=round(100 * cancelled, 1), raw_value=round(100 * rate, 1), latency=round(latency, 3),
                         added=None if base is None or c.get("policy") == "raw" else round(latency - base, 3),
                         usable="NO" if cancelled > .10 else "YES"))
    for run in variant_runs(saved):
        for c in run["cells"]:
            rate, latency, late = (number(c.get("timeout_rate_of_allowed")), number(c.get("mean_latency_seconds")),
                                   number(c.get("late_rate_of_allowed")))
            if rate is None or latency is None:
                continue
            cancelled, base = min(max(rate, 0), 1), raw.get(c.get("cohort"))
            rows.append(dict(policy="window_continue", cohort=c.get("cohort"), completed=round(100 * (1 - cancelled), 1),
                             cancelled=round(100 * cancelled, 1), raw_value=round(100 * rate, 1), latency=round(latency, 3),
                             added=None if base is None else round(latency - base, 3), usable="NO" if cancelled > .10 else "YES"))
    order = {p: i for i, p in enumerate(ORDER)}
    return sorted(rows, key=lambda r: (order.get(r["policy"], 9), r["cohort"]))


def audit_load_row(saved):
    """Audit verifier on every run of each matrix; a policy fails if ANY repeat had an invalid run."""
    checks = {}
    base = read_json(Path(saved) / "eval/output/round2/results.json").get("audit_checks", {})
    for policy, c in base.items():
        if isinstance(c, dict) and c.get("runs"):
            checks.setdefault(policy, []).append((c["runs"], c.get("valid", 0)))
    for run in variant_runs(saved):
        c = run.get("audit_checks", {}).get("window_hard")
        if isinstance(c, dict) and c.get("runs"):
            checks.setdefault("window_continue", []).append((c["runs"], c.get("valid", 0)))

    def verdict(policy):
        runs = checks.get(policy)
        if not runs:
            return dict(value="NOT RUN", verdict="NOT RUN")
        text = "; ".join(f"{v}/{r} VALID" for r, v in runs)
        return dict(value=text, verdict="PASS" if all(v == r for r, v in runs) else "FAIL")
    return dict(channel="Audit chain verified on every run of the matrix", baseline=verdict("raw"),
                baseline_why="Raw-timing matrix, audit on.  [MEASURED]",
                ours={p: verdict(p) for p in ORDER[1:]},
                ours_why="The verifier checked every run's signed chain after each matrix. A policy fails if any run was not VALID in any repeat. "
                         "window_continue had 247 invalid runs (1753/2000) in one of its two repeats, with a growing undelivered audit queue, "
                         "and 2000/2000 in the other. Cause not found.  [MEASURED, cause UNVERIFIED]")


def shapes(saved):
    cells = [c for c in read_json(Path(saved) / "eval/output/round2/results.json").get("cells", []) if isinstance(c, dict)]
    counts = [c.get("distinct_response_shapes") for c in cells if number(c.get("distinct_response_shapes")) is not None]
    return dict(channel="Error / status oracle (blocked vs allowed look different)",
                baseline=dict(value="NOT MEASURED", verdict="NOT RUN"),
                baseline_why="Without normalizing, a blocked request returns an error naming the rule, which tells Red what Blue filters.  [DESIGN]",
                ours=dict(ours=dict(value=f"{max(counts)} distinct reply shape(s) across {len(counts)} saved cells" if counts else "NOT RUN",
                                    verdict="PASS" if counts and max(counts) == 1 else "FAIL" if counts else "NOT RUN")),
                ours_why="Every outcome returns the same HTTP 202 with the same body size and headers, so Red cannot tell blocked from allowed by the reply itself.  [MEASURED]")


def snapshot(saved):
    saved = Path(saved)
    timing, other = channel_rows(saved), other_rows(saved)
    timing_extra = [r for r in attack_rows(saved) if "ours" not in r["ours"]] + [audit_load_row(saved)]
    extra = attack_rows(saved)
    channels = timing + other[:2] + [shapes(saved)] + other[2:] + [audit_load_row(saved)] + extra
    mx = matrix(saved)
    ours_verdicts = [d["verdict"] for r in timing for d in r["ours"].values() if d["verdict"] != "NOT RUN"]
    worst = "NOT RUN"
    for v in ("LEAKED", "BOUNDED LEAK", "NO LEAK FOUND"):
        if v in ours_verdicts:
            worst = v
            break
    iso = other[0]["ours"]["ours"]["verdict"]
    audit = "VALID" if other[1]["ours"]["ours"]["verdict"] in ("PASS", "BLOCKED") else "NOT RUN"
    shared = [(c["channel"], c["ours"]["ours"]["verdict"]) for c in channels if "ours" in c["ours"]]
    # Headline: the policies we ship (default bucket_hard and window_hard), not the raw baseline.
    per_policy = {p["key"]: p for p in policy_table(timing + timing_extra, shared)}
    ours = [per_policy["bucket_hard"], per_policy["window_hard"], per_policy["window_continue"]]
    order = ("INVALID", "INCOMPLETE", "VALID")
    status = min((p["verdict"] for p in ours), key=order.index)
    run_validity = dict(status=status, reason="; ".join(f"{p['policy']}: {p['verdict']}" for p in ours)
                        + ". VALID covers only the measured channels, never the uncovered ones below.")
    checks = [dict(check="Isolation (Red cannot reach Blue/model/internet)", result=iso),
              dict(check="Timing leak, worst measured case for our policies", result=worst),
              dict(check="Audit chain integrity", result=audit)]
    # Step results are looked up from the same data so the walkthrough shows what was measured.
    status = dict(isolation=iso, shapes=other_row_value(channels, "Error / status oracle"), timing=worst,
                  disclosure=other[2]["ours"]["ours"]["verdict"], audit=other[1]["ours"]["ours"]["verdict"])
    steps = [dict(n=n, what=what, how=how, control=control, result=status.get(key, "—") if key else "—") for n, what, how, control, key in STEPS]
    costs = cost_rows(saved)
    policies = policy_table(timing + timing_extra, shared)
    for p in policies:
        mine = [r for r in costs if r["policy"] == p["key"]]
        worst = min(mine, key=lambda r: r["completed"]) if mine else None
        p["usability"] = "NOT RUN" if worst is None else f"worst case {worst['completed']}% completed ({worst['cohort']})"
        p["unusable"] = [r["cohort"] for r in mine if r["usable"] == "NO"]
    return dict(costs=costs, policies=policies, steps=steps, channels=channels, checks=checks, validity=run_validity, not_covered=[dict(channel=a, note=b) for a, b in NOT_COVERED],
                matrix_saved=mx["saved"], matrix_total=mx["total"],
                note="Reasons are fixed explanations tagged MEASURED, NOTE or DESIGN. A run is VALID only if every covered check passes; "
                     "passing one channel says nothing about the channels in the last table.")


POLICY_NAMES = dict(raw="raw (no timing protection)", bucket="bucket (soft)", bucket_hard="bucket_hard (our default)",
                    window_hard="window_hard (one fixed window)",
                    window_continue="window_hard + continue (no cancel, opt-in)")
BAD, OK = ("FAIL", "LEAKED", "INVALID"), ("PASS", "VALID", "BLOCKED", "NO LEAK FOUND")


def policy_table(timing, shared):
    timing = [dict(row, ours={p: row["ours"].get(p, dict(value="NOT RUN", verdict="NOT RUN")) for p in ORDER[1:]}) for row in timing]
    """Per policy: which channels passed, failed, were uncertain or never measured, and why the run verdict follows."""
    out = []
    for policy in ORDER:
        results = [(row["channel"], row["ours"][policy]["verdict"] if policy != "raw" else row["baseline"]["verdict"]) for row in timing]
        results += shared
        failed = [c for c, r in results if r in BAD]
        uncertain = [c for c, r in results if r == "BOUNDED LEAK"]
        missing = [c for c, r in results if r == "NOT RUN"]
        if failed:
            verdict, because = "INVALID", "Failed: " + "; ".join(failed)
        elif missing:
            verdict, because = "INCOMPLETE", "Not measured: " + "; ".join(missing)
        else:
            verdict, because = "VALID", "Every covered channel passed (uncovered channels are listed below)."
        out.append(dict(policy=POLICY_NAMES[policy], verdict=verdict, key=policy, because=because, failed=failed, uncertain=uncertain, missing=missing,
                        passed=[c for c, r in results if r in OK]))
    return out


def other_row_value(channels, prefix):
    row = next((c for c in channels if c["channel"].startswith(prefix)), None)
    return row["ours"]["ours"]["verdict"] if row else "NOT RUN"
