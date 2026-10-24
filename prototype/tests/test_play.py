"""/play: one attack at a time, two panels (without / with our solution), one Run button, Next for the next attack.
No inline code (the dashboard's CSP forbids it); every attack carries both panels, an explanation and its source."""
import re

from fastapi.testclient import TestClient

from dashboard.app import create_app


def client(tmp_path):
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "audit", eval_mode=False)
    return TestClient(app, base_url="http://127.0.0.1")


def test_play_page_has_no_inline_code_and_its_files_are_served(tmp_path):
    c = client(tmp_path)
    page, script = c.get("/play"), c.get("/static/play.js")
    assert page.status_code == 200 and script.status_code == 200 and c.get("/static/play.css").status_code == 200
    assert "Team Ctrl Alt" in page.text and 'id="run"' in page.text and 'id="next"' in page.text
    assert "<style" not in page.text and not re.search(r"<script(?![^>]*src=)", page.text)
    assert "https://" not in page.text + script.text and not re.search(r"sk-[0-9a-f]{20}", script.text)


def test_every_attack_has_a_button_two_panels_and_an_explanation(tmp_path):
    script = client(tmp_path).get("/static/play.js").text
    entries = re.findall(r'\{nav:"([^"]+)"', script)
    assert len(entries) == 14  # Overview, attacks 1-11, Feedback, Score
    attacks = [e for e in entries if re.match(r"\d+ ", e)]
    assert len(attacks) == 11
    assert script.count("L:P(") == 14 and script.count("R:P(") == 13  # the Score page has a single panel
    assert script.count("fix:") == 14 and script.count("src:") == 14
    badges = re.findall(r'badge:"(STOPPED|REDUCED|INFO)"', script)
    assert badges.count("STOPPED") == 7 and badges.count("REDUCED") == 4  # same tally as FINAL_REPORT.md
