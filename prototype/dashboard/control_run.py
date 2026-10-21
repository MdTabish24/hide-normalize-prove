"""Measured control comparisons on temporary dummy data; no insecure service mode.

Plaintext files, JSON-only audit reading and evaluator-only exact counts are
explicit diagnostic baselines, NOT an unprotected Docker deployment.
"""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import tempfile
import time
import uuid

from .recording import atomic_json


def vault_comparison(directory):
    from cryptography.exceptions import InvalidTag
    from vault import PayloadVault
    directory = Path(directory)
    vault = PayloadVault(directory / "sealed", secrets.token_bytes(32))
    marker = "LOCAL_DEMO_PAYLOAD_" + secrets.token_hex(12)
    values = [marker, marker + " extended dummy text" * 30]
    binding = dict(role="red", run_id="control-demo", owner="red", kind="prompt")
    plain_sizes, sealed_sizes = [], []
    plaintext_found, sealed_found, roundtrip, wrong_binding_denied = [], [], [], []
    for index, value in enumerate(values):
        plain = directory / f"plain-{index}.json"
        plain.write_text(json.dumps(value), encoding="utf-8")
        ref = vault.put(value, **binding)
        encrypted = (vault.directory / (ref + ".enc")).read_bytes()
        plain_sizes.append(plain.stat().st_size)
        sealed_sizes.append(len(encrypted))
        plaintext_found.append(marker.encode() in plain.read_bytes())
        sealed_found.append(marker.encode() in encrypted)
        roundtrip.append(vault.get(ref, **binding) == value)
        try:
            vault.get(ref, **dict(binding, owner="another-owner"))
        except InvalidTag:
            wrong_binding_denied.append(True)
        else:
            wrong_binding_denied.append(False)
    return dict(plain_sizes=plain_sizes, sealed_sizes=sealed_sizes,
                plaintext_found=all(plaintext_found), ciphertext_found=any(sealed_found),
                roundtrip=all(roundtrip), wrong_binding_denied=all(wrong_binding_denied))


def audit_comparison(directory, log, checkpoint, public_key, run_id):
    from demo_audit_tamper import tamper_cases
    from verify_audit import verify
    directory = Path(directory)
    directory.mkdir(parents=True)
    result = []
    for name, (data, proof) in tamper_cases(Path(log).read_bytes(), Path(checkpoint).read_bytes()).items():
        # Baseline deliberately reads JSON only: no chain, signature or trusted
        # expected count. It demonstrates what plain log consumption can miss.
        try:
            baseline = bool([json.loads(row) for row in data.splitlines()])
        except ValueError:
            baseline = False
        copied_log, copied_proof = directory / "copy.jsonl", directory / "checkpoint.json"
        copied_log.write_bytes(data)
        copied_proof.write_bytes(proof)
        valid, _, index = verify(copied_log, copied_proof, public_key, run_id)
        result.append(dict(case=name, json_readable=baseline, signed_valid=valid, failing_index=index))
    return result


async def run_controls(path):
    from common import HEADERS, PENDING
    from eval.live import Lab
    path = Path(path)
    state = dict(recorded_at=time.time(), status="running", vault={}, identity={}, feedback={}, audit=[],
                 label="Measured local controls; mock backend; diagnostic baselines")

    def save():
        if not atomic_json(path, state):
            raise RuntimeError("Control artifact unavailable")

    def pending(response):
        return response.status_code == 202 and response.content == PENDING and dict(response.headers) == HEADERS

    save()
    try:
        with tempfile.TemporaryDirectory(prefix="hnp-controls-") as directory:
            root = Path(directory)
            state["vault"] = vault_comparison(root)
            save()
            async with Lab(root / "http", scale=.1, policy="bucket_hard", audit=True) as lab:
                world = lab.worlds[0]
                rid = "controls-" + uuid.uuid4().hex
                report_url = f"/v1/run/{rid}/report"
                before = await world.client.get(report_url, headers=world.auth("red"))
                responses = []
                for prompt in ("pineapple orchard", "neutral orchard"):
                    responses.append(await world.client.post("/v1/submit", headers=world.auth("red"),
                                                           json=dict(run_id=rid, prompt=prompt)))
                await world.finish(rid)
                evaluation = await world.client.get(f"/v1/run/{rid}/evaluation", headers=world.auth("evaluator"))
                count = evaluation.json().get("safe")
                if type(count) is not int:
                    raise RuntimeError("Evaluator count missing")
                private_url = f"/v1/run/{rid}/artifacts"
                evaluator = await world.client.get(private_url, headers=world.auth("evaluator"))
                red = await world.client.get(private_url, headers=world.auth("red"))
                blue = await world.client.get(private_url, headers=world.auth("blue"))
                bad = await world.client.get(private_url, headers={"authorization": "Bearer invalid-demo-token"})
                artifacts = evaluator.json().get("records")
                state["identity"] = dict(evaluator_records=len(artifacts) if isinstance(artifacts, list) else None,
                    red_pending=pending(red), blue_pending=pending(blue), bad_token_pending=pending(bad))
                reports = [await world.report(rid) for _ in range(3)]
                first_range = reports[0].get("safe_range")
                state["feedback"] = dict(true_count=count, safe_range=first_range,
                    before_pending=pending(before), repeat_equal=reports[0] == reports[1],
                    third_pending=reports[2].get("status") == "pending",
                    submissions_pending=all(pending(r) for r in responses))
                # A fourth read after actual process restart must still be withheld.
                world = await lab.restart_gateway(0)
                state["feedback"]["restart_pending"] = pending(await world.client.get(report_url, headers=world.auth("red")))
                checked = await lab.audit_check({0: [rid]}, drain_seconds=5)
                if checked["valid"] != 1:
                    raise RuntimeError("Source audit did not verify")
                base = root / "http"
                state["audit"] = audit_comparison(root / "tamper", base / f"audit-logs-0/{rid}.jsonl",
                    base / f"checkpoints-0/{rid}.json", base / "checkpoints-0/public_key.bin", rid)
                save()
        state["status"] = "complete"
        save()
    except BaseException:
        state["status"] = "failed"
        save()
        raise
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "runtime/observations/controls.json")
    result = asyncio.run(run_controls(parser.parse_args().output))
    print(json.dumps(result, indent=2))
