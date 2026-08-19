from offline_bili.bili23_adapter import VideoPartPreview, VideoPreview
from offline_bili.download import DownloadCoordinator, DownloadRequest
from offline_bili.library import ManagedLibrary


class FakeAdapter:
    def __init__(self):
        self.source_url = ""

    def download_to(self, source_url, cid, quality_id, output_dir):
        self.source_url = source_url
        output_dir.mkdir(parents=True)
        (output_dir / "video.mp4").write_bytes(b"managed video")
        (output_dir / "danmaku.xml").write_text("<i></i>", encoding="utf-8")
        return {
            "video_unit_id": "BV1-test-9",
            "title": "测试视频",
            "source_url": source_url,
            "cid": cid,
            "quality_id": quality_id,
        }


def test_download_is_published_only_after_manifest_is_created(tmp_path):
    part = VideoPartPreview(
        cid=9,
        page=1,
        title="P1",
        duration=10,
        source_url="https://www.bilibili.com/video/BV1-collection-item",
    )
    preview = VideoPreview(
        source_url="https://www.bilibili.com/video/BV1-test",
        bvid="BV1-test",
        aid=1,
        title="测试视频",
        cover_url="",
        owner_name="",
        owner_face_url="",
        parts=(part,),
        qualities=(),
        collection_title="测试合集",
        stats={"view": 12345, "danmaku": 678},
    )
    key = b"k" * 32
    adapter = FakeAdapter()
    coordinator = DownloadCoordinator(
        adapter,
        tmp_path / "staging",
        tmp_path / "library",
        key,
    )

    destination = coordinator.download(DownloadRequest(preview, part, 80))
    scan = ManagedLibrary(tmp_path / "library", key).scan()

    assert destination.name == "BV1-test-9"
    assert [item.video_unit_id for item in scan.videos] == ["BV1-test-9"]
    assert scan.videos[0].metadata["collection_title"] == "测试合集"
    assert scan.videos[0].metadata["stats"]["view"] == 12345
    assert not scan.rejected
    assert adapter.source_url.endswith("BV1-collection-item")
