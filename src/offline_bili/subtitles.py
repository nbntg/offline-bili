from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubtitleSettings:
    width: int = 1920
    height: int = 1080
    font_name: str = "Microsoft YaHei"
    font_size: int = 42
    position: int = 92
    background_opacity: float = 0.35


def render_bilibili_subtitle(source: Path, settings: SubtitleSettings) -> str:
    data = json.loads(source.read_text(encoding="utf-8"))
    alpha = round(255 * (1 - min(0.9, max(0.0, settings.background_opacity))))
    margin_v = round(settings.height * (100 - min(96, max(65, settings.position))) / 100)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {settings.width}\nPlayResY: {settings.height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{settings.font_name},{settings.font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H{alpha:02X}000000,0,0,0,0,100,100,0,0,3,1,0,2,80,80,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for item in data.get("body", []):
        start = _ass_time(float(item.get("from", 0)))
        end = _ass_time(float(item.get("to", 0)))
        text = str(item.get("content", "")).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return header + "\n".join(events) + ("\n" if events else "")


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"
