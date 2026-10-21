"""Feedback meter: hysteresis, batching, idempotence, persistent budgets, identical envelopes, no exact baseline in service."""
import asyncio

import pytest

from common import HEADERS, PENDING
from gateway import create_app
from meter import Params, STATES, batch_digest, transition
from storage import Store
from test_gateway import auth, client_for, configure, generic, settings, submit  # noqa: F401 (fixture)

KEY = bytes(range(32))


def store_for(directory):
    return Store(directory, KEY)


def add_batch(store, run_id, owner, size, safe, tag):
    """Record `size` finished attempts with the given outcome and distinct probe hashes."""
    for i in range(size):
        attempt = store.begin(run_id, owner, f"{tag}-{i}", "v1")
        store.end(attempt, bool(safe))


def log(store, run_id):
    with store.connect() as db:
        rows = db.execute("SELECT batch, score, true_state, published, reused FROM meter_log WHERE run_id=? ORDER BY batch",
                          (run_id,)).fetchall()
    return [(b, s, t, p, bool(r)) for b, s, t, p, r in rows]


def test_hysteresis_small_changes_do_not_flip_and_the_inner_band_re_centres():
    p = Params()
    state, ref = "STABLE", 0.5
    for score in (0.6, 0.4, 0.7, 0.3, 0.55):  # all inside +/-0.30 of the reference
        state, ref = transition(state, ref, score, p)
        assert (state, ref) == ("STABLE", 0.5)
    assert transition("STABLE", 0.5, 0.8, p) == ("IMPROVING", 0.8)
    assert transition("STABLE", 0.5, 0.2, p) == ("LOW", 0.2)
    assert transition("IMPROVING", 0.8, 0.95, p) == ("IMPROVING", 0.8)   # not back in the inner band: stays
    assert transition("IMPROVING", 0.8, 0.85, p) == ("STABLE", 0.85)     # inside the inner band: returns
    assert transition("IMPROVING", 0.8, 0.5, p) == ("LOW", 0.5)
    assert transition("LOW", 0.2, 0.25, p) == ("STABLE", 0.25)


def test_params_validation():
    for bad in (dict(batch=1), dict(inner=0.5), dict(noise_q=0.9), dict(delta_up=0)):
        with pytest.raises(ValueError):
            Params(**bad)


def test_state_is_unchanged_inside_a_batch_and_only_completed_batches_publish(tmp_path):
    store, p = store_for(tmp_path), Params(batch=5)
    add_batch(store, "r", "o", 4, True, "a")
    store.meter_update("r", "o", p, KEY)
    assert log(store, "r") == [] and store.meter_read("o", "r", p) == "STABLE"
    attempt = store.begin("r", "o", "pending", "v1")  # 5th attempt exists but is not done yet
    store.meter_update("r", "o", p, KEY)
    assert log(store, "r") == []
    store.end(attempt, True)
    store.meter_update("r", "o", p, KEY)
    store.meter_update("r", "o", p, KEY)  # idempotent
    assert log(store, "r") == [(0, 1.0, "STABLE", "STABLE", False)]


def test_same_batch_content_publishes_the_same_state_and_does_not_move_the_reference(tmp_path):
    store, p = store_for(tmp_path), Params(batch=4)
    add_batch(store, "a", "o", 4, False, "x")   # reference 0.0, STABLE
    add_batch(store, "a", "o", 4, True, "y")    # score 1.0 -> IMPROVING
    store.meter_update("a", "o", p, KEY)
    assert [row[3] for row in log(store, "a")] == ["STABLE", "IMPROVING"]
    add_batch(store, "b", "o", 4, True, "y")    # identical content to run a's second batch, now as a first batch
    store.meter_update("b", "o", p, KEY)
    assert log(store, "b") == [(0, 1.0, "STABLE", "IMPROVING", True)]  # cached state; chain untouched
    assert batch_digest(KEY, [("h1", 1), ("h2", 0)]) == batch_digest(KEY, [("h2", 0), ("h1", 1)])


def test_noise_arm_is_keyed_to_the_batch_so_repeating_cannot_average_it(tmp_path):
    p = Params(batch=4, noise_q=0.5)
    shown = set()
    for run in range(6):
        store = store_for(tmp_path / f"s{run}")
        add_batch(store, "r", "o", 4, True, "same")  # identical content every time
        store.meter_update("r", "o", p, KEY)
        shown.add(log(store, "r")[0][3])
    assert len(shown) == 1


def test_budgets_persist_across_restart_and_beyond_budget_repeats_the_last_returned_state(tmp_path):
    p = Params(batch=3, reads_per_run=3, reads_total=4)
    store = store_for(tmp_path)
    add_batch(store, "r1", "o", 3, False, "a")
    add_batch(store, "r1", "o", 3, True, "b")
    store.meter_update("r1", "o", p, KEY)
    assert [store.meter_read("o", "r1", p) for _ in range(3)] == ["IMPROVING"] * 3
    add_batch(store, "r1", "o", 3, False, "c")      # real state becomes LOW
    store.meter_update("r1", "o", p, KEY)
    assert store.meter_read("o", "r1", p) == "IMPROVING"  # per-run budget spent: same last returned state
    restarted = store_for(tmp_path)                       # budget lives in SQLite, so a restart does not reset it
    assert restarted.meter_read("o", "r1", p) == "IMPROVING"
    add_batch(restarted, "r2", "o", 3, False, "d")
    add_batch(restarted, "r2", "o", 3, True, "e")
    restarted.meter_update("r2", "o", p, KEY)
    assert restarted.meter_read("o", "r2", p) == "IMPROVING"  # 4th read overall is still inside the total of 4
    add_batch(restarted, "r2", "o", 3, False, "f")
    restarted.meter_update("r2", "o", p, KEY)
    assert restarted.meter_read("o", "r2", p) == "IMPROVING"  # total spent: frozen again, never "LOW"
    assert restarted.meter_read("other", "r2", p) in STATES   # another identity has its own budget


def test_one_probe_changing_does_not_change_the_published_state(tmp_path):
    p, outcomes = Params(batch=10), []
    for tag, second in (("w1", 5), ("w2", 6)):  # batch 2 differs by exactly one probe outcome
        store = store_for(tmp_path / tag)
        add_batch(store, "r", "o", 10, True, "first")
        for i in range(10):
            store.end(store.begin("r", "o", f"{tag}-{i}", "v1"), i < second)
        store.meter_update("r", "o", p, KEY)
        outcomes.append(log(store, "r")[1][3])
    assert outcomes[0] == outcomes[1] and outcomes[0] in STATES


def feedback_settings(settings, mode, **extra):
    return dict(settings, FEEDBACK_MODE=mode, **extra)


def test_every_mode_returns_the_same_envelope_and_exact_is_not_reachable_without_eval_mode(settings):
    async def scenario(config):
        async with client_for(config) as (app, client):
            await configure(client, config)
            await submit(client, config, "hello", "r")
            response = await client.get("/v1/run/r/feedback", headers=auth(config, "red"))
            assert response.status_code == 202 and dict(response.headers) == HEADERS and len(response.content) == 64
            return response.content

    assert asyncio.run(scenario(feedback_settings(settings, "none"))) == PENDING
    meter = asyncio.run(scenario(feedback_settings(settings, "meter", METER_BATCH="2")))
    assert meter.strip() == b'{"meter":"STABLE"}'
    # exact without EVAL_MODE=1 is ignored (treated as none): no per-prompt pass/fail can be requested in service.
    assert asyncio.run(scenario(feedback_settings(settings, "exact"))) == PENDING
    exact = asyncio.run(scenario(feedback_settings(settings, "exact", EVAL_MODE="1")))
    assert exact.strip() == b'{"exact":true}'


def test_invalid_feedback_mode_is_rejected(settings):
    with pytest.raises(ValueError):
        create_app(feedback_settings(settings, "everything"))


def test_gateway_meter_end_to_end_with_evaluator_only_true_scores(settings):
    config = feedback_settings(settings, "meter", METER_BATCH="2", METER_READS_PER_RUN="2", METER_READS_TOTAL="2")

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            red = auth(config, "red")
            for prompt in ("hello a", "hello b", "pineapple a", "pineapple b"):  # batch 1 allowed, batch 2 blocked
                response, _ = await submit(client, config, prompt, "m")
                generic(response)
            await asyncio.sleep(0.4)  # the worker thread publishes after the responses were already released
            first = (await client.get("/v1/run/m/feedback", headers=red)).content.strip()
            second = (await client.get("/v1/run/m/feedback", headers=red)).content.strip()
            third = (await client.get("/v1/run/m/feedback", headers=red)).content.strip()  # over budget
            assert (first, second) == (b'{"meter":"LOW"}', b'{"meter":"LOW"}') and third == second
            await client.post("/v1/run/m/finish", headers=auth(config, "evaluator"))
            truth = await client.get("/v1/run/m/meter-evaluation", headers=auth(config, "evaluator"))
            data = truth.json()
            assert [b["score"] for b in data["batches"]] == [1.0, 0.0]
            assert [b["published"] for b in data["batches"]] == ["STABLE", "LOW"] and data["reads"] == 2
            generic(await client.get("/v1/run/m/meter-evaluation", headers=red))  # Red cannot read the truth
    asyncio.run(scenario())
