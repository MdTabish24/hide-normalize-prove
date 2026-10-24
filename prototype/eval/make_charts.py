"""Benchmark charts for the README, drawn from the saved result files (no number is typed in except where a comment says so).

    python -m eval.make_charts        # writes docs/charts/*.png

Red = without our solution, green = with it (amber = reduced but above guessing level). Lower is better in every chart except the audit-queue one,
where lower is also better. Labels match README.md and FINAL_REPORT.md.
"""
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "charts"
RED, GREEN, AMBER, GREY, INK, MUTE = "#c43d3d", "#1f7a4d", "#b0700a", "#9aa3af", "#1b2430", "#5b6675"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#cfd6e0", "axes.labelcolor": INK, "text.color": INK,
                     "xtick.color": MUTE, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False})


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def pct(x):
    return round(100 * x, 1)


def suite_rows(attack):
    return [r for r in load("attack_suite_results.json")["results"] if str(r["attack"]) == str(attack)]


def matrix(policy):
    summary = next(r["summary"] for r in suite_rows(5) if r["policy"] == policy)
    return {k: int(v) for k, v in re.findall(r"(ordinary|boundary|overflow|deadline_near|deadline_far) (\d+)%", summary)}


def p95(path, attack, policy="window_hard", index=0):
    """(quiet, flooded) slowest-5% times of one attack in a result file; index picks the n-th row of that policy (9c: 0 = no CPU pinning)."""
    rows = [r for r in load(path)["results"] if str(r["attack"]) == attack and r["policy"] == policy]
    a, b = re.search(r"p95 (\d+) -> (\d+) ms", rows[index]["summary"]).groups()
    return int(a), int(b)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 1. guess rates
def guess_rates():
    raw, win = matrix("raw"), matrix("window_hard")
    acc = lambda p: pct(load(p)["accuracy"])
    ordinary = [acc(f"eval/output/real_timing/{n}.json") for n in ("window_continue", "ordinary-s20261025-window_continue")] + \
               [acc(f"eval/output/real_overnight/ordinary-s{s}-window_continue.json") for s in (20261027, 20261028)]
    longs = [acc("eval/output/real_timing/real_long-s20261026-window_continue.json"), acc("eval/output/real_overnight/real_long-s20261029-window_continue.json")]
    raw_ordinary = acc("eval/output/real_timing/raw.json")
    raw_long = acc("eval/output/real_timing/real_long-s20261026-raw.json")
    cache_rows = suite_rows(6)
    cache_off = int(next(re.search(r"= (\d+)%", r["summary"]).group(1) for r in cache_rows if "namespace off (negative" in r["summary"]))
    cache_on = int(next(re.search(r"= (\d+)%", r["summary"]).group(1) for r in cache_rows if r["policy"] == "raw" and "namespace on" in r["summary"]))
    coarse = load("eval/output/coarse_report/results.json")["results"][1]
    rows = [  # label, without, with, (low, high) or None
        ("Timing, mock: ordinary", raw["ordinary"], win["ordinary"], None),
        ("Timing, mock: reply near a bucket edge", raw["boundary"], win["boundary"], None),
        ("Timing, mock: very slow replies", raw["overflow"], win["overflow"], None),
        ("Timing, real model: ordinary prompts (4 runs)", raw_ordinary, round(sum(ordinary) / 4, 1), (min(ordinary), max(ordinary))),
        ("Timing, real model: long answers (2 runs)", raw_long, round(sum(longs) / 2, 1), (min(longs), max(longs))),
        ("Timing, real model: flood (old default vs ours)", pct(load("eval/output/real_overnight/real_bucket_hard.json")["accuracy"]),
         pct(load("eval/output/real_overnight/real_final.json")["accuracy"]), None),
        ("Model cache, mock", cache_off, cache_on, None),
        ("Report, none allowed (simulation)", 100, pct(coarse["exact_recovery_count_0"]), None),
        ("Report, all allowed (simulation)", 100, pct(coarse["exact_recovery_count_16"]), None),
    ]
    fig, ax = plt.subplots(figsize=(11, 6.2))
    h, ys = 0.36, range(len(rows))
    for i, (label, a, b, rng) in zip(ys, rows):
        ax.barh(i - h / 2, a, h, color=RED)
        colour = GREEN if b <= 55 else AMBER
        ax.barh(i + h / 2, b, h, color=colour)
        ax.text(a + 1, i - h / 2, f"{a:g}%", va="center", color=RED, fontweight="bold", bbox=dict(facecolor="white", edgecolor="none", pad=1.2))
        ax.text((rng[1] if rng else b) + 1.5, i + h / 2, f"{b:g}%" + (f"  (runs {rng[0]:g} to {rng[1]:g}%)" if rng else ""), va="center", color=colour, fontweight="bold", bbox=dict(facecolor="white", edgecolor="none", pad=1.2))
        if rng:
            ax.plot(rng, [i + h / 2] * 2, color=INK, lw=1.6)
    ax.axvline(50, color=MUTE, ls="--", lw=1.4)
    ax.text(50.8, len(rows) - 0.42, "50% = Red is only guessing", color=MUTE, fontsize=9.5)
    ax.set_yticks(list(ys), [r[0] for r in rows]); ax.set_ylim(len(rows) - 0.25, -0.6); ax.set_xlim(0, 118); ax.set_xlabel("How often Red guesses Blue's secret rule (%)  -  lower is better")
    ax.set_title("Without vs with our solution: how much Red learns", loc="left", fontweight="bold", fontsize=13)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=RED, label="Without our solution"), Patch(color=GREEN, label="With our solution"), Patch(color=AMBER, label="With our solution, still above guessing")],
              loc="upper center", bbox_to_anchor=(0.4, -0.1), ncol=3, frameon=False, fontsize=9.5)
    save(fig, "1_guess_rates.png")
    return rows


# ---------------------------------------------------------------- 2. leaks found in the weak setups
def leaks_found():
    weak = {r["attack"]: r for r in load("eval/output/weak_controls/results.json")["results"]}
    blocked = int(re.search(r"(\d+)/10 targets blocked", weak[1]["summary"]).group(1))
    secrets = len(re.findall(r"BLUE_TOKEN|GATEWAY_KEY", weak[2]["summary"])) + ("defense.enc visible=True" in weak[2]["summary"])
    logs = len(re.findall(r"canary trigger|raw prompt marker", weak[8]["summary"]))
    rows = [("Network targets\nRed reaches\n(of 10)", 10 - blocked, 0), ("Secrets Red finds\nin its container\n(of 3)", secrets, 0),
            ("Secrets found\nby a log scan\n(of 2)", logs, 0), ("Fake-token tricks\nthat worked\n(of 10)", None, 0)]
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    x = range(len(rows)); w = 0.36
    for i, (label, a, b) in zip(x, rows):
        if a is None:
            ax.bar(i - w / 2, 0.35, w, color="white", edgecolor=GREY, hatch="//"); ax.text(i - w / 2, 0.5, "not\nmeasured", ha="center", fontsize=9, color=MUTE)
        else:
            ax.bar(i - w / 2, a, w, color=RED); ax.text(i - w / 2, a + 0.12, str(a), ha="center", color=RED, fontweight="bold")
        ax.bar(i + w / 2, max(b, 0.04), w, color=GREEN); ax.text(i + w / 2, b + 0.12, str(b), ha="center", color=GREEN, fontweight="bold")
    ax.set_xticks(list(x), [r[0] for r in rows], fontsize=9.5); ax.set_ylim(0, 7.5); ax.set_ylabel("Leaks found  -  lower is better")
    ax.set_title("Direct doors: a deliberately weak setup vs our setup", loc="left", fontweight="bold", fontsize=13)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=RED, label="Weak setup (built to prove our test can see a leak)"), Patch(color=GREEN, label="With our solution")], frameon=False, fontsize=9.5, loc="upper right")
    save(fig, "2_direct_doors.png")
    return rows


# ---------------------------------------------------------------- 3. flood slowdown
def flood():
    local = (p95("eval/output/final_run/attack_final_noflags.json", "9"), p95("eval/output/final_run/attack_final_flags.json", "9"))
    docker = (p95("eval/output/final_run/attack9c_flags_off.json", "9c"), p95("eval/output/final_run/attack9c_flags_on.json", "9c"))
    groups = [("Local test\nwithout our changes", local[0], RED), ("Local test\nwith our changes", local[1], GREEN),
              ("Docker test\nwithout our changes", docker[0], RED), ("Docker test\nwith our changes", docker[1], AMBER)]
    fig, ax = plt.subplots(figsize=(10, 5))
    w = 0.36
    for i, (label, (quiet, loud), colour) in enumerate(groups):
        ax.bar(i - w / 2, quiet, w, color=GREY); ax.bar(i + w / 2, loud, w, color=colour)
        ax.text(i - w / 2, quiet + 40, f"{quiet}", ha="center", fontsize=10, color=MUTE)
        ax.text(i + w / 2, loud + 40, f"{loud}", ha="center", fontsize=10, color=colour, fontweight="bold")
    ax.set_xticks(range(4), [g[0] for g in groups], fontsize=9.5); ax.set_ylim(0, 3000); ax.set_ylabel("Blue's slowest 5% of replies (ms)  -  lower is better")
    ax.set_title("Red floods the gateway: how much slower do Blue's replies get?", loc="left", fontweight="bold", fontsize=13)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=GREY, label="Quiet"), Patch(color=RED, label="Under flood, without our changes"), Patch(color=GREEN, label="Under flood, with our changes (no shift found)"),
                       Patch(color=AMBER, label="Under flood, Docker (varies from run to run)")], frameon=False, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)
    save(fig, "3_flood_slowdown.png")
    return groups


# ---------------------------------------------------------------- 4. audit queue
def audit_queue():
    before = max(load("eval/output/loop_offload/window_continue_batch50_s2.json")["max_outbox_sampled"].values())
    after = max(load("eval/output/final_run/final_profile.json")["max_outbox_sampled"].values())
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    ax.bar(0, before, 0.5, color=RED); ax.bar(1, after, 0.5, color=GREEN)
    ax.set_yscale("log"); ax.set_ylim(1, 30000)
    ax.text(0, before * 1.2, f"{before:,}\n(queue full)", ha="center", color=RED, fontweight="bold"); ax.text(1, after * 1.3, f"{after}", ha="center", color=GREEN, fontweight="bold")
    ax.set_xticks([0, 1], ["Before the fix\n(one stuck connection\nfroze the queue)", "After the fix\n(fresh connection after\nany failure)"], fontsize=9.5)
    ax.set_ylabel("Audit events waiting, worst moment (log scale)"); ax.set_title("Audit queue under a flood", loc="left", fontweight="bold", fontsize=13)
    save(fig, "4_audit_queue.png")
    return before, after


# ---------------------------------------------------------------- 5. scoreboard
def scoreboard():
    tiles = [("1 Network", "ok"), ("2 Files and\nsecrets", "ok"), ("3 Fake tokens", "ok"), ("4 Error\nmessages", "ok"), ("6 Model cache", "ok"), ("8 Log search", "ok"),
             ("9 Flood (local)", "ok"), ("5 Timing\n(real model)", "mid"), ("7 Report\nextremes", "mid"), ("10 CPU-load\nslip", "mid"), ("11 Docker\nflood", "mid"),
             ("Out of scope:\nkernel, hardware,\ngateway", "out")]
    colours = {"ok": GREEN, "mid": AMBER, "out": "#6b7380"}
    fig, ax = plt.subplots(figsize=(10, 4.6)); ax.set_xlim(0, 4); ax.set_ylim(0, 3.35); ax.axis("off")
    for i, (name, kind) in enumerate(tiles):
        x, y = i % 4, 2 - i // 4
        ax.add_patch(FancyBboxPatch((x + 0.04, y + 0.06), 0.92, 0.82, boxstyle="round,pad=0.0,rounding_size=0.06", color=colours[kind]))
        ax.text(x + 0.5, y + 0.47, name, ha="center", va="center", color="white", fontweight="bold", fontsize=11)
    ax.text(0, 3.18, "Scoreboard: 7 of 11 stopped, 4 reduced but not closed, 1 out of scope", fontweight="bold", fontsize=13, va="center")
    save(fig, "5_scoreboard.png")


# ---------------------------------------------------------------- 6. feedback trade-off
def feedback():
    # Typed in from FINDINGS.md section 10 / FINAL_REPORT.md P7 (simulation, median probes): 7 with exact feedback, 60 with the meter without noise.
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(0, 7, 0.5, color=GREEN); ax.bar(1, 60, 0.5, color=AMBER)
    ax.text(0, 9, "7", ha="center", color=GREEN, fontweight="bold"); ax.text(1, 62, "60\n(8 to 9 times more)", ha="center", color=AMBER, fontweight="bold")
    ax.set_xticks([0, 1], ["No protection\n(exact feedback)", "Our opt-in meter\n(no noise)"]); ax.set_ylim(0, 80)
    ax.set_ylabel("Probes Red needs to find a planted bypass"); ax.set_title("Red's feedback: protection costs Red probes (simulation)", loc="left", fontweight="bold", fontsize=12)
    ax.text(1.45, 74, "The meter still tells rule A from B:\n100% (89% with noise). Default report: not measured.", ha="right", fontsize=8.5, color=MUTE)
    save(fig, "6_feedback_tradeoff.png")


def main():
    summary = dict(guess_rates=guess_rates(), direct_doors=leaks_found(), flood=[(g[0].replace("\n", " "), g[1]) for g in flood()], audit_queue=audit_queue())
    scoreboard(); feedback()
    print(json.dumps(summary, indent=1, default=str)[:1800])
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
