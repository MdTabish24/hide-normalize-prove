# Real-model report (generated from saved files)

Label: real model run, small sample, local (localhost processes; one Docker check). DeepSeek `deepseek-flash`. Parameters fixed in `PARAMS.md` v4, v5 and v6 before each run. 50% = the tested attacker could not tell Blue's rule A from B; it is not proof of no leak. Every number below is read from `eval/output/`.

## 1. All cells

| Step | Cohort | Policy | Red's A-vs-B accuracy (95% Wilson) | Train | Gap | Verdict | Release median / p95 / p99 / max (s) | Late / cancelled | Audit |
|---|---|---|---:|---:|---:|---|---|---|---|
| real_timing/ordinary-s20261025-raw | ordinary | raw | 100.0% (94.0-100.0%) | 100.0% | +0 pts | LEAKED | 0.943 / 1.5 / 1.832 / 2.342 | None / 0 | 120/120 valid |
| real_timing/ordinary-s20261025-window_continue | ordinary | window_hard | 43.3% (31.6-55.9%) | 73.3% | +30 pts | NO LEAK FOUND | 3.023 / 3.124 / 3.319 / 3.517 | 0 / 0 | 120/120 valid |
| real_timing/raw | ordinary | raw | 100.0% (94.0-100.0%) | 100.0% | +0 pts | LEAKED | 0.957 / 1.433 / 1.661 / 1.841 | None / 0 | 120/120 valid |
| real_timing/real_long-s20261026-raw | real_long | raw | 95.0% (83.5-98.6%) | 100.0% | +5 pts | LEAKED | 0.497 / 4.746 / 5.044 / 5.22 | None / 0 | 80/80 valid |
| real_timing/real_long-s20261026-window_continue | real_long | window_hard | 45.0% (30.7-60.2%) | 92.5% | +48 pts | BOUNDED LEAK | 3.017 / 3.139 / 5.719 / 6.02 | 105 / 1 | 80/80 valid |
| real_timing/window_continue | ordinary | window_hard | 33.3% (22.7-45.9%) | 78.3% | +45 pts | NO LEAK FOUND | 3.033 / 3.082 / 3.126 / 3.297 | 0 / 0 | 120/120 valid |
| real_overnight/ordinary-s20261027-window_continue | ordinary | window_hard | 41.7% (30.1-54.3%) | 80.0% | +38 pts | NO LEAK FOUND | 3.012 / 3.074 / 3.118 / 3.225 | 0 / 0 | 120/120 valid |
| real_overnight/ordinary-s20261028-window_continue | ordinary | window_hard | 46.7% (34.6-59.1%) | 80.0% | +33 pts | NO LEAK FOUND | 3.044 / 3.09 / 3.129 / 3.167 | 0 / 0 | 120/120 valid |
| real_overnight/real_bucket_hard | flood observer | bucket_hard | 66.7% (54.1-77.3%) | 78.3% | +12 pts | BOUNDED LEAK | 3.12 / 3.6233 / n/a / 9.9087 | n/a / 0 | world 0: 0 pending, 0 dead; world 1: 4090 pending, 1305 dead |
| real_overnight/real_long-s20261029-window_continue | real_long | window_hard | 57.5% (42.2-71.5%) | 80.0% | +23 pts | BOUNDED LEAK | 3.025 / 3.049 / 3.061 / 3.077 | 96 / 0 | 80/80 valid |
| real_overnight/real_window_continue | flood observer | window_hard + continue | 48.3% (36.2-60.7%) | 83.3% | +35 pts | BOUNDED LEAK | 3.0661 / 3.407 / n/a / 3.7029 | n/a / 0 | world 0: 0 pending, 0 dead; world 1: 0 pending, 0 dead |

## 2. Diagnosis of the release-time slip (PARAMS v6)

**real_overnight/ordinary-s20261027-window_continue** (W = 3.0 s): 720 client-observed requests, 0 slipped (> W + 0.5 s); client release {'50': 3.012, '95': 3.074, '99': 3.118, 'max': 3.225, 'n': 720}; server-side lateness {'50': 0.001, '95': 0.015, '99': 0.032, 'max': 0.183, 'n': 720}; gateway-side late > 0.25 s: 0, > 1 s: 0; slipped requests overlapping a loop-lag event: 0; loop lag: 3 events, max 0.205 s, 0 over 1 s, max background tasks 1, max in-flight 1, max asyncio tasks 7. Reading: no request slipped.

**real_overnight/ordinary-s20261028-window_continue** (W = 3.0 s): 720 client-observed requests, 0 slipped (> W + 0.5 s); client release {'50': 3.044, '95': 3.09, '99': 3.129, 'max': 3.167, 'n': 720}; server-side lateness {'50': 0.006, '95': 0.025, '99': 0.046, 'max': 0.101, 'n': 720}; gateway-side late > 0.25 s: 0, > 1 s: 0; slipped requests overlapping a loop-lag event: 0; loop lag: 4 events, max 0.115 s, 0 over 1 s, max background tasks 0, max in-flight 0, max asyncio tasks 6. Reading: no request slipped.

**real_overnight/real_bucket_hard** (W = 3.0 s): 720 client-observed requests, 44 slipped (> W + 0.5 s); client release {'50': 3.12, '95': 3.623, '99': 8.572, 'max': 9.909, 'n': 720}; server-side lateness {'50': 0.013, '95': 0.108, '99': 0.223, 'max': 1.801, 'n': 10913}; gateway-side late > 0.25 s: 83, > 1 s: 10; slipped requests overlapping a loop-lag event: 35; loop lag: 639 events, max 1.339 s, 2 over 1 s, max background tasks 0, max in-flight 0, max asyncio tasks 28. Reading: slips coincide with gateway-side lateness and/or loop stalls.

**real_overnight/real_long-s20261029-window_continue** (W = 3.0 s): 480 client-observed requests, 0 slipped (> W + 0.5 s); client release {'50': 3.025, '95': 3.049, '99': 3.061, 'max': 3.077, 'n': 480}; server-side lateness {'50': 0.001, '95': 0.015, '99': 0.024, 'max': 0.032, 'n': 480}; gateway-side late > 0.25 s: 0, > 1 s: 0; slipped requests overlapping a loop-lag event: 0; loop lag: 0 events, max 0.0 s, 0 over 1 s, max background tasks 0, max in-flight 0, max asyncio tasks 0. Reading: no request slipped.

**real_overnight/real_window_continue** (W = 3.0 s): 720 client-observed requests, 21 slipped (> W + 0.5 s); client release {'50': 3.066, '95': 3.407, '99': 3.586, 'max': 3.703, 'n': 720}; server-side lateness {'50': 0.012, '95': 0.089, '99': 0.164, 'max': 1.629, 'n': 10757}; gateway-side late > 0.25 s: 31, > 1 s: 5; slipped requests overlapping a loop-lag event: 21; loop lag: 391 events, max 3.151 s, 2 over 1 s, max background tasks 16, max in-flight 16, max asyncio tasks 40. Reading: slips coincide with gateway-side lateness and/or loop stalls.

## 3. Below-chance check (label permutations)

| Step | Observed test accuracy | Swapped-split accuracy | Null mean (sd) | Two-sided p |
|---|---:|---:|---|---:|
| real_overnight/ordinary-s20261027-window_continue | 0.417 | 0.483 | 0.499 (0.061) | 0.23 |
| real_overnight/ordinary-s20261028-window_continue | 0.467 | 0.567 | 0.501 (0.06) | 0.673 |
| real_overnight/real_bucket_hard | 0.6 | 0.517 | 0.503 (0.06) | 0.134 |
| real_overnight/real_long-s20261029-window_continue | 0.575 | 0.5 | 0.502 (0.073) | 0.389 |
| real_overnight/real_window_continue | 0.433 | 0.483 | 0.499 (0.059) | 0.351 |

## 4. Flood with the real model: audit and load

- **real_overnight/real_bucket_hard**: 84.9 flood requests per run, observer attempts recorded 6, observer cancelled 0, max sampled audit outbox {'0': 29, '1': 4146}, queue after drain [{'world': 0, 'pending_after_drain': 0, 'dead_letters': 0}, {'world': 1, 'pending_after_drain': 4090, 'dead_letters': 1305}], dead servers [], throughput check passed: False.
- **real_overnight/real_window_continue**: 83.7 flood requests per run, observer attempts recorded 6, observer cancelled 0, max sampled audit outbox {'0': 25, '1': 25}, queue after drain [{'world': 0, 'pending_after_drain': 0, 'dead_letters': 0}, {'world': 1, 'pending_after_drain': 0, 'dead_letters': 0}], dead servers [], throughput check passed: True.

## 5. Every request (what Red saw, what the evaluator knew)

### `ordinary-s20261027-window_continue.jsonl` (720 requests, 418 KiB)

| role | case | requests | Red's release median / p95 / p99 / max (s) | share later than W + 0.5 s | Blue allowed | backend | answer chars median | completion tokens mean / max |
|---|---|---:|---|---:|---:|---|---:|---|
| timing | allowed | 540 | 3.012 / 3.070 / 3.120 / 3.225 | 0.0% | 100.0% | DeepSeek | 120.0 | 37 / 128 |
| timing | blocked | 180 | 3.013 / 3.079 / 3.114 / 3.122 | 0.0% | 0.0% | - | n/a | n/a |

### `ordinary-s20261028-window_continue.jsonl` (720 requests, 418 KiB)

| role | case | requests | Red's release median / p95 / p99 / max (s) | share later than W + 0.5 s | Blue allowed | backend | answer chars median | completion tokens mean / max |
|---|---|---:|---|---:|---:|---|---:|---|
| timing | allowed | 540 | 3.042 / 3.089 / 3.128 / 3.153 | 0.0% | 100.0% | DeepSeek | 108.0 | 36 / 128 |
| timing | blocked | 180 | 3.046 / 3.092 / 3.128 / 3.167 | 0.0% | 0.0% | - | n/a | n/a |

### `real_bucket_hard.jsonl` (10913 requests, 5356 KiB)

| role | case | requests | Red's release median / p95 / p99 / max (s) | share later than W + 0.5 s | Blue allowed | backend | answer chars median | completion tokens mean / max |
|---|---|---:|---|---:|---:|---|---:|---|
| flood | flood | 10193 | 3.073 / 3.459 / 6.183 / 9.139 | 4.3% | 49.1% | DeepSeek | 130 | 35 / 128 |
| observer | allowed | 720 | 3.120 / 3.623 / 8.572 / 9.909 | 6.1% | 100.0% | DeepSeek | 51 | 18 / 128 |

### `real_long-s20261029-window_continue.jsonl` (480 requests, 259 KiB)

| role | case | requests | Red's release median / p95 / p99 / max (s) | share later than W + 0.5 s | Blue allowed | backend | answer chars median | completion tokens mean / max |
|---|---|---:|---|---:|---:|---|---:|---|
| timing | allowed | 240 | 3.025 / 3.046 / 3.063 / 3.075 | 0.0% | 100.0% | DeepSeek | 226.5 | 226 / 512 |
| timing | blocked | 240 | 3.024 / 3.049 / 3.058 / 3.077 | 0.0% | 0.0% | - | n/a | n/a |

### `real_window_continue.jsonl` (10758 requests, 5343 KiB)

| role | case | requests | Red's release median / p95 / p99 / max (s) | share later than W + 0.5 s | Blue allowed | backend | answer chars median | completion tokens mean / max |
|---|---|---:|---|---:|---:|---|---:|---|
| flood | flood | 10038 | 3.067 / 3.296 / 3.555 / 6.291 | 1.3% | 49.9% | DeepSeek | 132 | 35 / 128 |
| observer | allowed | 720 | 3.066 / 3.407 / 3.586 / 3.703 | 2.9% | 100.0% | DeepSeek | 29.0 | 12 / 99 |

Total request records: 23591; completion tokens recorded: 458302. The private answer texts are in `dashboard/runtime/private/real_overnight/` (git-ignored).

## 6. Docker check with the real model

```json
{
  "label": "real model run, small sample, local (Docker stack)",
  "status": "complete",
  "started": "2026-10-21T22:25:54+0530",
  "isolation": {
    "passed": 11,
    "total": 11
  },
  "traffic": {
    "requests": 30,
    "window_seconds": 3.0,
    "release_seconds": {
      "min": 3.002,
      "median": 3.008,
      "max": 3.511
    },
    "median_by_case": {
      "blocked": 3.015,
      "allowed": 3.007
    },
    "envelope_exact": 30,
    "distinct_status_body": 1
  },
  "evaluation": {
    "attempts": 30,
    "safe": 20,
    "cancelled": 0
  },
  "outputs": {
    "allowed_with_output": 20,
    "backends": [
      "DeepSeek"
    ]
  },
  "audit": "VALID",
  "minutes": 3.2
}
```

## 7. Files

- `real_timing/ordinary-s20261025-raw.json`
- `real_timing/ordinary-s20261025-window_continue.json`
- `real_timing/raw.json`
- `real_timing/real_long-s20261026-raw.json`
- `real_timing/real_long-s20261026-window_continue.json`
- `real_timing/window_continue.json`
- `real_overnight/ordinary-s20261027-window_continue.json`
- `real_overnight/ordinary-s20261028-window_continue.json`
- `real_overnight/real_bucket_hard.json`
- `real_overnight/real_long-s20261029-window_continue.json`
- `real_overnight/real_window_continue.json`
- `eval/output/real_overnight/requests/ordinary-s20261027-window_continue.jsonl`
- `eval/output/real_overnight/requests/ordinary-s20261028-window_continue.jsonl`
- `eval/output/real_overnight/requests/real_bucket_hard.jsonl`
- `eval/output/real_overnight/requests/real_long-s20261029-window_continue.jsonl`
- `eval/output/real_overnight/requests/real_window_continue.jsonl`
