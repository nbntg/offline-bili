from offline_bili.bili23_helper import _chapters_from_player_data


def test_chapters_are_extracted_from_shared_player_data():
    chapters = _chapters_from_player_data(
        {
            "view_points": [
                {"content": "开场", "from": 0, "to": 12},
                {"content": "核心内容", "from": 12, "to": 30},
            ]
        },
        duration=30,
    )

    assert chapters == [
        {"title": "开场", "start": 0.0, "end": 12.0},
        {"title": "核心内容", "start": 12.0, "end": 30.0},
    ]


def test_last_chapter_uses_video_duration_when_api_omits_end():
    chapters = _chapters_from_player_data(
        {"view_points": [{"content": "结尾", "from": 90, "to": 0}]},
        duration=120,
    )

    assert chapters == [{"title": "结尾", "start": 90.0, "end": 120.0}]

