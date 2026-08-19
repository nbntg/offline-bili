from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree
import math


@dataclass(frozen=True)
class DanmakuComment:
    time_seconds: float
    mode: int
    font_size: int
    color: int
    text: str


@dataclass(frozen=True)
class DanmakuSettings:
    width: int = 1920
    height: int = 1080
    font_name: str = "Microsoft YaHei"
    font_size: int = 36
    opacity: float = 0.8
    display_area: float = 0.6
    scroll_duration: float = 10.0
    static_duration: float = 5.0
    density: int = 60
    show_scroll: bool = True
    show_top: bool = True
    show_bottom: bool = True
    blocked_keywords: tuple[str, ...] = ()


def parse_bilibili_xml(xml_text: str) -> tuple[DanmakuComment, ...]:
    root = ElementTree.fromstring(xml_text)
    comments: list[DanmakuComment] = []
    for element in root.findall("d"):
        values = element.attrib.get("p", "").split(",")
        if len(values) < 4:
            continue
        try:
            comments.append(
                DanmakuComment(
                    time_seconds=float(values[0]),
                    mode=int(values[1]),
                    font_size=int(values[2]),
                    color=int(values[3]),
                    text=element.text or "",
                )
            )
        except ValueError:
            continue
    return tuple(comments)


def render_ass(comments: tuple[DanmakuComment, ...], settings: DanmakuSettings) -> str:
    header = _ass_header(settings)
    base_lanes = math.floor(settings.height * settings.display_area / settings.font_size)
    lanes = max(1, math.floor(base_lanes * min(100, max(20, settings.density)) / 100))
    scrolling_available = [0.0] * lanes
    top_available = [0.0] * lanes
    bottom_available = [0.0] * lanes
    events: list[str] = []

    for comment in sorted(comments, key=lambda item: item.time_seconds):
        if _blocked(comment.text, settings.blocked_keywords) or comment.mode == 7:
            continue
        if comment.mode in (1, 2, 3, 6) and not settings.show_scroll:
            continue
        if comment.mode == 5 and not settings.show_top:
            continue
        if comment.mode == 4 and not settings.show_bottom:
            continue

        if comment.mode in (1, 2, 3, 6):
            duration = settings.scroll_duration
            lane = _claim_lane(scrolling_available, comment.time_seconds, duration)
            if lane is None:
                continue
            y = settings.font_size * lane + settings.font_size
            estimated_width = max(settings.font_size, len(comment.text) * settings.font_size)
            if comment.mode == 6:
                position = f"\\move(-{estimated_width},{y},{settings.width + estimated_width},{y})"
            else:
                position = f"\\move({settings.width + estimated_width},{y},-{estimated_width},{y})"
        elif comment.mode == 5:
            duration = settings.static_duration
            lane = _claim_lane(top_available, comment.time_seconds, duration)
            if lane is None:
                continue
            y = settings.font_size * lane + settings.font_size
            position = f"\\an8\\pos({settings.width // 2},{y})"
        elif comment.mode == 4:
            duration = settings.static_duration
            lane = _claim_lane(bottom_available, comment.time_seconds, duration)
            if lane is None:
                continue
            y = settings.height - settings.font_size * lane - settings.font_size
            position = f"\\an2\\pos({settings.width // 2},{y})"
        else:
            continue

        start = _ass_time(comment.time_seconds)
        end = _ass_time(comment.time_seconds + duration)
        color = _ass_color(comment.color)
        alpha = round(255 * (1 - min(1.0, max(0.0, settings.opacity))))
        text = _escape_ass(comment.text)
        override = f"{{{position}\\c{color}\\alpha&H{alpha:02X}&}}"
        events.append(f"Dialogue: 0,{start},{end},Danmaku,,0,0,0,,{override}{text}")

    return header + "\n".join(events) + ("\n" if events else "")


def _claim_lane(availability: list[float], start: float, duration: float) -> int | None:
    for index, available_at in enumerate(availability):
        if available_at <= start:
            availability[index] = start + duration
            return index
    return None


def _blocked(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(keyword.casefold() in lowered for keyword in keywords if keyword)


def _ass_header(settings: DanmakuSettings) -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {settings.width}\n"
        f"PlayResY: {settings.height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Danmaku,{settings.font_name},{settings.font_size},&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _ass_color(rgb: int) -> str:
    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return f"&H{blue:02X}{green:02X}{red:02X}&"


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
