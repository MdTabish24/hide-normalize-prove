# Hide, Normalize, Prove

A local proof of concept for Bayora's **Securing Adversarial AI Safety Testing
Infrastructure** challenge. We test whether shared observations expose a
defender's secret, then measure how gateway policies change those observations.

This repository contains a simulated control demo and saved evidence from a
small real DeepSeek model run. It does not implement a deployed sandbox.

## Two-minute local demo

```powershell
python -m pip install -r requirements.txt
python experiment.py
python verify_audit.py
python verify_audit.py --log demo_audit/edited.jsonl
python -m unittest test_experiment.py
```

The original recorded audit is `AUDIT VALID`. An edited line, deleted tail,
reordered records or changed checkpoint count returns `AUDIT INVALID`.
`INVALID` exits with code 1 intentionally. The signing private key is ephemeral
and never committed. Public key/checkpoint files are local demonstration fixtures,
not an independently protected witness.

To edit a line yourself without changing the original:

```powershell
$demoText = Get-Content -LiteralPath demo_audit/events.jsonl -Raw
$demoText.Replace('pending', 'changed') | Set-Content -LiteralPath demo_audit/manual_edit.jsonl -Encoding utf8
python verify_audit.py --log demo_audit/manual_edit.jsonl
```

The simulation makes no API calls. Rerunning it refreshes local audit fixtures
and heuristic ranges. Timing datasets/classifier results use fixed seeds.

## Timing evidence

**Simulated, local PoC. 200 unseen runs per case, separate training runs.**

| Case | Raw accuracy | Bucketed accuracy |
|---|---:|---:|
| Ordinary | 100% | 50% |
| 3s boundary | 93% | 95% |
| Above 9s | 100% | 100% |

An additional simulated overflow comparison releases every late observation
at exactly 9s with the same generic envelope. Its unseen accuracy is **50%**,
but **100% of this overflow cohort times out**. This is a deadline model,
not a real inference cancellation implementation. The 256 output-token cap
does not establish a wall-clock runtime bound. Boundary leakage remains.

## Real-model evidence

**Real model run, small sample (DeepSeek), n=150 latency / n=20 extraction.**
Model: `deepseek-flash`. p50/p95/p99: 1.18/1.64/2.12s. Offline bucket padding
adds 1.82s on average. 149 releases map to 3s and one to 6s, overrun 0.7%.
Exact-canary scan: 0/20 disclosures. Rule keywords: 2/20 raw outputs versus
0/20 gateway, zero by design because the gateway withholds free text.

No secret A/B or cache hit/miss labels exist for the real latency sample.
Do not treat the simulated classifier results as production security guarantees.

## Optional real experiment

```powershell
$env:DEEPSEEK_API_KEY = "YOUR_KEY_IN_YOUR_TERMINAL"
python experiment_real.py
```

This makes 150 logical paid API requests, with at most 170 calls including
retries, and overwrites the four real-result artifacts after a complete run.
Never commit or share keys. API base URL: `https://api.deepseek.com`.

To rescan saved outputs without any API calls:

```powershell
python experiment_real.py --reanalyze-leaks
```

## Implemented locally

- Constant pending envelope and end-of-test asymmetric range feedback.
- Memoized repeat-batch reports and SQLite identity/defense-version budget.
- Mock cache session reset and role/run namespaces.
- Hash-chained events and Ed25519-signed count/length/head checkpoint.
- Run-wise train/test split, uncertainty and separately labeled pooled diagnostic.

## Remaining limitations

Ranges are heuristic protection, not formal differential privacy. Narrow ranges
still distinguish extreme counts and related adaptive queries can leak.
Actual-time overflow exposes timing. A fixed deadline does not protect mixed
completion/timeout signals or bucket-boundary probes. Hosted DeepSeek KV reset
is unavailable to this client. Vault, workload identity, live HTTP scheduling,
real KV controls and an independent witness remain deployment work. A valid
audit chain establishes recorded integrity, not completeness or universal safety.

See [DESIGN_NOTES.md](DESIGN_NOTES.md) for scope and all decisions.
The submission deck is [output/final_presentation.pptx](output/final_presentation.pptx).
