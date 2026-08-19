import json

from offline_bili.subtitles import SubtitleSettings, render_bilibili_subtitle


def test_official_subtitle_json_renders_to_timed_ass(tmp_path):
    source = tmp_path / "subtitle-zh.json"
    source.write_text(
        json.dumps({"body": [{"from": 1.25, "to": 3.5, "content": "你好"}]}),
        encoding="utf-8",
    )

    rendered = render_bilibili_subtitle(
        source, SubtitleSettings(font_size=50, position=90, background_opacity=0.5)
    )

    assert "Style: Default,Microsoft YaHei,50" in rendered
    assert "0:00:01.25,0:00:03.50" in rendered
    assert "你好" in rendered
