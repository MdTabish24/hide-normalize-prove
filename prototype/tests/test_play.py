"""/play: the seven animated scenes that go with the video transcript. Served, self-contained, and in step with the transcript's seven parts."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import create_app


def page(tmp_path):
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "audit", eval_mode=False)
    return TestClient(app, base_url="http://127.0.0.1").get("/play")


def test_play_page_is_served_self_contained_and_has_seven_scenes(tmp_path):
    response = page(tmp_path)
    assert response.status_code == 200 and "Team Ctrl Alt" in response.text
    assert len(re.findall(r'\{name:"\d ', response.text)) == 7
    assert "https://" not in response.text and not re.search(r"sk-[0-9a-f]{20}", response.text)


def test_scene_durations_match_the_transcript_sections(tmp_path):
    durations = [int(d) for d in re.findall(r'name:"\d [^"]+",dur:(\d+)', page(tmp_path).text)]
    assert durations == [25, 30, 35, 105, 35, 40, 20]  # 0:25, 0:30, 0:35, 1:45, 0:35, 0:40, 0:20 as in VIDEO_TRANSCRIPT.md
    transcript = (Path(__file__).parents[1] / "VIDEO_TRANSCRIPT.md").read_text(encoding="utf-8")
    assert "## 4. Eleven attacks (1:30 - 3:15)" in transcript
