"""The README charts are drawn from the saved result files, not typed in: the numbers must equal what the files say."""
import pytest

pytest.importorskip("matplotlib")

from eval import make_charts


def test_charts_are_drawn_from_the_saved_files_and_match_the_documented_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(make_charts, "OUT", tmp_path)
    rows = {r[0]: r[1:3] for r in make_charts.guess_rates()}
    assert rows["Timing, mock: ordinary"] == (98, 52)
    assert rows["Timing, real model: flood (old default vs ours)"] == (66.7, 58.3)  # real_bucket_hard.json vs real_final.json
    assert rows["Report, none allowed (simulation)"] == (100, 24.0)
    assert make_charts.audit_queue() == (10000, 35)
    assert [g[1] for g in make_charts.flood()] == [(911, 1811), (909, 910), (915, 2519), (912, 1697)]
    assert (tmp_path / "benchmark.png").exists()
