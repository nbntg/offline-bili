from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json


@dataclass
class AppSettings:
    library_path: str = ""
    playback_speed: float = 1.0
    volume: int = 100
    autoplay: bool = False
    danmaku_font_size: int = 36
    danmaku_opacity: float = 0.8
    danmaku_display_area: float = 0.6
    danmaku_speed: float = 10.0
    danmaku_density: int = 60
    danmaku_scroll: bool = True
    danmaku_top: bool = True
    danmaku_bottom: bool = True
    subtitle_font_size: int = 42
    subtitle_position: int = 92
    subtitle_background_opacity: float = 0.35


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.is_file():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AppSettings(
                library_path=str(data.get("library_path", "")),
                playback_speed=float(data.get("playback_speed", 1.0)),
                volume=max(0, min(100, int(data.get("volume", 100)))),
                autoplay=bool(data.get("autoplay", False)),
                danmaku_font_size=max(18, min(72, int(data.get("danmaku_font_size", 36)))),
                danmaku_opacity=max(0.1, min(1.0, float(data.get("danmaku_opacity", 0.8)))),
                danmaku_display_area=max(0.2, min(1.0, float(data.get("danmaku_display_area", 0.6)))),
                danmaku_speed=max(4.0, min(18.0, float(data.get("danmaku_speed", 10.0)))),
                danmaku_density=max(20, min(100, int(data.get("danmaku_density", 60)))),
                danmaku_scroll=bool(data.get("danmaku_scroll", True)),
                danmaku_top=bool(data.get("danmaku_top", True)),
                danmaku_bottom=bool(data.get("danmaku_bottom", True)),
                subtitle_font_size=max(18, min(72, int(data.get("subtitle_font_size", 42)))),
                subtitle_position=max(65, min(96, int(data.get("subtitle_position", 92)))),
                subtitle_background_opacity=max(
                    0.0, min(0.9, float(data.get("subtitle_background_opacity", 0.35)))
                ),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
