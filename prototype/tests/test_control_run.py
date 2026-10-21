"""Real subprocess HTTP controls, plus disclosure and provenance checks. No API key."""
import asyncio
import json

from dashboard.control_run import run_controls
from dashboard.story import controls_projection


def test_controls_measure_file_http_restart_and_tamper_cases(tmp_path):
    path = tmp_path / "controls.json"
    value = asyncio.run(run_controls(path))
    assert value["status"] == "complete"
    v = value["vault"]
    assert v["plaintext_found"] and not v["ciphertext_found"]
    assert v["roundtrip"] and v["wrong_binding_denied"]
    assert v["plain_sizes"][0] != v["plain_sizes"][1]
    assert v["sealed_sizes"] == [32768, 32768]
    assert value["identity"] == dict(evaluator_records=2, red_pending=True, blue_pending=True, bad_token_pending=True)
    f = value["feedback"]
    assert f["true_count"] == 1
    assert f["safe_range"][0] <= f["true_count"] <= f["safe_range"][1]
    assert all(f[key] for key in ("before_pending", "repeat_equal", "third_pending", "restart_pending", "submissions_pending"))
    assert len(value["audit"]) == 8
    for row in value["audit"]:
        assert row["json_readable"]
        assert row["signed_valid"] == (row["case"] == "unmodified")
    assert "LOCAL_DEMO_PAYLOAD_" not in path.read_text()
    projected = controls_projection(tmp_path)
    assert projected["origin"] == "operator run" and len(projected["audit"]) == 8


def test_controls_projection_filters_secrets_and_does_not_fallback_after_failure(tmp_path):
    path = tmp_path / "controls.json"
    path.write_text(json.dumps(dict(status="complete", recorded_at=1, key="not-for-display",
        vault=dict(secret="not-for-display", plain_sizes="not-for-display"), feedback=dict(safe_range=[1,2]),
        identity=dict(token="not-for-display"), audit=[dict(case="unmodified", raw="not-for-display", signed_valid=True)])))
    assert "not-for-display" not in json.dumps(controls_projection(tmp_path))
    saved = tmp_path / "saved/evidence"
    saved.mkdir(parents=True)
    (saved / "controls-comparison.json").write_text(path.read_text())
    path.write_text('{"status":"failed","recorded_at":2}')
    projected = controls_projection(tmp_path, saved.parent)
    assert projected["status"] == "failed" and "vault" not in projected
    path.unlink()
    assert controls_projection(tmp_path, saved.parent)["origin"] == "saved evidence"
