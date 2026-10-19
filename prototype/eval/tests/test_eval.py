import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import time

import httpx

import gateway
import model
import storage
from eval import feedback
from eval.feedback import probes, seed_simulated_run
from eval.run import evaluate, features
from storage import Store


def test_production_generator_identity_and_default_budget(tmp_path):
    assert feedback.generate_range is gateway.generate_range is storage.generate_range
    store = Store(tmp_path, secrets.token_bytes(32))
    assert store.range_seed_mode == "run" and store.range_generator is gateway.generate_range
    seed_simulated_run(store, "r", probes(1, 16), 16)
    first = store.report("r", "simulated-red")
    assert first == store.report("r", "simulated-red")
    assert store.report("r", "simulated-red") is None


def test_monte_carlo_actually_calls_gateway_production_generator(monkeypatch):
    production = gateway.generate_range
    calls = []
    def traced(*args, **kwargs):
        calls.append(kwargs["mode"])
        return production(*args, **kwargs)
    monkeypatch.setattr(feedback, "generate_range", traced)
    feedback.monte_carlo(sets=2, seed=7391)
    assert calls.count("run") == 60 and calls.count("probeset") == 60


def test_probeset_same_across_runs_reorder_and_varies_for_changed_sets(tmp_path):
    store = Store(tmp_path, secrets.token_bytes(32), range_seed_mode="probeset")
    prompt_set = probes(1, 16)
    responses = []
    for index, items in enumerate((prompt_set, prompt_set, list(reversed(prompt_set)))):
        seed_simulated_run(store, f"same-{index}", items, 16)
        responses.append(json.loads(store.report(f"same-{index}", "simulated-red"))["safe_range"])
    assert responses[0] == responses[1] == responses[2]
    changed = []
    for index in range(16):
        seed_simulated_run(store, f"different-{index}", probes(100 + index, 16), 16)
        changed.append(tuple(json.loads(store.report(f"different-{index}", "simulated-red"))["safe_range"]))
    assert len(set(changed)) > 1  # Finite ranges can collide; never require uniqueness.


def test_model_hook_ignored_off_enabled_only_explicitly(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "test-model-service-token")
    monkeypatch.setenv("MISS_SECONDS", "0.002")
    monkeypatch.setenv("HIT_SECONDS", "0.002")
    monkeypatch.setenv("JITTER_SECONDS", "0")
    monkeypatch.delenv("EVAL_MODE", raising=False)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=model.app), base_url="http://model") as client:
            body = {"prompt": "hint", "run_id": "hook", "role": "red", "sim_delay": 2.0}
            headers = {"authorization": "Bearer test-model-service-token"}
            start = time.perf_counter()
            assert (await client.post("/generate", json=body, headers=headers)).status_code == 200
            assert time.perf_counter() - start < 0.3
            monkeypatch.setenv("EVAL_MODE", "1")
            body["sim_delay"] = 0.08
            start = time.perf_counter()
            assert (await client.post("/generate", json=body, headers=headers)).status_code == 200
            assert time.perf_counter() - start >= 0.07
    asyncio.run(scenario())


def test_gateway_ignores_hook_without_eval_and_never_exposes_key(tmp_path, capsys):
    config = {name: secrets.token_hex(32) for name in (
        "RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN", "GATEWAY_KEY", "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN")}
    config.update(DATA_DIR=str(tmp_path), BUCKETS="0.03,0.06,0.09", RANGE_SEED_MODE="probeset")
    sent = []
    async def dispatch(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"allowed": True} if request.url.host == "blue-defense" else {"answer": "dummy"})
    app = gateway.create_app(config, httpx.MockTransport(dispatch))
    async def scenario():
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            def auth(role):
                return {"authorization": "Bearer " + config[role + "_TOKEN"]}
            responses = [await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=auth("BLUE"))]
            responses.append(await client.post("/v1/submit", json={"run_id": "r", "prompt": "hello", "sim_delay": 10}, headers=auth("RED")))
            responses.append(await client.post("/v1/run/r/finish", headers=auth("EVALUATOR")))
            responses.append(await client.get("/v1/run/r/report", headers=auth("RED")))
            assert all(len(response.content) == 64 for response in responses)
            assert all("sim_delay" not in body for body in sent)
            assert all(config["GATEWAY_KEY"] not in response.text for response in responses)
    asyncio.run(scenario())
    assert config["GATEWAY_KEY"] not in capsys.readouterr().out


def test_feature_function_cannot_receive_labels():
    row = {"total": 0.1, "ttfb": 0.09, "status": 202, "body_length": 64,
           "header_fingerprint": hashlib.sha256(b"headers").hexdigest()}
    expected = features([row] * 6, [0.3, 0.6, 0.9])
    assert features([dict(row, secret="B", run_id="private-label")] * 6, [0.3, 0.6, 0.9]) == expected


def test_tiny_live_http_full_harness(tmp_path):
    data = asyncio.run(evaluate(tmp_path, n=2, train_n=2, scale=0.02, concurrency=1,
                                mc_sets=2, live_sets=2, audit=False))
    assert len(data["timing"]) == 9
    for cell in data["timing"]:
        assert cell["test_runs"] == 2 and cell["requests_per_run"] == 6
        assert len({r["run_id"] for r in cell["samples"]}) == 4
        if cell["cohort"] == "overflow" and cell["policy"] in {"raw", "bucket"}:
            assert max(o["total"] for r in cell["samples"] for o in r["observations"]) > data["buckets"][-1]
    for name in ("results.json", "results_table.md", "leakage_matrix.png", "feedback_error.png"):
        assert (tmp_path / name).stat().st_size > 0
