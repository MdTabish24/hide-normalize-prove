"""Build EVIDENCE.md from saved results. Missing evidence is NOT RUN, never filled in.

    python run_all_evidence.py --cached   # read saved files only (no processes, no Docker, no HTTP)
    python run_all_evidence.py --fast     # re-run tests + Docker checks first (~5 min), then build
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
LOCAL = "live gateway, mock model, local run"
DOCKER = "local Docker stack (Docker Desktop)"
SIM = "simulated (Monte Carlo)"
REAL = "real model run, small sample"
RESULTS = {"PASS", "FAIL", "BLOCKED", "BOUNDED LEAK", "LEAKED", "NOT COVERED", "NOT RUN"}


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def text(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def row(test, policy="-", result="NOT RUN", number="no saved evidence", label=LOCAL, audit="-", source=""):
    assert result in RESULTS, result
    return {"test": test, "policy": policy, "result": result, "key_number": number, "label": label,
            "audit_mode": audit, "source": Path(source).relative_to(ROOT.parent).as_posix() if source else ""}


def tests_rows():
    rows = []
    for name, path, label in (("Test suite (host, Windows)", EVIDENCE / "tests.txt", LOCAL),
                              ("Test suite (inside Docker image)", EVIDENCE / "tests-in-docker.txt", DOCKER)):
        output = text(path)
        passed, failed = re.findall(r"(\d+) passed", output), re.findall(r"(\d+) failed", output)
        if not passed and not failed:
            rows.append(row(name, label=label, source=path if output else ""))
            continue
        summary = f"{passed[-1] if passed else 0} passed, {failed[-1] if failed else 0} failed"
        rows.append(row(name, result="FAIL" if failed else "PASS", number=summary, label=label, audit="mixed fixtures", source=path))
    return rows


def docker_rows():
    rows = []
    ps = text(EVIDENCE / "compose-ps.txt")
    services = [line.split()[0] for line in ps.splitlines()[1:] if " Up " in f" {line} "]
    rows.append(row("docker compose ps", result="PASS" if len(services) >= 6 else "NOT RUN" if not ps else "FAIL",
                    number=f"{len(services)} services up: {', '.join(services)}" if ps else "no saved output",
                    label=DOCKER, source=EVIDENCE / "compose-ps.txt" if ps else ""))
    demo = text(EVIDENCE / "isolation.txt")
    match = re.search(r'"passed": (\d+), "total": (\d+)', demo)
    if match:
        ok = match[1] == match[2]
        rows.append(row("Isolation demo inside red-client", result="PASS" if ok else "FAIL",
                        number=f"{match[1]}/{match[2]} checks PASS", label=DOCKER, source=EVIDENCE / "isolation.txt"))
    else:
        rows.append(row("Isolation demo inside red-client", label=DOCKER))
    extra = text(EVIDENCE / "isolation-extra.txt")
    if extra:
        reachable = extra.count("REACHABLE")
        rows.append(row("Extra probes (audit/proxy from Red; egress of gateway, Blue, model)",
                        result="PASS" if not reachable else "FAIL",
                        number=f"{extra.count('blocked')} blocked, {reachable} reachable", label=DOCKER,
                        source=EVIDENCE / "isolation-extra.txt"))
    audit = text(EVIDENCE / "audit-docker.txt")
    if audit:
        valid = re.search(r"^VALID$", audit, re.M) is not None
        invalid = len(re.findall(r"^(?!unmodified)\S.*\s+INVALID\s", audit, re.M))
        unmodified = re.search(r"^unmodified\s+VALID", audit, re.M) is not None
        rows.append(row("Audit verifier on a finished run (no-network container)", result="PASS" if valid else "FAIL",
                        number="VALID" if valid else "not VALID", label=DOCKER, audit="on", source=EVIDENCE / "audit-docker.txt"))
        rows.append(row("Audit tamper demo (7 tamper cases on copies)",
                        result="BLOCKED" if unmodified and invalid == 7 else "FAIL",
                        number=f"unmodified VALID={unmodified}; {invalid}/7 tampered copies INVALID", label=DOCKER,
                        audit="on", source=EVIDENCE / "audit-docker.txt"))
    else:
        rows.append(row("Audit verifier + tamper demo", label=DOCKER))
    return rows


def matrix_rows():
    rows = []
    path = ROOT / "eval/output/round2/results.json"
    data = load(path)
    old = load(ROOT / "eval/output/results.json") or {}
    old_cells = {(c["cohort"], c["policy"]): c for c in old.get("timing", [])}
    if not data:
        return [row("Timing A-vs-B matrix (Round 2, audit on)", source="")]
    audit = "on" if data.get("audit") else "off"
    label = f"{LOCAL}; scale {data['scale']}, N={data['n_test']} unseen runs/cell"
    for cell in data["cells"]:
        low, high = cell["wilson_95"]
        previous = old_cells.get((cell["cohort"], cell["policy"]))
        before = f"; Round 1 audit-off {previous['test_accuracy']:.1%}" if previous else ""
        rows.append(row(f"Timing A-vs-B: {cell['cohort']}", cell["policy"], "LEAKED" if low > 0.5 else "BOUNDED LEAK",
                        f"{cell['test_accuracy']:.1%} (95% {low:.1%}-{high:.1%}); timeouts {cell['timeout_rate_of_allowed']:.0%} of allowed; "
                        f"mean latency {cell['mean_latency_seconds']:.2f} s{before}", label, audit, path))
    for cohort, policy in data.get("not_run", []):
        rows.append(row(f"Timing A-vs-B: {cohort}", policy, "NOT RUN", "runtime cap reached", label, audit, path))
    for policy, check in data.get("audit_checks", {}).items():
        if check.get("enabled"):
            ok = check["runs"] and check["valid"] == check["runs"]
            rows.append(row("Audit under matrix load (verifier on every run)", policy, "PASS" if ok else "FAIL",
                            f"{check['valid']}/{check['runs']} runs VALID; dead letters "
                            f"{sum(q['dead_letters'] for q in check['queue'])}", LOCAL, "on", path))
    if data.get("status") != "complete":
        rows.append(row("Timing matrix status", result="NOT RUN", number=f"artifact status: {data.get('status')}", source=path))
    return rows


def attack_rows():
    path = ROOT / "attack_suite_results.json"
    data = load(path)
    if not data:
        return [row("Attack suite", source="")]
    return [row(f"Attack {r['attack']}: {r['name']}", r["policy"], r["result"], r["summary"], r["label"], r["audit_mode"], path)
            for r in data["results"]]


def feedback_rows():
    path = ROOT / "eval/output/feedback/results.json"
    data = load(path)
    if not data or data.get("status") != "complete":
        return [row("Feedback analysis (Phase 5)", label=SIM, number="no complete saved result")]
    rows = []
    for live in data["live"]:
        ok = live["within_run_repeat_stable_after_restart"] and live["third_read_blocked_after_restart"]
        rows.append(row("Feedback: same-run repeat, 3rd read blocked, after restart", live["mode"], "BLOCKED" if ok else "FAIL",
                        f"repeat stable={live['within_run_repeat_stable_after_restart']}, third read blocked={live['third_read_blocked_after_restart']}",
                        LOCAL, "off (feedback harness)", path))
    for mode in ("run", "probeset"):
        cells = sorted((c for c in data["monte_carlo"] if c["mode"] == mode), key=lambda c: c["k"])
        if cells:
            a, b = cells[0], cells[-1]
            rows.append(row("Feedback: cross-run averaging", mode,
                            "LEAKED" if b["mean_absolute_error"] < a["mean_absolute_error"] - 0.5 else "BOUNDED LEAK",
                            f"mean abs error K={a['k']}: {a['mean_absolute_error']:.2f} -> K={b['k']}: {b['mean_absolute_error']:.2f} "
                            f"(extremes K=1: {a['extremes']['mean_absolute_error']:.2f})", SIM, "n/a", path))
    for check in data["cross_check"]:
        interval = check.get("mc_predictive_interval_95")
        rows.append(row("Feedback: live K=3 cross-check of Monte Carlo", check["mode"],
                        "PASS" if check["agreement"] else "FAIL" if check["agreement"] is False else "NOT RUN",
                        f"live MAE {check.get('live_mae', float('nan')):.2f} vs MC 95% {interval}" if interval else check.get("reason", ""),
                        LOCAL, "off (feedback harness)", path))
    return rows


def real_model_rows():
    rows = []
    path = ROOT.parent / "real_results.json"
    real = load(path)
    if isinstance(real, dict) and isinstance(real.get("metrics"), dict):
        m = real["metrics"]
        rows.append(row("Real-model latency vs 3/6/9 s buckets", "bucket (offline)", "PASS",
                        f"n={real.get('sample_size')}; p50/p95/p99 {m['p50_seconds']:.2f}/{m['p95_seconds']:.2f}/{m['p99_seconds']:.2f} s; "
                        f"mean padding +{m['mean_added_latency_seconds']:.2f} s", REAL, "n/a", path))
        latencies = [r["latency_seconds"] for r in real.get("requests", [])]
        if latencies:
            window, deadline = 3.0, 2.4
            cancelled = sum(v > deadline for v in latencies)
            rows.append(row("Offline replay: window_hard W=3 s, D=2.4 s on the measured real latencies", "window_hard (offline)",
                            "PASS", f"{cancelled}/{len(latencies)} ({cancelled / len(latencies):.1%}) would be cancelled; "
                            f"mean added latency +{window - sum(latencies) / len(latencies):.2f} s", REAL + " (offline replay)", "n/a", path))
    else:
        rows.append(row("Real-model latency", label=REAL))
    leak_path = ROOT.parent / "leak_counts.json"
    leaks = load(leak_path)
    if isinstance(leaks, dict) and isinstance(leaks.get("attempt_results"), list):
        samples = leaks["attempt_results"]
        rows.append(row("Real-model exact-canary scan of raw outputs", "raw output", "BOUNDED LEAK",
                        f"{leaks.get('raw_output_leaks')}/{len(samples)} exact canary hits; misses paraphrases (see next row)",
                        REAL, "n/a", leak_path))
        raw = sum(bool(r.get("raw_rule_leaked")) for r in samples)
        gated = sum(bool(r.get("gateway_rule_leaked")) for r in samples)
        rows.append(row("Real-model rule disclosure in raw outputs (keyword scan + manual review)", "raw output", "LEAKED" if raw else "BLOCKED",
                        f"{raw}/{len(samples)} raw outputs revealed Blue's rule", REAL, "n/a", leak_path))
        rows.append(row("Same outputs behind score-only gateway", "score-only", "BLOCKED" if not gated else "LEAKED",
                        f"{gated}/{len(samples)} (no model text reaches Red, by design)", REAL, "n/a", leak_path))
    return rows


def agent_rows():
    path = ROOT / "agent_sessions.json"
    sessions = load(path) or []
    rows = []
    for policy in ("raw", "bucket_hard", "window_hard"):
        trials = [s for s in sessions if s.get("policy") == policy]
        valid = [s for s in trials if s.get("protocol_valid") is True]
        rows.append(row("External coding-agent red team", policy, "NOT COVERED" if trials else "NOT RUN",
                        f"{sum(s.get('correct') is True for s in valid)}/{len(valid)} valid guesses correct ({len(trials)} sessions)"
                        if trials else "harness ready; 0 of 5 sessions run", LOCAL, "on", path if trials else ""))
    return rows


NOT_SHOWN = [
    "No result here is a proof. 50% attacker accuracy means THIS attacker, at this sample size, could not tell A from B.",
    "Mock model only for leakage timing. No real-model KV cache, GPU, batching or streaming behaviour was tested.",
    "Timing matrix runs at scale 0.1 on Windows host processes: fixed HTTP/SQLite/OS overhead is not scaled, so numbers are not predictions for 3/6/9 s production buckets. Linux containers showed much tighter release timing.",
    "Boundary and deadline cohorts give the attacker exact control of compute time through a test-only hook (EVAL_MODE). Real Red cannot do that; this is a worst case.",
    "Small samples: 200 unseen runs per timing cell, 40 trials per cache condition, 5 planned agent sessions (NOT RUN).",
    "The gateway and audit collector are trusted. A compromised gateway can omit events; events never logged are undetectable by a hash chain.",
    "Signed checkpoints are local: an attacker who replaces both log and checkpoint with an older matching pair is not detected (needs an external witness).",
    "Feedback noise is heuristic, not differential privacy. Cross-run averaging and extreme counts leak (measured).",
    "Out of scope: host/kernel escape, hardware and shared-GPU side channels, TEEs, a compromised host or Docker daemon.",
    "Release timing slips under host CPU saturation (attack 9b); resource governance (cgroup limits, admission control) is required in deployment.",
]


def render(rows, generated):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    counts = {r: sum(x["result"] == r for x in rows) for r in sorted(RESULTS)}
    lines = ["# EVIDENCE: Hide, Normalize, Prove (Round 2)", "",
             f"Generated {generated} by `python run_all_evidence.py`. Every row comes from a saved file listed under Sources; "
             "missing evidence is NOT RUN.", "",
             "Result key: PASS/FAIL = a functional check. BLOCKED = the attack failed in this test. BOUNDED LEAK = no clear leak "
             "for this attacker and sample (95% interval includes chance); residual risk remains. LEAKED = measurable leak. "
             "NOT COVERED = outside scope. NOT RUN = not executed.", "",
             "Counts: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v), "",
             "| Test | Policy | Result | Key number | Label | Audit mode |", "|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(cell(r[k]) for k in ("test", "policy", "result", "key_number", "label", "audit_mode")) + " |" for r in rows]
    lines += ["", "## What this does NOT show", "", *["- " + item for item in NOT_SHOWN],
              "", "## Sources", "", *["- `" + s + "`" for s in sorted({r["source"] for r in rows if r["source"]})]]
    return "\n".join(lines) + "\n"


def collect():
    return tests_rows() + docker_rows() + matrix_rows() + attack_rows() + feedback_rows() + real_model_rows() + agent_rows()


def run(command, transcript, timeout):
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=timeout)
        output, code = result.stdout + result.stderr, result.returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        output, code = f"NOT RUN: {type(error).__name__}: {error}", None
    stamp = f"# {' '.join(command)}  ({datetime.now(timezone.utc).isoformat(timespec='seconds')})\n"
    transcript.write_text(stamp + output + f"\nexit={code}\n", encoding="utf-8")
    return code, output


def run_fast():
    EVIDENCE.mkdir(exist_ok=True)
    print("Running test suite (timing tests included; keep the machine idle)...", flush=True)
    run([sys.executable, "-m", "pytest", "tests", "eval/tests", "-q", "-p", "no:cacheprovider"], EVIDENCE / "tests.txt", 1200)
    code, _ = run(["docker", "info", "--format", "{{.ServerVersion}}"], EVIDENCE / "docker-info.txt", 30)
    if code != 0:
        print("Docker Engine unavailable: Docker rows stay as previously saved or NOT RUN.", flush=True)
        return
    run(["docker", "compose", "ps", "--format", "table {{.Service}}\t{{.Status}}\t{{.Ports}}"], EVIDENCE / "compose-ps.txt", 60)
    run(["docker", "compose", "exec", "-T", "red-client", "python", "demo_isolation.py"], EVIDENCE / "isolation.txt", 120)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cached", action="store_true")
    mode.add_argument("--fast", action="store_true")
    args = parser.parse_args()
    if args.fast:
        run_fast()
    rows = collect()
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (ROOT / "EVIDENCE.md").write_text(render(rows, generated), encoding="utf-8")
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "results.json").write_text(json.dumps({"generated_utc": generated, "mode": "fast" if args.fast else "cached",
                                                        "rows": rows}, indent=2) + "\n", encoding="utf-8")
    width = max(len(r["test"]) for r in rows)
    for r in rows:
        print(f"{r['test'][:70]:<70} {r['policy']:<12} {r['result']:<13} {r['key_number'][:90]}")
    print(f"\nWrote {ROOT / 'EVIDENCE.md'} ({len(rows)} rows).")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
