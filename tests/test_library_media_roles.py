from pathlib import Path

from offline_bili.library import ManagedVideo


def test_managed_video_resolves_separate_dash_streams():
    video = ManagedVideo(
        package_dir=Path("package"),
        video_unit_id="BV-test-1",
        metadata={},
        files=(Path("package/video.mp4"), Path("package/audio.m4a"), Path("package/danmaku.xml")),
    )

    assert video.media_path == Path("package/video.mp4")
    assert video.audio_path == Path("package/audio.m4a")
    assert video.danmaku_path == Path("package/danmaku.xml")
