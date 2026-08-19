from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlencode


RESULT_PREFIX = "OFFLINE_BILI_RESULT:"
EVENT_PREFIX = "OFFLINE_BILI_EVENT:"


def _emit_event(event: dict) -> None:
    print(EVENT_PREFIX + json.dumps(event, ensure_ascii=True, separators=(",", ":")), flush=True)


def _bootstrap(vendor_src: Path, data_dir: Path) -> None:
    os.environ["OFFLINE_BILI_BILI23_DATA"] = str(data_dir.resolve())
    sys.path.insert(0, str(vendor_src.resolve()))


def _prepare_wbi() -> None:
    from util.common.config import config
    from util.network.request import ResponseType, SyncNetWorkRequest

    response = SyncNetWorkRequest("https://api.bilibili.com/x/web-interface/nav").run()
    data = response.get("data") or {}
    wbi = data.get("wbi_img") or {}
    img_url = wbi.get("img_url", "")
    sub_url = wbi.get("sub_url", "")
    if not img_url or not sub_url:
        raise RuntimeError("B 站未返回 WBI 验证信息")
    config.set(config.img_key, Path(img_url).stem, save=False)
    config.set(config.sub_key, Path(sub_url).stem, save=False)


def _normalize_url(url: str) -> str:
    if "b23.tv" in url:
        from util.parse.parser.b23 import B23Parser

        return B23Parser().parse(url)
    return url


def _available_qualities(play_data: dict) -> list[tuple[int, str]]:
    """Return streams the current account can actually download, highest first."""
    accepted_ids = [int(value) for value in play_data.get("accept_quality") or []]
    accepted_names = [str(value) for value in play_data.get("accept_description") or []]
    names = {
        quality_id: accepted_names[index]
        for index, quality_id in enumerate(accepted_ids)
        if index < len(accepted_names)
    }
    stream_ids = sorted(
        {
            int(stream.get("id", 0))
            for stream in (play_data.get("dash") or {}).get("video", [])
            if int(stream.get("id", 0)) > 0
        },
        reverse=True,
    )
    if not stream_ids and int(play_data.get("quality") or 0) > 0:
        stream_ids = [int(play_data["quality"])]
    return [(quality_id, names.get(quality_id, str(quality_id))) for quality_id in stream_ids]


def parse_video(url: str, data_dir: Path) -> dict:
    from util.network.request import ResponseType, SyncNetWorkRequest
    from util.parse.parser.video import VideoParser

    _prepare_wbi()
    url = _normalize_url(url)
    parser = VideoParser()
    response = parser.parse(url, get_info_data=True)
    data = response["data"]
    pages = data.get("pages") or [
        {
            "cid": data["cid"],
            "page": 1,
            "part": data.get("title", "P1"),
            "duration": data.get("duration", 0),
        }
    ]

    first_cid = pages[0]["cid"]
    params = {
        "bvid": data["bvid"],
        "cid": first_cid,
        "qn": 127,
        "fnval": 4048,
        "fourk": 1,
    }
    play_url = f"https://api.bilibili.com/x/player/wbi/playurl?{parser.enc_wbi(params)}"
    play_response = SyncNetWorkRequest(play_url).run()
    parser.check_response(play_response)
    play_data = play_response["data"]
    qualities = _available_qualities(play_data)

    preview_cache = data_dir / "preview-cache"
    preview_cache.mkdir(parents=True, exist_ok=True)
    cover_path = preview_cache / f"{data['bvid']}-cover.jpg"
    owner_path = preview_cache / f"{data['bvid']}-owner.jpg"
    for asset_url, destination in (
        (data.get("pic", ""), cover_path),
        ((data.get("owner") or {}).get("face", ""), owner_path),
    ):
        if asset_url:
            try:
                destination.write_bytes(
                    SyncNetWorkRequest(asset_url, response_type=ResponseType.BYTES).run()
                )
            except Exception:
                pass
    try:
        tags_response = SyncNetWorkRequest(
            f"https://api.bilibili.com/x/tag/archive/tags?bvid={data['bvid']}"
        ).run()
        tags = [item.get("tag_name", "") for item in tags_response.get("data") or [] if item.get("tag_name")]
    except Exception:
        tags = []

    collection = data.get("ugc_season") or {}
    collection_sections = collection.get("sections") or []
    if collection_sections:
        parts = []
        for section in collection_sections:
            section_title = section.get("title", "")
            for episode in section.get("episodes") or []:
                episode_bvid = episode.get("bvid", "")
                episode_pages = episode.get("pages") or []
                if len(episode_pages) > 1:
                    for page in episode_pages:
                        parts.append({
                            "cid": page["cid"],
                            "page": page.get("page", 1),
                            "title": f"{episode.get('title', episode_bvid)} · {page.get('part', '')}".strip(" ·"),
                            "duration": page.get("duration", 0),
                            "source_url": f"https://www.bilibili.com/video/{episode_bvid}?p={page.get('page', 1)}",
                            "bvid": episode_bvid,
                            "section_title": section_title,
                        })
                else:
                    page = episode_pages[0] if episode_pages else episode
                    parts.append({
                        "cid": episode.get("cid") or page.get("cid"),
                        "page": page.get("page", 1),
                        "title": episode.get("title") or page.get("part") or episode_bvid,
                        "duration": episode.get("duration") or (episode.get("arc") or {}).get("duration") or page.get("duration", 0),
                        "source_url": f"https://www.bilibili.com/video/{episode_bvid}",
                        "bvid": episode_bvid,
                        "section_title": section_title,
                    })
    else:
        parts = [
            {
                "cid": page["cid"],
                "page": page.get("page", index + 1),
                "title": page.get("part") or f"P{index + 1}",
                "duration": page.get("duration", 0),
                "source_url": f"https://www.bilibili.com/video/{data['bvid']}?p={page.get('page', index + 1)}",
                "bvid": data["bvid"],
                "section_title": "",
            }
            for index, page in enumerate(pages)
        ]

    return {
        "source_url": url,
        "bvid": data["bvid"],
        "aid": data.get("aid"),
        "title": data.get("title", data["bvid"]),
        "cover_url": data.get("pic", ""),
        "owner_name": (data.get("owner") or {}).get("name", ""),
        "owner_face_url": (data.get("owner") or {}).get("face", ""),
        "cover_path": str(cover_path) if cover_path.is_file() else "",
        "owner_face_path": str(owner_path) if owner_path.is_file() else "",
        "description": data.get("desc", ""),
        "published_at": int(data.get("pubdate", 0) or 0),
        "category": data.get("tname", ""),
        "stats": data.get("stat") or {},
        "tags": tags,
        "collection_title": collection.get("title", ""),
        "parts": parts,
        "qualities": [{"id": quality_id, "name": name} for quality_id, name in qualities],
    }


def _write_progress(path: Path | None, percent: int, status: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"percent": max(0, min(100, percent)), "status": status}),
        encoding="utf-8",
    )
    temporary.replace(path)


def _stream_to_file(urls: list[str], destination: Path, progress=None) -> None:
    from util.common.config import config
    from util.network.request import get_client

    headers = {
        "Referer": "https://www.bilibili.com/",
        "User-Agent": config.get(config.user_agent),
    }
    last_error: Exception | None = None
    for url in urls:
        try:
            with get_client().stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0) or 0)
                received = 0
                with destination.open("wb") as stream:
                    for chunk in response.iter_bytes(1024 * 1024):
                        stream.write(chunk)
                        received += len(chunk)
                        if progress is not None:
                            progress(received, total)
                if progress is not None:
                    progress(received, received)
            return
        except Exception as error:
            last_error = error
            destination.unlink(missing_ok=True)
    raise RuntimeError(f"媒体流下载失败：{last_error}")


def _stream_urls(stream: dict) -> list[str]:
    primary = stream.get("baseUrl") or stream.get("base_url")
    backups = stream.get("backupUrl") or stream.get("backup_url") or []
    return [url for url in [primary, *backups] if url]


def _fetch_player_data(parser, data: dict, cid: int) -> dict:
    from util.network.request import SyncNetWorkRequest

    params = {
        "bvid": data["bvid"],
        "cid": cid,
        "dm_img_list": "[]",
        "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
        "dm_cover_img_str": "QU5HTEUgKE5WSURJQSwgTlZJRElBIEdlRm9yY2UgUlRYIDQwNjAgTGFwdG9wIEdQVSAoMHgwMDAwMjhFMCkgRGlyZWN0M0QxMSB2c181XzAgcHNfNV8wLCBEM0QxMSlHb29nbGUgSW5jLiAoTlZJRElBKQ",
        "dm_img_inter": '{"ds":[],"wh":[5231,6067,75],"of":[475,950,475]}',
    }
    response = SyncNetWorkRequest(
        f"https://api.bilibili.com/x/player/wbi/v2?{parser.enc_wbi(params)}"
    ).run()
    if response.get("code") != 0:
        return {}
    return response.get("data") or {}


def _chapters_from_player_data(player_data: dict, duration: int | float = 0) -> list[dict]:
    points = player_data.get("view_points") or []
    chapters: list[dict] = []
    for index, entry in enumerate(points):
        try:
            start = float(entry.get("from", 0) or 0)
            end = float(entry.get("to", 0) or 0)
        except (TypeError, ValueError):
            continue
        if end <= start:
            if index + 1 < len(points):
                try:
                    end = float(points[index + 1].get("from", 0) or 0)
                except (TypeError, ValueError):
                    end = 0
            elif duration:
                end = float(duration)
        if end <= start:
            continue
        chapters.append({
            "title": str(entry.get("content") or f"章节 {index + 1}"),
            "start": start,
            "end": end,
        })
    return chapters


def _download_subtitles(player_data: dict, output_dir: Path) -> list[dict]:
    from util.network.request import SyncNetWorkRequest

    saved = []
    for index, entry in enumerate(player_data.get("subtitle", {}).get("subtitles", [])):
        url = entry.get("subtitle_url", "")
        if not url:
            continue
        if url.startswith("//"):
            url = "https:" + url
        language = str(entry.get("lan") or f"track-{index + 1}")
        safe_language = re.sub(r"[^a-zA-Z0-9_-]+", "-", language).strip("-") or f"track-{index + 1}"
        subtitle_data = SyncNetWorkRequest(url).run()
        filename = f"subtitle-{safe_language}.json"
        (output_dir / filename).write_text(
            json.dumps(subtitle_data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        saved.append({
            "file": filename,
            "language": language,
            "name": entry.get("lan_doc") or language,
            "ai_generated": language.casefold().startswith("ai-"),
        })
    return saved


def download_video(
    url: str,
    cid: int,
    quality_id: int,
    output_dir: Path,
    ffmpeg_path: Path | None = None,
    progress_path: Path | None = None,
) -> dict:
    from util.network.request import ResponseType, SyncNetWorkRequest
    from util.parse.parser.video import VideoParser

    _prepare_wbi()
    url = _normalize_url(url)
    parser = VideoParser()
    response = parser.parse(url, get_info_data=True)
    data = response["data"]
    page = next((item for item in data.get("pages", []) if int(item["cid"]) == cid), None)
    if page is None and int(data.get("cid", 0)) == cid:
        page = {"cid": cid, "page": 1, "part": data.get("title", "P1"), "duration": data.get("duration", 0)}
    if page is None:
        raise RuntimeError("所选分 P 已不存在，请重新解析链接")

    params = {"bvid": data["bvid"], "cid": cid, "qn": quality_id, "fnval": 4048, "fourk": 1}
    play_url = f"https://api.bilibili.com/x/player/wbi/playurl?{parser.enc_wbi(params)}"
    play_response = SyncNetWorkRequest(play_url).run()
    parser.check_response(play_response)
    dash = play_response["data"].get("dash") or {}
    videos = dash.get("video") or []
    if not videos:
        raise RuntimeError("这个视频没有返回可下载的 DASH 视频流")

    exact = [item for item in videos if int(item.get("id", 0)) == quality_id]
    candidates = exact or sorted(videos, key=lambda item: int(item.get("id", 0)), reverse=True)
    video = next(
        (item for item in candidates if str(item.get("codecs", "")).startswith("avc")),
        candidates[0],
    )
    audios = dash.get("audio") or []
    audio = max(audios, key=lambda item: int(item.get("bandwidth", 0))) if audios else None

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_progress(progress_path, 0, "正在下载视频")
    _stream_to_file(
        _stream_urls(video),
        output_dir / "video.mp4",
        lambda current, total: _write_progress(
            progress_path,
            round(current / total * 84) if total else 0,
            "正在下载视频",
        ),
    )
    if audio:
        _stream_to_file(
            _stream_urls(audio),
            output_dir / "audio.m4a",
            lambda current, total: _write_progress(
                progress_path,
                84 + (round(current / total * 12) if total else 0),
                "正在下载音频",
            ),
        )
        if ffmpeg_path and ffmpeg_path.is_file():
            _write_progress(progress_path, 97, "正在封装视频")
            merged = output_dir / "merged.mp4"
            subprocess.run(
                [
                    str(ffmpeg_path),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(output_dir / "video.mp4"),
                    "-i",
                    str(output_dir / "audio.m4a"),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c",
                    "copy",
                    str(merged),
                ],
                check=True,
            )
            (output_dir / "video.mp4").unlink()
            (output_dir / "audio.m4a").unlink()
            merged.rename(output_dir / "video.mp4")

    danmaku = SyncNetWorkRequest(
        f"https://comment.bilibili.com/{cid}.xml",
        response_type=ResponseType.TEXT,
    ).run()
    _write_progress(progress_path, 98, "正在保存弹幕和封面")
    (output_dir / "danmaku.xml").write_text(danmaku, encoding="utf-8")

    assets = {
        "cover.jpg": data.get("pic", ""),
        "avatar.jpg": (data.get("owner") or {}).get("face", ""),
    }
    for filename, asset_url in assets.items():
        if asset_url:
            content = SyncNetWorkRequest(asset_url, response_type=ResponseType.BYTES).run()
            (output_dir / filename).write_bytes(content)

    try:
        player_data = _fetch_player_data(parser, data, cid)
    except Exception:
        player_data = {}
    try:
        subtitles = _download_subtitles(player_data, output_dir)
    except Exception:
        subtitles = []
    chapters = _chapters_from_player_data(player_data, page.get("duration", 0))

    display_title = data.get("title", data["bvid"])
    if len(data.get("pages") or []) > 1:
        display_title = f"{display_title} · P{page.get('page', 1)} {page.get('part', '')}".strip()
    result = {
        "video_unit_id": f"{data['bvid']}-{cid}",
        "source_url": url,
        "bvid": data["bvid"],
        "aid": data.get("aid"),
        "cid": cid,
        "page": page.get("page", 1),
        "title": display_title,
        "series_title": data.get("title", data["bvid"]),
        "part_title": page.get("part", ""),
        "duration": page.get("duration", 0),
        "owner_name": (data.get("owner") or {}).get("name", ""),
        "subtitles": subtitles,
        "chapters": chapters,
        "quality_id": int(video.get("id", 0)),
        "codec": video.get("codecs", ""),
    }
    _write_progress(progress_path, 100, "已完成并校验")
    return result


def login_with_qrcode(data_dir: Path) -> dict:
    from util.auth.base import AuthBase
    from util.network.request import ResponseType, SyncNetWorkRequest

    params = {
        "source": "main-fe-header",
        "go_url": "https://www.bilibili.com/",
        "web_location": "333.1007",
    }
    response = SyncNetWorkRequest(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?" + urlencode(params)
    ).run()
    if response.get("code") != 0:
        raise RuntimeError(response.get("message") or "无法生成登录二维码")
    data = response["data"]
    _emit_event({"type": "qrcode", "url": data["url"]})

    poll_url = (
        "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key="
        + data["qrcode_key"]
    )
    previous_code = None
    while True:
        poll = SyncNetWorkRequest(poll_url).run()
        if poll.get("code") != 0:
            raise RuntimeError(poll.get("message") or "二维码状态查询失败")
        status = poll["data"]
        code = int(status["code"])
        if code != previous_code:
            _emit_event({"type": "status", "code": code, "message": status.get("message", "")})
            previous_code = code
        if code == 0:
            AuthBase().update_cookies()
            nav = SyncNetWorkRequest("https://api.bilibili.com/x/web-interface/nav").run()
            user = nav.get("data") or {}
            profile = {
                "username": user.get("uname", ""),
                "uid": user.get("mid"),
                "avatar_url": user.get("face", ""),
            }
            account_dir = data_dir / "account"
            account_dir.mkdir(parents=True, exist_ok=True)
            (account_dir / "profile.json").write_text(
                json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if profile["avatar_url"]:
                try:
                    avatar = SyncNetWorkRequest(
                        profile["avatar_url"], response_type=ResponseType.BYTES
                    ).run()
                    (account_dir / "avatar.jpg").write_bytes(avatar)
                except Exception:
                    pass
            return profile
        if code == 86038:
            raise RuntimeError("二维码已过期，请重新生成")
        time.sleep(1)


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--vendor-src", required=True, type=Path)
    argument_parser.add_argument("--data-dir", required=True, type=Path)
    argument_parser.add_argument("--url")
    argument_parser.add_argument("--operation", choices=("parse", "download", "login"), default="parse")
    argument_parser.add_argument("--cid", type=int)
    argument_parser.add_argument("--quality", type=int)
    argument_parser.add_argument("--output", type=Path)
    argument_parser.add_argument("--ffmpeg", type=Path)
    argument_parser.add_argument("--progress-file", type=Path)
    args = argument_parser.parse_args()
    _bootstrap(args.vendor_src, args.data_dir)
    try:
        if args.operation == "parse":
            if not args.url:
                raise ValueError("解析操作缺少 url")
            result = {"ok": True, "preview": parse_video(args.url, args.data_dir)}
        elif args.operation == "download":
            if args.cid is None or args.quality is None or args.output is None:
                raise ValueError("下载操作缺少 cid、quality 或 output")
            if not args.url:
                raise ValueError("下载操作缺少 url")
            result = {
                "ok": True,
                "download": download_video(
                    args.url,
                    args.cid,
                    args.quality,
                    args.output,
                    args.ffmpeg,
                    args.progress_file,
                ),
            }
        else:
            result = {"ok": True, "login": login_with_qrcode(args.data_dir)}
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    # ASCII-only transport avoids Windows pipe code-page corruption for Chinese metadata.
    print(RESULT_PREFIX + json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
