from pathlib import Path

from offline_bili.integrity import create_manifest, verify_package
from offline_bili.library import ManagedLibrary


KEY = b"test-key-that-is-not-used-in-production"


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "library" / "BV-test-1"
    package.mkdir(parents=True)
    (package / "video.mp4").write_bytes(b"video")
    (package / "danmaku.xml").write_text("<i />", encoding="utf-8")
    create_manifest(
        package,
        "BV-test:cid-1",
        {"title": "Test video"},
        ["video.mp4", "danmaku.xml"],
        KEY,
    )
    return package


def test_valid_package_is_visible(tmp_path: Path):
    package = _package(tmp_path)

    result = verify_package(package, KEY)
    scan = ManagedLibrary(tmp_path / "library", KEY).scan()

    assert result.valid
    assert [video.video_unit_id for video in scan.videos] == ["BV-test:cid-1"]
    assert scan.rejected == ()


def test_modified_media_is_rejected(tmp_path: Path):
    package = _package(tmp_path)
    (package / "video.mp4").write_bytes(b"other")

    result = verify_package(package, KEY)

    assert not result.valid
    assert "mismatch" in result.reason


def test_unrecorded_file_is_rejected(tmp_path: Path):
    package = _package(tmp_path)
    (package / "personal-video.mp4").write_bytes(b"not managed")

    result = verify_package(package, KEY)

    assert not result.valid
    assert result.reason == "unrecorded or missing files"


def test_forged_manifest_is_rejected(tmp_path: Path):
    package = _package(tmp_path)
    manifest = package / ".offline-bili.json"
    content = manifest.read_text(encoding="utf-8").replace("Test video", "Forged")
    manifest.write_text(content, encoding="utf-8")

    result = verify_package(package, KEY)

    assert not result.valid
    assert result.reason == "invalid manifest signature"

