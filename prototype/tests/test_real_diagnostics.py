"""PARAMS v6 diagnosis helpers and the generated real-model report: pure functions, synthetic data, no model and no processes."""
import json
import random
from types import SimpleNamespace

from eval import real_diagnostics as dx
from eval import real_report


def obs(total, started=1000.0):
    return dict(total=total, started_at=started)


def test_a_slip_with_gateway_side_lateness_and_a_loop_stall_is_attributed_to_the_gateway():
    observations = [obs(3.0, 1000.0), obs(3.1, 1010.0), obs(6.0, 1020.0)]
    trace = [dict(lateness=0.0), dict(lateness=0.01), dict(lateness=2.9)]
    lags = [dict(t=1023.0, lag=2.5, background=7, inflight=9, tasks=30)]  # stall ends at 1023, inside the slipped request (1020-1026)
    result = dx.slips(observations, trace, lags, 3.0)
    assert result["slipped_requests"] == 1 and result["server_side_late_over_0_25_s"] == 1 and result["slipped_overlapping_a_loop_lag_event"] == 1
    assert result["loop_lag"]["max_seconds"] == 2.5 and result["loop_lag"]["max_background_tasks"] == 7
    assert "gateway-side" in result["reading"]


def test_a_slip_without_gateway_lateness_or_stalls_is_attributed_outside_the_gateway():
    result = dx.slips([obs(3.0), obs(6.0)], [dict(lateness=0.0), dict(lateness=0.02)], [], 3.0)
    assert result["slipped_requests"] == 1 and result["server_side_late_over_0_25_s"] == 0
    assert "outside the gateway" in result["reading"]
    assert dx.slips([obs(3.0)], [], [], 3.0)["reading"] == "no request slipped"


def test_collect_reads_only_numeric_trace_fields_and_all_loop_lag_rows(tmp_path):
    worlds = []
    for index in (0, 1):
        data = tmp_path / f"world-{index}"
        data.mkdir()
        (data / "demo-trace.jsonl").write_text(json.dumps(dict(run_id="secret-run-id", blue_allowed=True, compute_seconds=0.2, model_answer="Dummy answer.",
                                                            scheduled_release_seconds=3.0, released_seconds=3.4)) + "\n" + "not json\n")
        (data / "loop-lag.jsonl").write_text(json.dumps(dict(t=1.0, lag=0.3, background=1, inflight=2, tasks=9)) + "\n")
        worlds.append(SimpleNamespace(config={"DATA_DIR": str(data)}))
    trace, lags = dx.collect(SimpleNamespace(worlds=worlds))
    assert len(trace) == 2 and abs(trace[0]["lateness"] - 0.4) < 1e-9 and len(lags) == 2
    assert "run_id" not in json.dumps(trace) and "Dummy" not in json.dumps(trace)


def rows(signal):
    rng = random.Random(5)
    out = []
    for split in ("train", "test"):
        for i in range(30):
            secret = i % 2
            out.append(dict(split=split, secret=secret, features=[secret + rng.random() * 0.1] if signal else [rng.random()]))
    return out


def test_permutation_check_finds_a_real_signal_and_not_noise():
    real = dx.permutation_check(rows(True), repetitions=100)
    noise = dx.permutation_check(rows(False), repetitions=100)
    assert real["observed_test_accuracy"] == 1.0 and real["two_sided_p"] < 0.05
    assert noise["two_sided_p"] > 0.05 and 0.3 < noise["null_mean"] < 0.7
    assert {"swapped_split_accuracy", "null_sd", "repetitions"} <= set(noise)


def test_report_is_generated_from_saved_files_and_marks_missing_parts_not_run(tmp_path):
    folder = tmp_path / "eval/output/real_overnight"
    (folder / "requests").mkdir(parents=True)
    cell = dict(cell="window_continue", cohort="ordinary", seed=1, policy="window_hard", window_continue=True, window_seconds=3.0, accuracy=0.4, train_accuracy=0.8,
                wilson_95=[0.3, 0.5], verdict="NO LEAK FOUND", release_seconds=dict(median=3.0, p95=3.1, p99=3.2, max=3.3), cancelled=0, late_after_deadline=0,
                audit=dict(valid=10, runs=10), permutation_check=dict(observed_test_accuracy=0.4, swapped_split_accuracy=0.6, null_mean=0.5, null_sd=0.06,
                                                                      two_sided_p=0.1, repetitions=500))
    (folder / "ordinary-s1-window_continue.json").write_text(json.dumps(cell))
    lines = [dict(role="timing", case=case, client=dict(total=total), evaluator=dict(blue_allowed=case == "allowed", backend="DeepSeek" if case == "allowed" else None,
                                                                                    usage=dict(completion_tokens=10), answer_chars=40 if case == "allowed" else None))
             for case, total in (("blocked", 3.0), ("allowed", 3.0), ("allowed", 6.2))]
    (folder / "requests/ordinary-s1-window_continue.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    text = real_report.build(tmp_path)
    assert "40.0% (30.0-50.0%)" in text and "NO LEAK FOUND" in text and "10/10 valid" in text
    assert "3 requests" in text and "| 50.0% |" in text  # one of the two allowed requests was later than W + 0.5 s
    assert "NOT RUN: no diagnostics file found." in text and "NOT RUN: no flood cell found." in text
    assert "0.1" in text and "completion tokens recorded: 30" in text
