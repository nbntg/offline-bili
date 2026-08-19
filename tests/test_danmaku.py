from offline_bili.danmaku import DanmakuSettings, parse_bilibili_xml, render_ass


XML = """<i>
<d p="1.25,1,25,16711680,0,0,0,0">hello</d>
<d p="2.50,5,25,65280,0,0,0,0">blocked text</d>
</i>"""


def test_bilibili_xml_timestamps_are_preserved_in_ass():
    comments = parse_bilibili_xml(XML)

    ass = render_ass(comments, DanmakuSettings(blocked_keywords=("blocked",)))

    assert "0:00:01.25" in ass
    assert "hello" in ass
    assert "blocked text" not in ass
    assert "\\move(" in ass


def test_static_top_comment_uses_top_alignment():
    comments = parse_bilibili_xml(XML)

    ass = render_ass(comments, DanmakuSettings())

    assert "\\an8\\pos(" in ass
