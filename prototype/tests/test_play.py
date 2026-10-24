"""/play: the seven animated scenes that go with the video transcript. No inline code (the dashboard's CSP forbids it); scenes in step with the transcript."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import create_app


def client(tmp_path):
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "audit", eval_mode=False)
    return TestClient(app, base_url="http://127.0.0.1")


def test_play_page_has_no_inline_code_and_has_seven_scenes(tmp_path):
    c = client(tmp_path)
    page, script = c.get("/play"), c.get("/static/play.js")
    assert page.status_code == 200 and script.status_code == 200 and c.get("/static/play.css").status_code == 200
    assert "Team Ctrl Alt" in page.text
    assert "<style" not in page.text and not re.search(r"<script(?![^>]*src=)", page.text)
    assert len(re.findall(r'\{name:"\d ', script.text)) == 7
    assert "https://" not in page.text + script.text and not re.search(r"sk-[0-9a-f]{20}", script.text)


def test_scene_durations_match_the_transcript_sections(tmp_path):
    durations = [int(d) for d in re.findall(r'name:"\d [^"]+",dur:(\d+)', client(tmp_path).get("/static/play.js").text)]
    assert durations == [25, 30, 35, 105, 35, 40, 20]  # 0:25, 0:30, 0:35, 1:45, 0:35, 0:40, 0:20 as in VIDEO_TRANSCRIPT.md
    transcript = (Path(__file__).parents[1] / "VIDEO_TRANSCRIPT.md").read_text(encoding="utf-8")
    assert "## 4. Eleven attacks (1:30 - 3:15)" in transcript
