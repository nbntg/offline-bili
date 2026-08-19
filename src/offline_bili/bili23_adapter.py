from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from PySide6.QtCore import QThread, Signal
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable

from .bili23_helper import EVENT_PREFIX, RESULT_PREFIX


@dataclass(frozen=True)
class VideoPartPreview:
    cid: int
    page: int
    title: str
    duration: int
    source_url: str = ""
    bvid: str = ""
    section_title: str = ""


@dataclass(frozen=True)
class QualityPreview:
    quality_id: int
    name: str


@dataclass(frozen=True)
class VideoPreview:
    source_url: str
    bvid: str
    aid: int | None
    title: str
    cover_url: str
    owner_name: str
    owner_face_url: str
    parts: tuple[VideoPartPreview, ...]
    qualities: tuple[QualityPreview, ...]
    cover_path: str = ""
    owner_face_path: str = ""
    description: str = ""
    published_at: int = 0
    category: str = ""
    stats: dict = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    collection_title: str = ""


class Bili23Adapter:
    def __init__(self, root: Path, data_dir: Path):
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.vendor_src = self.root / "vendor" / "Bili23-Downloader" / "src"
        if not self.vendor_src.is_dir():
            raise FileNotFoundError("缺少 Bili23-Downloader 上游源码")

    def parse(self, url: str) -> VideoPreview:
        payload = self._run([
            "--operation",
            "parse",
            "--url",
            url,
        ], timeout=45)
        return preview_from_dict(payload["preview"])

    def download_to(
        self,
        source_url: str,
        cid: int,
        quality_id: int,
        output_dir: Path,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> dict:
        progress_path = output_dir.parent / f".{output_dir.name}.progress.json"
        arguments = [
            "--operation",
            "download",
            "--url",
            source_url,
            "--cid",
            str(cid),
            "--quality",
            str(quality_id),
            "--output",
            str(output_dir.resolve()),
            "--progress-file",
            str(progress_path.resolve()),
        ]
        ffmpeg = self.root / "tools" / "ffmpeg" / "ffmpeg.exe"
        if ffmpeg.is_file():
            arguments.extend(["--ffmpeg", str(ffmpeg)])
        try:
            payload = self._run(
                arguments,
                timeout=3600,
                cancelled=cancelled,
                progress_path=progress_path,
                progress=progress,
            )
            return payload["download"]
        finally:
            progress_path.unlink(missing_ok=True)
            progress_path.with_suffix(progress_path.suffix + ".tmp").unlink(missing_ok=True)

    def _run(
        self,
        arguments: list[str],
        timeout: int,
        cancelled: Callable[[], bool] | None = None,
        progress_path: Path | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> dict:
        command = [
            *self._helper_command(),
            "--vendor-src",
            str(self.vendor_src),
            "--data-dir",
            str(self.data_dir),
            *arguments,
        ]
        if cancelled is None and progress is None:
            result = subprocess.run(
                command, cwd=self.root, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, creationflags=_hidden_process_flags(),
            )
            stdout, stderr = result.stdout, result.stderr
        else:
            process = subprocess.Popen(
                command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", creationflags=_hidden_process_flags(),
            )
            started = time.monotonic()
            last_progress: tuple[int, str] | None = None
            while process.poll() is None:
                if cancelled is not None and cancelled():
                    process.terminate()
                    process.communicate(timeout=5)
                    raise RuntimeError("任务已取消")
                if progress is not None and progress_path is not None and progress_path.is_file():
                    try:
                        progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
                        current_progress = (
                            int(progress_data.get("percent", 0)),
                            str(progress_data.get("status", "")),
                        )
                        if current_progress != last_progress:
                            progress(*current_progress)
                            last_progress = current_progress
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        pass
                if time.monotonic() - started > timeout:
                    process.terminate()
                    process.communicate(timeout=5)
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(0.2)
            stdout, stderr = process.communicate()
        payload_line = next(
            (line for line in reversed(stdout.splitlines()) if line.startswith(RESULT_PREFIX)),
            None,
        )
        if payload_line is None:
            message = stderr.strip() or "Bili23 解析进程没有返回结果"
            raise RuntimeError(message)
        payload = json.loads(payload_line.removeprefix(RESULT_PREFIX))
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or "Bili23 解析失败")
        return payload

    @staticmethod
    def _helper_command() -> list[str]:
        if getattr(sys, "frozen", False):
            helper = Path(sys.executable).resolve().parent / "helper" / "OfflineBiliHelper.exe"
            return [str(helper)]
        return [sys.executable, "-m", "offline_bili.bili23_helper"]


class ParseLinksThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, adapter: Bili23Adapter, links: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.links = links

    def run(self) -> None:
        previews: list[VideoPreview] = []
        try:
            for link in self.links:
                previews.append(self.adapter.parse(link))
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.succeeded.emit(tuple(previews))


class LoginThread(QThread):
    qrcode_ready = Signal(str)
    status_changed = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, adapter: Bili23Adapter, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self._process: subprocess.Popen | None = None

    def run(self) -> None:
        command = [
            *self.adapter._helper_command(),
            "--vendor-src",
            str(self.adapter.vendor_src),
            "--data-dir",
            str(self.adapter.data_dir),
            "--operation",
            "login",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                cwd=self.adapter.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_hidden_process_flags(),
            )
            assert self._process.stdout is not None
            result = None
            for raw_line in self._process.stdout:
                line = raw_line.strip()
                if line.startswith(EVENT_PREFIX):
                    event = json.loads(line.removeprefix(EVENT_PREFIX))
                    if event.get("type") == "qrcode":
                        self.qrcode_ready.emit(event["url"])
                    elif event.get("type") == "status":
                        self.status_changed.emit(int(event["code"]), event.get("message", ""))
                elif line.startswith(RESULT_PREFIX):
                    result = json.loads(line.removeprefix(RESULT_PREFIX))
            return_code = self._process.wait()
            if result and result.get("ok"):
                self.succeeded.emit(result["login"])
            elif not self.isInterruptionRequested():
                stderr = self._process.stderr.read().strip() if self._process.stderr else ""
                self.failed.emit((result or {}).get("error") or stderr or f"登录进程退出：{return_code}")
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
        finally:
            self._process = None

    def stop(self) -> None:
        self.requestInterruption()
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()


def preview_from_dict(data: dict) -> VideoPreview:
    return VideoPreview(
        source_url=data["source_url"],
        bvid=data["bvid"],
        aid=data.get("aid"),
        title=data["title"],
        cover_url=data.get("cover_url", ""),
        owner_name=data.get("owner_name", ""),
        owner_face_url=data.get("owner_face_url", ""),
        parts=tuple(VideoPartPreview(**part) for part in data.get("parts", [])),
        qualities=tuple(
            QualityPreview(quality_id=quality["id"], name=quality["name"])
            for quality in data.get("qualities", [])
        ),
        cover_path=data.get("cover_path", ""),
        owner_face_path=data.get("owner_face_path", ""),
        description=data.get("description", ""),
        published_at=int(data.get("published_at", 0) or 0),
        category=data.get("category", ""),
        stats=data.get("stats") or {},
        tags=tuple(data.get("tags") or ()),
        collection_title=data.get("collection_title", ""),
    )


def _hidden_process_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
