"""Allowlisted projection for the side-by-side view. Metadata only: no prompt text, no keywords, no keys.

Everything comes from the recorded run (duel_run.py) and saved matrix/evidence files. Missing data is NOT RUN, never filled.
"""
import statistics
import time
from pathlib import Path

from . import history, why
from .data import matrix, number, read_json

LABEL = "live gateway, mock model, local run"
POLICY_LABEL = dict(raw="raw", bucket_hard="bucket_hard", window_hard="window_hard", window_continue="window_hard + continue")
NR = "NOT RUN"


def why_text(case, request):
    """Plain Hinglish reason for the Blue decision and what the model did (evaluator-only)."""
    evaluator = request.get("evaluator") or {}
    allowed = evaluator.get("blue_allowed")
    if allowed is None:
        return NR
    if not allowed:
        return f"Blocked: Blue ke {why_rule()} match hua, model tak gaya hi nahi"
    text = "Allowed: koi rule match nahi hua"
    if case == "repeat":
        text += "; same probe pehle bhi aaya, model ka cache use hua"
    if evaluator.get("late"):
        text += "; model ne fixed window ke baad jawab diya (peeche chalta raha, cancel nahi hua)"
    return text


def why_rule():
    return "keyword rule A"


def red_text(red):
    if red.get("status") is None or red.get("release_seconds") is None:
        return NR
    return f"Red ko dikha: HTTP {red['status']} pending, {red['release_seconds']:.2f} s"


def model_text(evaluator):
    if evaluator.get("blue_allowed") is None:
        return NR
    if not evaluator.get("model_called"):
        return "Model call nahi hua (Blue ne block kiya)"
    return "Mock model: fixed dummy answer (real model nahi)" + ("" if evaluator.get("model_completed") else "; jawab poora nahi hua")


def accuracy(saved, policy):
    """Red's A-vs-B accuracy for this policy from the saved matrix; NOT RUN when absent. Never a headline from missing cells."""
    rows = matrix(saved)["rows"] + why.variant_rows(saved)
    cells = [r for r in rows if r["policy"] == policy and r["status"] == "SAVED" and r["accuracy"] is not None]
    if not cells:
        return dict(status=NR, label=LABEL, text="NOT RUN: no saved matrix cells for this policy")
    values = [100 * r["accuracy"] for r in cells]
    tests = sorted({int(r["n"]) for r in cells if r["n"]})
    note = " (worse of two repeats per cohort)" if policy == "window_continue" else ""
    return dict(status="SAVED", label=LABEL, cells=len(cells), n_per_cell=tests[0] if tests else None,
                low=round(min(values), 1), high=round(max(values), 1),
                text=f"Red's A-vs-B accuracy {why.span(values)} over {len(cells)} saved cohorts, {tests[0] if tests else '?'} unseen runs per cohort{note}; 50% = guessing")


def times(arm, case):
    return [r["red"]["release_seconds"] for r in arm["requests"] if r["case"] == case and r["red"].get("release_seconds") is not None]


def timing_note(arm):
    """What Red could tell from release times in this recording (measured)."""
    blocked, allowed = times(arm, "blocked"), times(arm, "allowed")
    every = [r["red"]["release_seconds"] for r in arm["requests"] if r["red"].get("release_seconds") is not None]
    if not every:
        return NR
    if blocked and allowed:
        gap = statistics.median(allowed) - statistics.median(blocked)
        return (f"Blocked median {statistics.median(blocked):.2f} s vs allowed median {statistics.median(allowed):.2f} s "
                f"(gap {1000 * gap:.0f} ms); all requests {min(every):.2f}-{max(every):.2f} s")
    return f"All requests {min(every):.2f}-{max(every):.2f} s"


def project_arm(arm, sequence):
    requests = []
    for item, request in zip(sequence, arm.get("requests", [])):
        evaluator = request.get("evaluator") or {}
        requests.append(dict(
            index=item["index"], probe=item["probe"], group=item["group"], case=item["case"],
            red=dict(status=request["red"].get("status"), body_length=request["red"].get("body_length"),
                     release_seconds=request["red"].get("release_seconds"), envelope_exact=request["red"].get("envelope_exact") is True,
                     text=red_text(request["red"])),
            evaluator=dict(blue_allowed=evaluator.get("blue_allowed"), model_called=evaluator.get("model_called"),
                           model_completed=evaluator.get("model_completed"), late=evaluator.get("late"), cancelled=evaluator.get("cancelled"),
                           why=why_text(item["case"], request), model=model_text(evaluator))))
    meter = arm.get("meter")
    return dict(name=arm.get("name"), title=arm.get("title"), policy=arm.get("policy"), window_continue=arm.get("window_continue") is True,
                feedback_mode=arm.get("feedback_mode", "none"), requests=requests, timing=timing_note(dict(requests=requests)),
                audit=dict(status=(arm.get("audit") or {}).get("status", NR), events=(arm.get("audit") or {}).get("count")),
                meter=None if not meter else dict(
                    reads=[dict(after_probe=r.get("after_probe"), state=r.get("state")) for r in meter.get("reads", [])],
                    reads_used=meter.get("reads_used"), reads_budget=meter.get("reads_budget"),
                    reads_left=None if meter.get("reads_used") is None else max(0, meter.get("reads_budget", 3) - meter["reads_used"]),
                    batches=[dict(batch=b.get("batch"), score=b.get("score"), published=b.get("published"), true_state=b.get("true_state"))
                             for b in meter.get("batches", [])]))


def chart_rows(saved):
    rows = matrix(saved)["rows"] + why.variant_rows(saved)
    return [dict(policy=r["policy"], label=POLICY_LABEL.get(r["policy"], r["policy"]), cohort=r["cohort"], status=r["status"],
                 accuracy=r["accuracy"], interval=r["interval"], n=r["n"]) for r in rows if r["policy"] in POLICY_LABEL]


def snapshot(saved, observations):
    recording = read_json(Path(observations) / "duel.json")
    sequence = [dict(index=i["index"], probe=i["probe"], group=i["group"], case=i["case"])
                for i in recording.get("sequence", []) if isinstance(i, dict)]
    arms = {name: project_arm(arm, sequence) for name, arm in (recording.get("arms") or {}).items()
            if isinstance(arm, dict) and name in ("raw", "ours")}
    complete = recording.get("status") == "complete" and set(arms) == {"raw", "ours"}
    summary = why.summary(saved)
    isolation = history.build("isolation", "Isolation", "Isolation", "evidence/isolation.txt", "isolation", "", saved)
    tamper = history.build("audit-tamper", "Audit tamper", "Audit", "evidence/audit-docker.txt", "tamper", "", saved)
    recorded = number(recording.get("recorded_at"))
    return dict(
        label=LABEL, status="RECORDED" if complete else "PARTIAL" if arms else NR,
        recorded_at=None if recorded is None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(recorded)),
        note="Playback of a recorded run (not live). Same request sequence, same Blue rule, same audit; only timing and the opt-in meter differ.",
        sequence=sequence if complete else [], arms=arms if complete else {},
        accuracy=dict(raw=accuracy(saved, "raw"), ours=accuracy(saved, "window_continue")), chart=chart_rows(saved),
        isolation=dict(result=isolation["result"], headline=isolation["headline"], details=isolation["details"], recorded_at=isolation["recorded_at"]),
        tamper=dict(result=tamper["result"], headline=tamper["headline"], details=tamper["details"], recorded_at=tamper["recorded_at"]),
        limits=summary["limits"], not_stopped=summary["not_stopped"])
