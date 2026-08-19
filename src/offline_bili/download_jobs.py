from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import time
import uuid

from .bili23_adapter import QualityPreview, VideoPartPreview, VideoPreview
from .download import DownloadRequest


@dataclass(frozen=True)
class DownloadJob:
    job_id: str
    request: DownloadRequest
    status: str
    error: str
    created_at: int


class DownloadJobStore:
    def __init__(self, path: Path):
        self.path = path
        self._recover_interrupted()

    def list_jobs(self) -> tuple[DownloadJob, ...]:
        return tuple(sorted(self._read(), key=lambda item: item.created_at))

    def add(self, requests: tuple[DownloadRequest, ...]) -> tuple[DownloadJob, ...]:
        jobs = list(self.list_jobs())
        now = int(time.time())
        added = tuple(
            DownloadJob(uuid.uuid4().hex, request, "pending", "", now + index)
            for index, request in enumerate(requests)
        )
        jobs.extend(added)
        self._write(jobs)
        return added

    def set_status(self, job_id: str, status: str, error: str = "") -> None:
        jobs = [
            DownloadJob(job.job_id, job.request, status, error, job.created_at)
            if job.job_id == job_id else job
            for job in self.list_jobs()
        ]
        self._write(jobs)

    def remove(self, job_ids: set[str]) -> None:
        self._write([job for job in self.list_jobs() if job.job_id not in job_ids])

    def _read(self) -> tuple[DownloadJob, ...]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return tuple(_job_from_dict(item) for item in data.get("jobs", []))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return ()

    def _write(self, jobs: list[DownloadJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"jobs": [_job_to_dict(job) for job in jobs]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _recover_interrupted(self) -> None:
        jobs = list(self._read())
        recovered = [
            DownloadJob(job.job_id, job.request, "failed", "程序上次退出时下载中断", job.created_at)
            if job.status == "running" else job
            for job in jobs
        ]
        if recovered != jobs:
            self._write(recovered)


def _job_to_dict(job: DownloadJob) -> dict:
    preview = job.request.preview
    part = job.request.part
    return {
        "job_id": job.job_id,
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at,
        "quality_id": job.request.quality_id,
        "part": {
            "cid": part.cid,
            "page": part.page,
            "title": part.title,
            "duration": part.duration,
            "source_url": part.source_url,
            "bvid": part.bvid,
            "section_title": part.section_title,
        },
        "preview": {
            "source_url": preview.source_url,
            "bvid": preview.bvid,
            "aid": preview.aid,
            "title": preview.title,
            "cover_url": preview.cover_url,
            "owner_name": preview.owner_name,
            "owner_face_url": preview.owner_face_url,
            "cover_path": preview.cover_path,
            "owner_face_path": preview.owner_face_path,
            "description": preview.description,
            "published_at": preview.published_at,
            "category": preview.category,
            "stats": preview.stats,
            "tags": list(preview.tags),
            "collection_title": preview.collection_title,
            "parts": [
                {
                    "cid": item.cid,
                    "page": item.page,
                    "title": item.title,
                    "duration": item.duration,
                    "source_url": item.source_url,
                    "bvid": item.bvid,
                    "section_title": item.section_title,
                }
                for item in preview.parts
            ],
            "qualities": [
                {"quality_id": item.quality_id, "name": item.name} for item in preview.qualities
            ],
        },
    }


def _job_from_dict(data: dict) -> DownloadJob:
    preview_data = data["preview"]
    preview = VideoPreview(
        source_url=preview_data["source_url"],
        bvid=preview_data["bvid"],
        aid=preview_data.get("aid"),
        title=preview_data["title"],
        cover_url=preview_data.get("cover_url", ""),
        owner_name=preview_data.get("owner_name", ""),
        owner_face_url=preview_data.get("owner_face_url", ""),
        parts=tuple(VideoPartPreview(**item) for item in preview_data.get("parts", [])),
        qualities=tuple(QualityPreview(**item) for item in preview_data.get("qualities", [])),
        cover_path=preview_data.get("cover_path", ""),
        owner_face_path=preview_data.get("owner_face_path", ""),
        description=preview_data.get("description", ""),
        published_at=int(preview_data.get("published_at", 0) or 0),
        category=preview_data.get("category", ""),
        stats=preview_data.get("stats") or {},
        tags=tuple(preview_data.get("tags") or ()),
        collection_title=preview_data.get("collection_title", ""),
    )
    part = VideoPartPreview(**data["part"])
    return DownloadJob(
        job_id=data["job_id"],
        request=DownloadRequest(preview, part, int(data["quality_id"])),
        status=data.get("status", "pending"),
        error=data.get("error", ""),
        created_at=int(data.get("created_at", 0)),
    )
