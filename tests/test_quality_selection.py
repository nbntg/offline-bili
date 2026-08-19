from offline_bili.bili23_helper import _available_qualities


def test_only_actual_streams_are_offered_as_download_qualities():
    play_data = {
        "quality": 80,
        "accept_quality": [127, 120, 116, 80, 64],
        "accept_description": ["8K", "4K", "1080P60", "1080P", "720P"],
        "dash": {
            "video": [
                {"id": 80, "codecs": "avc1"},
                {"id": 80, "codecs": "hev1"},
                {"id": 64, "codecs": "avc1"},
            ]
        },
    }

    assert _available_qualities(play_data) == [(80, "1080P"), (64, "720P")]


def test_reported_quality_is_used_when_dash_list_is_absent():
    assert _available_qualities({"quality": 32}) == [(32, "32")]
