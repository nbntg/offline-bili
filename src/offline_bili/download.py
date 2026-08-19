from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import QThread, Signal
import json
import shutil
import uuid

from .bili23_adapter import Bili23Adapter, VideoPartPreview, VideoPreview
from .integrity import create_manifest


@dataclass(frozen=True)
class DownloadRequest:
    preview: VideoPreview
    part: VideoPartPreview
    quality_id: int


class DownloadCoordinator:
    def __init__(
        self,
        adapter: Bili23Adapter,
        staging_dir: Path,
        library_dir: Path,
        integrity_key: bytes,
    ):
        self.adapter = adapter
        self.staging_dir = staging_dir.resolve()
        self.library_dir = library_dir.resolve()
        self.integrity_key = integrity_key

    def download(self, request: DownloadRequest, cancelled=None, progress=None) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        stage = self.staging_dir / uuid.uuid4().hex
        try:
            metadata = self.adapter.download_to(
                request.part.source_url or request.preview.source_url,
                request.part.cid,
                request.quality_id,
                stage,
                cancelled=cancelled,
                progress=progress,
            )
        except TypeError as error:
            if "cancelled" not in str(error) and "progress" not in str(error):
                raise
            metadata = self.adapter.download_to(
                request.part.source_url or request.preview.source_url,
                request.part.cid,
                request.quality_id,
                stage,
            )
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        metadata.update(
            {
                "collection_title": request.preview.collection_title,
                "description": request.preview.description,
                "published_at": request.preview.published_at,
                "category": request.preview.category,
                "stats": request.preview.stats,
                "tags": list(request.preview.tags),
                "section_title": request.part.section_title,
            }
        )
        (stage / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        relative_files = [
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if path.is_file()
        ]
        create_manifest(
            stage,
            metadata["video_unit_id"],
            metadata,
            relative_files,
            self.integrity_key,
        )
        destination = self.library_dir / metadata["video_unit_id"]
        if destination.exists():
            raise FileExistsError("这个分 P 已经下载过；覆盖更新会在后续版本加入")
        shutil.move(str(stage), str(destination))
        return destination


class DownloadThread(QThread):
    progress = Signal(int, int, int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    job_changed = Signal(str, str, str)

    def __init__(self, coordinator: DownloadCoordinator, jobs: tuple[tuple[str, DownloadRequest], ...], parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self.jobs = jobs

    def run(self) -> None:
        completed: list[Path] = []
        errors = []
        for index, (job_id, request) in enumerate(self.jobs, start=1):
            if self.isInterruptionRequested():
                self.job_changed.emit(job_id, "failed", "任务已取消")
                continue
            self.progress.emit(index, len(self.jobs), 0, request.part.title)
            self.job_changed.emit(job_id, "running", "")
            try:
                completed.append(
                    self.coordinator.download(
                        request,
                        self.isInterruptionRequested,
                        lambda percent, status, index=index, title=request.part.title: self.progress.emit(
                            index,
                            len(self.jobs),
                            percent,
                            f"{title} · {status}" if status else title,
                        ),
                    )
                )
                self.progress.emit(index, len(self.jobs), 100, request.part.title)
                self.job_changed.emit(job_id, "completed", "")
            except Exception as error:
                message = str(error)
                errors.append(message)
                self.job_changed.emit(job_id, "failed", message)
        if errors and not completed:
            self.failed.emit(errors[0])
        self.succeeded.emit(tuple(completed))

    def cancel(self) -> None:
        self.requestInterruption()
