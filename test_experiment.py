"""Local control and evidence tests; no API calls."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import experiment as e
from experiment_real import release_time


class ControlsTest(unittest.TestCase):
    def test_pending_independent_of_result(self):
        with tempfile.TemporaryDirectory() as folder:
            feedback = e.RangeFeedback(Path(folder) / "state.sqlite", b"test-key")
            for count in (0, 13, 100):
                self.assertEqual(feedback.finalize("red", "blue-v1", ["x"] * 100,
                                                   count, False), e.pending_response())
            self.assertEqual(len(e.pending_response()["body"].encode()), 64)
            self.assertEqual(e.pending_response()["status_code"], 202)

    def test_range_contains_count_and_is_not_forced_centered(self):
        with tempfile.TemporaryDirectory() as folder:
            feedback = e.RangeFeedback(Path(folder) / "state.sqlite", b"test-key")
            with patch.object(e.secrets, "randbelow", return_value=0):
                payload = feedback.finalize("red", "v1", ["x"] * 100, 13, True)
            self.assertEqual(payload["safe_range"], [1, 13])
            self.assertNotEqual(sum(payload["safe_range"]) / 2, 13)
            for count in (0, 100):
                payload = feedback.finalize(f"red-{count}", "v1", ["x"] * 100, count, True)
                self.assertLessEqual(payload["safe_range"][0], count)
                self.assertGreaterEqual(payload["safe_range"][1], count)

    def test_reordered_repeat_and_restart_do_not_resample(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite"
            feedback = e.RangeFeedback(path, b"test-key")
            first = feedback.finalize("red", "v1", ["a", "b"] * 50, 13, True)
            restarted = e.RangeFeedback(path, b"test-key")
            with patch.object(e.secrets, "randbelow", side_effect=AssertionError("Resampled")):
                self.assertEqual(first, restarted.finalize("red", "v1", ["b", "a"] * 50, 13, True))

    def test_budget_survives_restart_and_duplicate_counts_matter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite"
            feedback = e.RangeFeedback(path, b"test-key")
            feedback.finalize("red", "v1", ["a"] * 50 + ["b"] * 50, 13, True)
            feedback.finalize("red", "v1", ["a"] * 51 + ["b"] * 49, 13, True)
            restarted = e.RangeFeedback(path, b"test-key")
            self.assertEqual(restarted.finalize("red", "v1", ["third"], 0, True),
                             {"status": "unavailable"})

    def test_cache_role_run_and_session_isolation(self):
        cache = e.SessionCache()
        red = cache.begin_session("tenant", "red", "r1", "s1")
        cache.put(red, "prompt", "value")
        for namespace in (("tenant", "blue", "r1", "s1"),
                          ("tenant", "red", "r2", "s1"),
                          ("tenant", "red", "r1", "s2")):
            self.assertIsNone(cache.get(cache.begin_session(*namespace), "prompt"))
        self.assertIsNone(cache.get(cache.begin_session(*red), "prompt"))

    def test_bucket_boundaries_and_user_overflow_policy(self):
        for value, expected in ((2.9, 3), (3, 3), (3.1, 6), (6, 6), (6.1, 9), (9, 9), (9.4, 9.4)):
            self.assertEqual(release_time(value), expected)


class AuditTest(unittest.TestCase):
    def test_edit_delete_reorder_replay_and_count_change(self):
        with tempfile.TemporaryDirectory() as folder:
            results = e.audit_demo(Path(folder) / "audit")
            self.assertTrue(results.pop("intact"))
            self.assertTrue(all(value is False for value in results.values()))

    def test_same_length_edit_wrong_key_and_recomputed_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            log, checkpoint = folder / "log", folder / "checkpoint"
            key = Ed25519PrivateKey.generate()
            e.write_audit([{"type": "result", "value": "A"}], "r1", key, log, checkpoint)
            self.assertFalse(e.verify_audit(log, checkpoint, Ed25519PrivateKey.generate().public_key(), "r1"))
            log.write_bytes(log.read_bytes().replace(b'"A"', b'"B"'))
            self.assertFalse(e.verify_audit(log, checkpoint, key.public_key(), "r1"))
            records = [json.loads(line) for line in log.read_text().splitlines()]
            previous = "0" * 64
            for record in records:
                record.pop("hash")
                record["previous_hash"] = previous
                record["hash"] = e.hashlib.sha256(e.canonical(record).encode()).hexdigest()
                previous = record["hash"]
            log.write_text("\n".join(e.canonical(row) for row in records) + "\n", encoding="utf-8")
            self.assertFalse(e.verify_audit(log, checkpoint, key.public_key(), "r1"))


class EvidenceTest(unittest.TestCase):
    def test_split_is_by_run_and_pooled_is_diagnostic(self):
        train = e.make_runs("ordinary", "train", 1)
        test = e.make_runs("ordinary", "test", 2)
        results = e.evaluate("ordinary", train, test, "buckets")
        self.assertEqual(results["unseen_test"]["n_runs"], 200)
        self.assertEqual(results["train_plus_unseen_diagnostic_only"]["n_runs"], 400)
        self.assertEqual(results["unseen_test"]["accuracy"], 0.5)
        self.assertLess(results["unseen_test"]["wilson_95_interval"][0], 0.5)
        with self.assertRaises(AssertionError):
            e.evaluate("ordinary", train, train, "raw")

    def test_boundary_and_overflow_residual_leak_detected(self):
        for cohort in ("boundary", "overflow"):
            result = e.evaluate(cohort, e.make_runs(cohort, "train", 1),
                                e.make_runs(cohort, "test", 2), "buckets")
            self.assertGreater(result["unseen_test"]["accuracy"], 0.9)

    def test_hard_timeout_overflow_comparison(self):
        result = e.evaluate("overflow", e.make_runs("overflow", "train", 1),
                            e.make_runs("overflow", "test", 2), "hard_timeout")
        self.assertEqual(result["unseen_test"]["accuracy"], 0.5)
        self.assertEqual(result["timeout_rate"], 1)
        self.assertEqual(e.timed_observation(9.4, "hard_timeout"), 9)
        self.assertEqual(e.timed_observation(2.9, "hard_timeout"), 3)
        self.assertEqual(e.timed_observation(3.1, "hard_timeout"), 6)
        self.assertEqual(e.timeout_response(10), e.pending_response())


if __name__ == "__main__":
    unittest.main()
