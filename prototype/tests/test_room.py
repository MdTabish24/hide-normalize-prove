"""/room: the walk-through of the 11 attacks. The dashboard's security header only allows its own CSS and JS files, so the page must have no inline code."""
import re

from fastapi.testclient import TestClient

from dashboard.app import create_app


def client(tmp_path):
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "audit", eval_mode=False)
    return TestClient(app, base_url="http://127.0.0.1")


def test_room_page_has_no_inline_code_and_its_files_are_served(tmp_path):
    c = client(tmp_path)
    page = c.get("/room")
    assert page.status_code == 200 and "The Room" in page.text
    assert "<style" not in page.text and not re.search(r"<script(?![^>]*src=)", page.text)  # inline code would be blocked by the CSP
    assert "script-src 'self'" in page.headers["content-security-policy"] and "style-src 'self'" in page.headers["content-security-policy"]
    for path in ("/static/room.css", "/static/room.js"):
        assert c.get(path).status_code == 200
    assert "https://" not in page.text + c.get("/static/room.js").text  # nothing is loaded from outside
    assert not re.search(r"sk-[0-9a-f]{20}", page.text + c.get("/static/room.js").text)


def test_room_counts_are_consistent_with_the_documented_tally(tmp_path):
    script = client(tmp_path).get("/static/room.js").text
    badges = re.findall(r'badge:"(STOPPED|REDUCED)"', script)
    assert len(badges) == 11 and badges.count("STOPPED") == 7 and badges.count("REDUCED") == 4  # same as FINAL_REPORT.md section 5
