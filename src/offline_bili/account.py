from __future__ import annotations

import json
import shutil
from pathlib import Path


def login_config_path(data_dir: Path) -> Path:
    return data_dir / "bili23" / "config.json"


def profile_path(data_dir: Path) -> Path:
    return data_dir / "account" / "profile.json"


def avatar_path(data_dir: Path) -> Path:
    return data_dir / "account" / "avatar.jpg"


def has_login(data_dir: Path) -> bool:
    try:
        data = json.loads(login_config_path(data_dir).read_text(encoding="utf-8"))
        cookies = data.get("Cookie", {})
        return bool(cookies.get("is_login") and cookies.get("SESSDATA"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def load_profile(data_dir: Path) -> dict:
    try:
        return json.loads(profile_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def import_legacy_data(old_root: Path, data_dir: Path) -> None:
    old_data = old_root / "data"
    source_config = login_config_path(old_data)
    if not source_config.is_file():
        source_config = old_data / "bili23" / "Bili23 Downloader" / "config.json"
    if not source_config.is_file():
        raise ValueError("所选文件夹里没有可迁移的旧版登录信息")
    destination_config = login_config_path(data_dir)
    destination_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_config, destination_config)
    for relative in (Path("account/profile.json"), Path("account/avatar.jpg")):
        source = old_data / relative
        if source.is_file():
            destination = data_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
