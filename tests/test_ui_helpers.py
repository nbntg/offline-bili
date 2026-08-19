from offline_bili.ui import _parse_timecode


def test_timecode_parser_accepts_common_player_formats():
    assert _parse_timecode("01:23:45 / 05:38:19") == 5025
    assert _parse_timecode("12:34") == 754
    assert _parse_timecode("90") == 90
    assert _parse_timecode("12:99") is None
    assert _parse_timecode("不是时间") is None
