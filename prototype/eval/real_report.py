"""Builds REAL_MODEL_REPORT.md from every saved real-model result and request file (PARAMS v4, v5, v6).

    python -m eval.real_report          # reads eval/output/real_timing, real_suite, real_overnight; writes REAL_MODEL_REPORT.md

Everything in the report is read from saved files; nothing is typed in by hand. Request-level statistics come from the per-request JSONL files
(what Red saw and what the evaluator knew for EVERY request). Label: real model run, small sample, local.
"""
import argparse
import json
from pathlib import Path
import statistics

from stats import percentile

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pct(value):
    return "n/a" if value is None else f"{100 * value:.1f}%"


def span(interval):
    return "n/a" if not interval else f"{100 * interval[0]:.1f}-{100 * interval[1]:.1f}%"


def q(values, quantiles=(50, 95, 99)):
    if not values:
        return "n/a"
    return " / ".join(f"{percentile(values, k):.3f}" for k in quantiles) + f" / {max(values):.3f}"


def cell_rows(results):
    lines = ["| Step | Cohort | Policy | Red's A-vs-B accuracy (95% Wilson) | Train | Gap | Verdict | Release median / p95 / p99 / max (s) | Late / cancelled | Audit |",
             "|---|---|---|---:|---:|---:|---|---|---|---|"]
    for name, d in results:
        release = d.get("release_seconds") or d.get("observer_release_seconds") or {}
        audit = d.get("audit") if isinstance(d.get("audit"), dict) else {}
        queue = d.get("audit_queue_after_drain")
        audit_text = f"{audit.get('valid')}/{audit.get('runs')} valid" if audit else (
            "; ".join(f"world {x['world']}: {x['pending_after_drain']} pending, {x['dead_letters']} dead" for x in queue) if queue else "n/a")
        gap = "n/a" if d.get("train_accuracy") is None else "%+.0f pts" % (100 * (d["train_accuracy"] - d["accuracy"]))
        lines.append(f"| {name} | {d.get('cohort') or ('flood observer' if d.get('flood_workers') else 'ordinary')} | {d.get('policy')}{' + continue' if d.get('window_continue') else ''} | "
                     f"{pct(d.get('accuracy'))} ({span(d.get('wilson_95'))}) | {pct(d.get('train_accuracy'))} | "
                     f"{gap} | {d.get('verdict')} | "
                     f"{release.get('median')} / {release.get('p95')} / {release.get('p99', 'n/a')} / {release.get('max')} | "
                     f"{d.get('late_after_deadline', 'n/a')} / {d.get('cancelled', d.get('observer_cancelled'))} | {audit_text} |")
    return lines


def request_stats(path, window):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    groups = {}
    for row in rows:
        groups.setdefault((row.get("role"), row.get("case")), []).append(row)
    lines = [f"| role | case | requests | Red's release median / p95 / p99 / max (s) | share later than W + 0.5 s | Blue allowed | backend | answer chars median | completion tokens mean / max |",
             "|---|---|---:|---|---:|---:|---|---:|---|"]
    for (role, case), items in sorted(groups.items(), key=lambda kv: str(kv[0])):
        totals = [r["client"]["total"] for r in items if r.get("client")]
        evaluator = [r["evaluator"] for r in items if r.get("evaluator")]
        tokens = [(e.get("usage") or {}).get("completion_tokens") for e in evaluator if (e.get("usage") or {}).get("completion_tokens") is not None]
        chars = [e["answer_chars"] for e in evaluator if e.get("answer_chars") is not None]
        allowed = [e["blue_allowed"] for e in evaluator if e.get("blue_allowed") is not None]
        backends = sorted({str(e.get("backend")) for e in evaluator if e.get("backend")})
        slip = "n/a" if window is None else f"{100 * sum(t > window + 0.5 for t in totals) / len(totals):.1f}%"
        lines.append(f"| {role} | {case} | {len(items)} | {q(totals)} | {slip} | {pct(sum(allowed) / len(allowed)) if allowed else 'n/a'} | "
                     f"{', '.join(backends) or '-'} | {statistics.median(chars) if chars else 'n/a'} | "
                     f"{f'{statistics.mean(tokens):.0f} / {max(tokens)}' if tokens else 'n/a'} |")
    total_tokens = sum((r.get("evaluator") or {}).get("usage", {}).get("completion_tokens", 0) or 0 for r in rows if (r.get("evaluator") or {}).get("usage"))
    return lines, len(rows), total_tokens


def build(root=ROOT):
    root = Path(root)
    results = []
    for folder in ("real_timing", "real_overnight"):
        for path in sorted((root / "eval/output" / folder).glob("*.json")):
            data = load(path)
            if isinstance(data, dict) and "accuracy" in data:
                results.append((f"{folder}/{path.stem}", data))
    docker = load(root / "eval/output/real_suite/docker_check.json")
    lines = ["# Real-model report (generated from saved files)", "",
             "Label: real model run, small sample, local (localhost processes; one Docker check). DeepSeek `deepseek-flash`. Parameters fixed in `PARAMS.md` v4, v5 and v6 before each run. "
             "50% = the tested attacker could not tell Blue's rule A from B; it is not proof of no leak. Every number below is read from `eval/output/`.", "",
             "## 1. All cells", ""] + cell_rows(results) + [""]
    lines += ["## 2. Diagnosis of the release-time slip (PARAMS v6)", ""]
    any_diag = False
    for name, d in results:
        diag = d.get("diagnostics")
        if not diag:
            continue
        any_diag = True
        lag = diag["loop_lag"]
        lines += [f"**{name}** (W = {diag['window_seconds']} s): {diag['requests_observed']} client-observed requests, {diag['slipped_requests']} slipped (> W + 0.5 s); "
                  f"client release {q([]) if not diag.get('client_release') else diag['client_release']}; server-side lateness {diag['server_lateness_seconds']}; "
                  f"gateway-side late > 0.25 s: {diag['server_side_late_over_0_25_s']}, > 1 s: {diag['server_side_late_over_1_s']}; "
                  f"slipped requests overlapping a loop-lag event: {diag['slipped_overlapping_a_loop_lag_event']}; loop lag: {lag['events']} events, max {lag['max_seconds']} s, "
                  f"{lag['events_over_1_s']} over 1 s, max background tasks {lag['max_background_tasks']}, max in-flight {lag['max_inflight']}, max asyncio tasks {lag['max_asyncio_tasks']}. "
                  f"Reading: {diag['reading']}.", ""]
    if not any_diag:
        lines += ["NOT RUN: no diagnostics file found.", ""]
    lines += ["## 3. Below-chance check (label permutations)", ""]
    checks = [(n, d["permutation_check"]) for n, d in results if d.get("permutation_check")]
    if checks:
        lines += ["| Step | Observed test accuracy | Swapped-split accuracy | Null mean (sd) | Two-sided p |", "|---|---:|---:|---|---:|"]
        lines += [f"| {n} | {c['observed_test_accuracy']} | {c['swapped_split_accuracy']} | {c['null_mean']} ({c['null_sd']}) | {c['two_sided_p']} |" for n, c in checks]
    else:
        lines += ["NOT RUN: no permutation checks found (only cells run under PARAMS v6 have saved samples)."]
    lines += ["", "## 4. Flood with the real model: audit and load", ""]
    floods = [(n, d) for n, d in results if d.get("flood_workers")]
    if floods:
        for name, d in floods:
            lines += [f"- **{name}**: {d.get('mean_flood_requests_per_run')} flood requests per run, observer attempts recorded {d.get('mean_observer_attempts_recorded')}, observer cancelled {d.get('observer_cancelled')}, "
                      f"max sampled audit outbox {d.get('max_outbox_sampled')}, queue after drain {d.get('audit_queue_after_drain')}, dead servers {d.get('dead_servers')}, "
                      f"throughput check passed: {(d.get('throughput_check') or {}).get('passed')}."]
    else:
        lines += ["NOT RUN: no flood cell found."]
    lines += ["", "## 5. Every request (what Red saw, what the evaluator knew)", ""]
    windows = {d.get("cell") and f"{d.get('cohort')}-s{d.get('seed')}-{d.get('cell')}": d.get("window_seconds") for _, d in results if d.get("cell")}
    windows |= {d["cell"]: d.get("window_seconds") for _, d in results if d.get("flood_workers") and d.get("cell")}
    request_dir = root / "eval/output/real_overnight/requests"
    files = sorted(request_dir.glob("*.jsonl")) if request_dir.exists() else []
    grand_requests, grand_tokens = 0, 0
    for path in files:
        table, count, tokens = request_stats(path, windows.get(path.stem))
        grand_requests += count
        grand_tokens += tokens
        lines += [f"### `{path.name}` ({count} requests, {path.stat().st_size // 1024} KiB)", ""] + table + [""]
    lines += [f"Total request records: {grand_requests}; completion tokens recorded: {grand_tokens}. The private answer texts are in `dashboard/runtime/private/real_overnight/` (git-ignored)."
              if files else "NOT RUN: no per-request files found (they are written by `eval.real_overnight`).", "", "## 6. Docker check with the real model", ""]
    lines += [f"```json\n{json.dumps(docker, indent=2)}\n```"] if docker else ["NOT RUN."]
    lines += ["", "## 7. Files", ""] + [f"- `{n}.json`" for n, _ in results] + [f"- `eval/output/real_overnight/requests/{p.name}`" for p in files]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "REAL_MODEL_REPORT.md")
    args = parser.parse_args()
    args.output.write_text(build(), encoding="utf-8")
    print("wrote", args.output)


if __name__ == "__main__":
    main()
