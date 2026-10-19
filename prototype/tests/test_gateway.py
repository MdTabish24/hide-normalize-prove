"""Real ASGI requests, sleeps, AES and SQLite; no model API or Docker required."""
import asyncio
from contextlib import asynccontextmanager
import json
import secrets
import time

import httpx
import pytest

import blue
import model
from common import HEADERS, PENDING
from gateway import create_app


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "private-service-token-for-tests")
    monkeypatch.setenv("HIT_SECONDS", "0.006")
    monkeypatch.setenv("MISS_SECONDS", "0.04")
    monkeypatch.setenv("JITTER_SECONDS", "0")
    model.cache.clear()
    return {"RED_TOKEN": secrets.token_hex(16), "BLUE_TOKEN": secrets.token_hex(16),
            "EVALUATOR_TOKEN": secrets.token_hex(16), "GATEWAY_KEY": secrets.token_hex(32),
            "BLUE_SERVICE_TOKEN": "private-service-token-for-tests",
            "MODEL_SERVICE_TOKEN": "private-service-token-for-tests",
            "DATA_DIR": str(tmp_path), "BUCKETS": "0.15,0.3,0.45"}


def auth(settings, role):
    return {"authorization": "Bearer " + settings[role.upper() + "_TOKEN"]}


@asynccontextmanager
async def client_for(settings, calls=None, fail=False):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=blue.app)) as blue_client, \
            httpx.AsyncClient(transport=httpx.ASGITransport(app=model.app)) as model_client:
        async def dispatch(request):
            if fail:
                raise RuntimeError("Private error text must never reach Red")
            if calls is not None:
                calls.append((request.url.host, json.loads(request.content)))
            client = blue_client if request.url.host == "blue-defense" else model_client
            return await client.post(str(request.url), content=request.content, headers=request.headers)

        app = create_app(settings, httpx.MockTransport(dispatch))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield app, client


async def configure(client, settings):
    return await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=auth(settings, "blue"))


async def submit(client, settings, prompt="hello", run_id="test-run"):
    start = time.perf_counter()
    response = await client.post("/v1/submit", json={"run_id": run_id, "prompt": prompt}, headers=auth(settings, "red"))
    return response, time.perf_counter() - start


def generic(response):
    assert response.status_code == 202
    assert response.content == PENDING
    assert len(response.content) == 64
    assert dict(response.headers) == HEADERS


@pytest.mark.timing
def test_envelope_and_first_bucket_for_blocked_allowed_hit_miss(settings):
    async def scenario():
        async with client_for(settings) as (_, client):
            await configure(client, settings)
            # First allowed call is a miss; the exact repeat is a cache hit.
            for prompt in ("hello", "hello", "pineapple"):
                response, elapsed = await submit(client, settings, prompt)
                generic(response)
                assert 0.145 <= elapsed < 0.26
            bad = await client.post("/v1/submit", json={"run_id": "r", "prompt": "hello"}, headers={"authorization": "Bearer bad"})
            wrong = await client.post("/v1/defense", json={"trigger": "hello"}, headers=auth(settings, "red"))
            generic(bad)
            generic(wrong)
    asyncio.run(scenario())


@pytest.mark.timing
def test_errors_use_same_fixed_last_bucket(settings):
    async def scenario():
        async with client_for(settings, fail=True) as (_, client):
            await configure(client, settings)
            requests = [
                ("GET", "/unknown", {}),
                ("POST", "/v1/submit", {"json": {}, "headers": auth(settings, "red")}),
                ("POST", "/v1/submit", {"json": {"run_id": "r", "prompt": "hi"}, "headers": auth(settings, "red")}),
                ("POST", "/v1/defense", {"json": {"trigger": "hi"}, "headers": auth(settings, "red")}),
            ]
            for method, path, kwargs in requests:
                start = time.perf_counter()
                generic(await client.request(method, path, **kwargs))
                assert 0.44 <= time.perf_counter() - start < 0.6
    asyncio.run(scenario())


def test_report_memoization_budget_and_actual_app_restart(settings):
    async def scenario():
        async with client_for(settings) as (_, client):
            await configure(client, settings)
            await submit(client, settings)
            generic(await client.get("/v1/run/test-run/report", headers=auth(settings, "red")))
            await client.post("/v1/run/test-run/finish", headers=auth(settings, "red"))
            generic(await client.get("/v1/run/test-run/report", headers=auth(settings, "red")))
            await client.post("/v1/run/test-run/finish", headers=auth(settings, "evaluator"))
            first = await client.get("/v1/run/test-run/report", headers=auth(settings, "red"))
            assert first.json() == {"status": "complete", "safe_range": [0, 1]}
        # New app, new Store/SQLite connection and new HTTP client, same disk/key.
        async with client_for(settings) as (_, client):
            second = await client.get("/v1/run/test-run/report", headers=auth(settings, "red"))
            assert second.content == first.content
            generic(await client.get("/v1/run/test-run/report", headers=auth(settings, "red")))
        async with client_for(settings) as (_, client):
            generic(await client.get("/v1/run/test-run/report", headers=auth(settings, "red")))
    asyncio.run(scenario())


def test_defense_encrypted_at_rest_and_loaded_after_restart(settings, tmp_path):
    async def scenario():
        async with client_for(settings) as (_, client):
            await configure(client, settings)
        encrypted = (tmp_path / "defense.enc").read_bytes()
        assert b"pineapple" not in encrypted and b"trigger" not in encrypted
        calls = []
        async with client_for(settings, calls) as (app, client):
            assert app.state.defense == {"trigger": "pineapple"}
            await submit(client, settings, "pineapple")
            assert not any(host == "model-mock" for host, _ in calls)
        changed = dict(settings, GATEWAY_KEY=secrets.token_hex(32))
        with pytest.raises(Exception):
            create_app(changed)
    asyncio.run(scenario())


@pytest.mark.timing
def test_hard_timeout_same_envelope_and_count_finishes(settings, monkeypatch):
    monkeypatch.setenv("MISS_SECONDS", "0.9")
    async def scenario():
        async with client_for(settings) as (app, client):
            await configure(client, settings)
            response, elapsed = await submit(client, settings)
            generic(response)
            assert 0.44 <= elapsed < 0.6
            with app.state.store.connect() as db:
                assert db.execute("SELECT done FROM attempts").fetchone() == (1,)
            assert not model.cache  # In-process backend sleep was cancelled.
    asyncio.run(scenario())


def test_role_is_derived_only_from_token(settings):
    async def scenario():
        async with client_for(settings) as (app, client):
            response = await client.post("/v1/defense", json={"trigger": "pineapple", "role": "blue"}, headers=auth(settings, "red"))
            generic(response)
            assert app.state.defense is None
            response = await client.post("/v1/submit", json={"prompt": "hello", "run_id": "r"}, headers=auth(settings, "blue"))
            generic(response)
            with app.state.store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM attempts").fetchone() == (0,)
    asyncio.run(scenario())


@pytest.mark.timing
def test_cache_miss_hit_and_role_run_namespace(settings):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=model.app), base_url="http://model-mock") as client:
            elapsed = []
            for role, run in (("red", "a"), ("red", "a"), ("blue", "a"), ("red", "b")):
                start = time.perf_counter()
                result = await client.post("/generate", json={"role": role, "run_id": run, "prompt": "same-prefix"},
                                           headers={"authorization": "Bearer private-service-token-for-tests"})
                assert result.json() == {"answer": "Dummy answer."}
                elapsed.append(time.perf_counter() - start)
            assert elapsed[1] < 0.03
            assert all(elapsed[i] >= 0.035 for i in (0, 2, 3))
    asyncio.run(scenario())


def test_logs_contain_metadata_only(settings, capsys):
    async def scenario():
        async with client_for(settings) as (_, client):
            await configure(client, settings)
            await submit(client, settings, "private payload pineapple")
    asyncio.run(scenario())
    output = capsys.readouterr().out
    assert "pineapple" not in output and "private payload" not in output
    assert all(token not in output for key, token in settings.items() if key.endswith("TOKEN"))
    for line in output.splitlines():
        assert set(json.loads(line)) == {"event", "run_id", "role", "bucket", "timestamp", "prompt_hash"}
