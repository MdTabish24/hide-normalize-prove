import asyncio
from pathlib import Path
import secrets

from cryptography.exceptions import InvalidTag
import pytest

from vault import PayloadVault, RECORD_BYTES
from test_gateway import settings, client_for, configure, submit, auth, generic


def test_fixed_records_unicode_bindings_cover_reads_and_restart(tmp_path, monkeypatch):
    key = secrets.token_bytes(32)
    vault = PayloadVault(tmp_path, key)
    binding = dict(role="red", run_id="run-a", owner="identity-a", kind="prompt")
    reads = []
    original = vault.cover_read
    def cover():
        reads.append(1)
        original()
    monkeypatch.setattr(vault, "cover_read", cover)
    for text in ("small private prompt", "🔒"*4096):
        ref = vault.put(text, **binding)
        assert (tmp_path / (ref+".enc")).stat().st_size == RECORD_BYTES
        assert vault.get(ref, **binding) == text
        assert len(reads) % 2 == 0
        restarted = PayloadVault(tmp_path, key)
        assert restarted.get(ref, **binding) == text
        for field, value in (("role","blue"),("run_id","other"),("owner","other"),("kind","output")):
            with pytest.raises(InvalidTag):
                restarted.get(ref, **(binding | {field:value}))
    assert all(p.stat().st_size == RECORD_BYTES for p in tmp_path.glob("*.enc"))
    with pytest.raises(ValueError):
        vault.get("../outside", **binding)


def test_tampering_wrong_key_and_capacity_fail_closed(tmp_path):
    vault = PayloadVault(tmp_path, secrets.token_bytes(32))
    binding = dict(role="red", run_id="r", owner="o", kind="output")
    ref = vault.put({"answer":"private model output"}, **binding)
    with pytest.raises(InvalidTag):
        PayloadVault(tmp_path, secrets.token_bytes(32)).get(ref, **binding)
    path = tmp_path / (ref+".enc")
    blob = bytearray(path.read_bytes()); blob[100] ^= 1; path.write_bytes(blob)
    with pytest.raises(InvalidTag):
        vault.get(ref, **binding)
    with pytest.raises(ValueError):
        vault.put("x"*RECORD_BYTES, **binding)


def test_gateway_encrypts_both_sides_and_only_finished_evaluator_can_read(settings, tmp_path):
    prompt = "private-red-payload-9218"
    async def scenario():
        async with client_for(settings) as (app, client):
            await configure(client, settings)
            await submit(client, settings, prompt)
            endpoint = "/v1/run/test-run/artifacts"
            generic(await client.get(endpoint, headers=auth(settings,"evaluator")))
            await client.post("/v1/run/test-run/finish", headers=auth(settings,"evaluator"))
            for role in ("red","blue"):
                generic(await client.get(endpoint, headers=auth(settings,role)))
            result = await client.get(endpoint, headers=auth(settings,"evaluator"))
            assert result.json()["records"] == [{"prompt":prompt,"output":{"answer":"Dummy answer."},"blue_allowed":True,"cancelled":False}]
            with pytest.raises(PermissionError):
                app.state.store.completed_payloads("test-run", "different-identity")
        # Reopen a fresh gateway, preserving the key and encrypted records.
        async with client_for(settings) as (_, client):
            assert (await client.get(endpoint,headers=auth(settings,"evaluator"))).json() == result.json()
    asyncio.run(scenario())
    assert (tmp_path/"defense.enc").stat().st_size == RECORD_BYTES
    assert len(list((tmp_path/"vault").glob("*.enc"))) == 3  # cover, prompt, output
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content=path.read_bytes()
            assert prompt.encode() not in content and b"pineapple" not in content and b"Dummy answer." not in content


def test_legacy_blue_config_migrates_without_key_rotation(tmp_path):
    import json
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from storage import Store
    key, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    (tmp_path/"defense.enc").write_bytes(nonce+AESGCM(key).encrypt(nonce,json.dumps({"trigger":"pineapple"}).encode(),b"blue-defense-v1"))
    store=Store(tmp_path,key)
    assert store.unseal() == {"trigger":"pineapple"}
    assert (tmp_path/"defense.enc").stat().st_size == RECORD_BYTES


@pytest.mark.timing
def test_slow_prompt_storage_does_not_block_release_loop(settings, monkeypatch):
    import time
    config=dict(settings,POLICY_MODE="window_hard",WINDOW_SECONDS="0.3")
    async def scenario():
        async with client_for(config) as (app,client):
            await configure(client,config)
            original=app.state.store.save_prompt
            def slow(*args):
                time.sleep(.5)
                return original(*args)
            monkeypatch.setattr(app.state.store,"save_prompt",slow)
            start=time.perf_counter()
            generic((await submit(client,config))[0])
            assert .29 <= time.perf_counter()-start < .45
            with app.state.store.connect() as db:
                assert db.execute('SELECT cancelled,blue_allowed FROM attempts').fetchone()==(1,None)
    asyncio.run(scenario())


def test_concurrent_vault_commits_publish_complete_records(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from storage import Store
    store=Store(tmp_path,secrets.token_bytes(32))
    def work(index):
        attempt=store.begin('parallel','owner')
        prompt=f'private parallel fixture {index}'
        assert store.save_prompt(attempt,'parallel','owner',prompt)==prompt
        ref=store.seal_output('parallel','owner',{'answer':str(index)})
        store.end(attempt,True,blue_allowed=True,output_ref=ref)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(work,range(8)))
    assert store.finish('parallel')
    rows=store.completed_payloads('parallel','owner')
    assert len(rows)==8 and {r['output']['answer'] for r in rows}=={str(i) for i in range(8)}
    assert all(r['blue_allowed'] is True for r in rows)
