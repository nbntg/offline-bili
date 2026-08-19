from __future__ import annotations

from pathlib import Path
from typing import Any
import os

from PySide6.QtCore import QObject, Signal


class MpvUnavailableError(RuntimeError):
    pass


class MpvBackend(QObject):
    """Thin, replaceable adapter around python-mpv and the portable libmpv DLL."""

    position_changed = Signal(float)
    duration_changed = Signal(float)
    pause_changed = Signal(bool)
    ended = Signal()

    def __init__(self, window_id: int, tools_dir: Path, parent: QObject | None = None):
        super().__init__(parent)
        dll_dir = (tools_dir / "mpv").resolve()
        dll_path = dll_dir / "libmpv-2.dll"
        cache_dir = tools_dir.resolve().parent / "data" / "cache" / "mpv"
        cache_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt" and not dll_path.is_file():
            raise MpvUnavailableError(f"缺少播放组件：{dll_path}")

        self._dll_directory: Any = None
        if os.name == "nt":
            self._dll_directory = os.add_dll_directory(str(dll_dir))
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")

        try:
            import mpv
        except (ImportError, OSError) as error:
            raise MpvUnavailableError(f"无法加载 libmpv：{error}") from error

        try:
            self._player = mpv.MPV(
                wid=str(window_id),
                vo="gpu-next",
                hwdec="auto-safe",
                osc=False,
                input_default_bindings=False,
                input_vo_keyboard=False,
                keep_open=True,
                idle=True,
                config=False,
                load_scripts=False,
                gpu_shader_cache_dir=str(cache_dir),
                log_handler=self._log,
            )
            self._subtitle_track_id: int | None = None
            self._danmaku_track_id: int | None = None
            self._danmaku_is_primary = False
            self._player.observe_property("time-pos", self._position_observer)
            self._player.observe_property("duration", self._duration_observer)
            self._player.observe_property("pause", self._pause_observer)
            self._player.register_event_callback(self._event_observer)
        except Exception as error:
            raise MpvUnavailableError(f"初始化播放器失败：{error}") from error

    def load(
        self,
        media_path: Path,
        danmaku_path: Path | None = None,
        audio_path: Path | None = None,
        subtitle_path: Path | None = None,
    ) -> None:
        self._player.command("loadfile", str(media_path), "replace")
        self._subtitle_track_id = None
        self._danmaku_track_id = None
        self._danmaku_is_primary = False
        if audio_path and audio_path.is_file():
            self._player.command("audio-add", str(audio_path), "select")
        if subtitle_path and subtitle_path.is_file():
            self._player.command("sub-add", str(subtitle_path), "select")
            self._subtitle_track_id = self._track_id(subtitle_path)
        if danmaku_path and danmaku_path.is_file():
            selection = "auto" if self._subtitle_track_id is not None else "select"
            self._player.command("sub-add", str(danmaku_path), selection)
            self._danmaku_track_id = self._track_id(danmaku_path)
            if self._subtitle_track_id is not None and self._danmaku_track_id is not None:
                self._player.secondary_sid = self._danmaku_track_id
            else:
                self._danmaku_is_primary = True

    def set_speed(self, speed: float) -> None:
        self._player.speed = speed

    def set_paused(self, paused: bool) -> None:
        self._player.pause = paused

    def set_volume(self, volume: int) -> None:
        self._player.volume = max(0, min(100, volume))

    def seek(self, seconds: float) -> None:
        self._player.command("seek", seconds, "absolute", "exact")

    def refresh_video(self) -> None:
        self._player.command("video-reconfig")

    def set_subtitle_visible(self, visible: bool) -> None:
        if self._subtitle_track_id is not None:
            self._player.sub_visibility = visible

    def set_danmaku_visible(self, visible: bool) -> None:
        if self._danmaku_is_primary:
            self._player.sub_visibility = visible
        else:
            self._player.secondary_sub_visibility = visible

    def reload_danmaku(self, subtitle_path: Path | None) -> None:
        if self._danmaku_track_id is not None:
            self._player.command("sub-remove", self._danmaku_track_id)
        self._danmaku_track_id = None
        if subtitle_path and subtitle_path.is_file():
            selection = "auto" if self._subtitle_track_id is not None else "select"
            self._player.command("sub-add", str(subtitle_path), selection)
            self._danmaku_track_id = self._track_id(subtitle_path)
            self._danmaku_is_primary = self._subtitle_track_id is None
            if not self._danmaku_is_primary and self._danmaku_track_id is not None:
                self._player.secondary_sid = self._danmaku_track_id

    def reload_subtitle(self, subtitle_path: Path | None) -> None:
        if self._subtitle_track_id is not None:
            self._player.command("sub-remove", self._subtitle_track_id)
        self._subtitle_track_id = None
        if subtitle_path and subtitle_path.is_file():
            self._player.command("sub-add", str(subtitle_path), "select")
            self._subtitle_track_id = self._track_id(subtitle_path)
            if self._danmaku_track_id is not None:
                self._player.secondary_sid = self._danmaku_track_id

    def _track_id(self, path: Path) -> int | None:
        expected = str(path.resolve()).casefold()
        for track in self._player.track_list or []:
            external = str(track.get("external-filename", "")).casefold()
            if external == expected or external.endswith(path.name.casefold()):
                return int(track["id"])
        return None

    def shutdown(self) -> None:
        player = getattr(self, "_player", None)
        if player is not None:
            player.terminate()
            self._player = None
        if self._dll_directory is not None:
            self._dll_directory.close()
            self._dll_directory = None

    def _position_observer(self, _name: str, value: float | None) -> None:
        if value is not None:
            self.position_changed.emit(float(value))

    def _duration_observer(self, _name: str, value: float | None) -> None:
        if value is not None:
            self.duration_changed.emit(float(value))

    def _pause_observer(self, _name: str, value: bool | None) -> None:
        if value is not None:
            self.pause_changed.emit(bool(value))

    def _event_observer(self, event: Any) -> None:
        event_id = getattr(getattr(event, "event_id", None), "value", None)
        if event_id == 7:  # MPV_EVENT_END_FILE
            self.ended.emit()

    @staticmethod
    def _log(_level: str, _component: str, _message: str) -> None:
        return
