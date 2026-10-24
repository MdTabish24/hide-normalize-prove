"""/room: the walk-through of the 11 attacks. Checks the page is served and its counts agree with its own data."""
import re

from fastapi.testclient import TestClient

from dashboard.app import create_app


def page(tmp_path):
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "audit", eval_mode=False)
    return TestClient(app, base_url="http://127.0.0.1").get("/room")


def test_room_page_is_served_and_has_no_secrets_or_external_calls(tmp_path):
    response = page(tmp_path)
    assert response.status_code == 200 and "The Room" in response.text
    assert "http://" not in response.text.replace("http://127.0.0.1", "") and "https://" not in response.text  # self-contained
    assert not re.search(r"sk-[0-9a-f]{20}", response.text)


def test_room_counts_are_consistent_with_the_documented_tally(tmp_path):
    text = page(tmp_path).text
    badges = re.findall(r'badge:"(STOPPED|REDUCED)"', text)
    assert len(badges) == 11 and badges.count("STOPPED") == 7 and badges.count("REDUCED") == 4  # same as FINAL_REPORT.md section 5
    assert "never say" not in text.lower() or "secure" not in re.sub(r'We never say[^<]*', "", text).lower().replace("not proven safe", "")
