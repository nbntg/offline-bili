from offline_bili.bili23_adapter import preview_from_dict


def test_preview_mapping_preserves_parts_and_qualities():
    preview = preview_from_dict(
        {
            "source_url": "https://www.bilibili.com/video/BV1test",
            "bvid": "BV1test",
            "aid": 123,
            "title": "示例视频",
            "cover_path": "data/bili23/preview-cache/BV1test-cover.jpg",
            "owner_name": "示例 UP",
            "owner_face_path": "data/bili23/preview-cache/BV1test-owner.jpg",
            "description": "这是视频简介",
            "published_at": 1_750_000_000,
            "category": "知识",
            "stats": {"view": 12_345, "like": 678},
            "tags": ["数学", "高考"],
            "collection_title": "数学大观",
            "parts": [{
                "cid": 456,
                "page": 1,
                "title": "第一集",
                "duration": 90,
                "source_url": "https://www.bilibili.com/video/BV1episode",
                "bvid": "BV1episode",
                "section_title": "积分应用大观",
            }],
            "qualities": [{"id": 80, "name": "高清 1080P"}],
        }
    )

    assert preview.title == "示例视频"
    assert preview.parts[0].cid == 456
    assert preview.qualities[0].quality_id == 80
    assert preview.cover_path.endswith("BV1test-cover.jpg")
    assert preview.owner_face_path.endswith("BV1test-owner.jpg")
    assert preview.description == "这是视频简介"
    assert preview.category == "知识"
    assert preview.stats["view"] == 12_345
    assert preview.tags == ("数学", "高考")
    assert preview.collection_title == "数学大观"
    assert preview.parts[0].source_url.endswith("BV1episode")
    assert preview.parts[0].section_title == "积分应用大观"
