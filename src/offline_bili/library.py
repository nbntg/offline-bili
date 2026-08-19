from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .integrity import VerificationResult, verify_package


VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
DANMAKU_SUFFIXES = {".xml"}
AUDIO_SUFFIXES = {".m4a", ".aac", ".flac", ".mp3", ".ogg", ".opus"}


@dataclass(frozen=True)
class ManagedVideo:
    package_dir: Path
    video_unit_id: str
    metadata: dict[str, Any]
    files: tuple[Path, ...]

    @property
    def media_path(self) -> Path | None:
        return next((path for path in self.files if path.suffix.casefold() in VIDEO_SUFFIXES), None)

    @property
    def danmaku_path(self) -> Path | None:
        return next((path for path in self.files if path.suffix.casefold() in DANMAKU_SUFFIXES), None)

    @property
    def audio_path(self) -> Path | None:
        return next((path for path in self.files if path.suffix.casefold() in AUDIO_SUFFIXES), None)

    @property
    def cover_path(self) -> Path | None:
        return next((path for path in self.files if path.name.casefold() == "cover.jpg"), None)

    @property
    def avatar_path(self) -> Path | None:
        return next((path for path in self.files if path.name.casefold() == "avatar.jpg"), None)

    @property
    def subtitle_paths(self) -> tuple[Path, ...]:
        return tuple(
            path for path in self.files
            if path.name.casefold().startswith("subtitle-") and path.suffix.casefold() == ".json"
        )


@dataclass(frozen=True)
class RejectedPackage:
    package_dir: Path
    reason: str


@dataclass(frozen=True)
class LibraryScan:
    videos: tuple[ManagedVideo, ...]
    rejected: tuple[RejectedPackage, ...]


class ManagedLibrary:
    def __init__(self, library_dir: Path, integrity_key: bytes):
        self.library_dir = library_dir
        self.integrity_key = integrity_key

    def scan(self) -> LibraryScan:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        videos: list[ManagedVideo] = []
        rejected: list[RejectedPackage] = []

        for package_dir in sorted(path for path in self.library_dir.iterdir() if path.is_dir()):
            result = verify_package(package_dir, self.integrity_key)
            if result.valid:
                videos.append(self._to_video(package_dir, result))
            else:
                rejected.append(RejectedPackage(package_dir, result.reason))

        return LibraryScan(tuple(videos), tuple(rejected))

    @staticmethod
    def _to_video(package_dir: Path, result: VerificationResult) -> ManagedVideo:
        assert result.manifest is not None
        manifest = result.manifest
        files = tuple(package_dir / entry["path"] for entry in manifest["files"])
        return ManagedVideo(
            package_dir=package_dir,
            video_unit_id=manifest["video_unit_id"],
            metadata=manifest.get("metadata", {}),
            files=files,
        )
