from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


def _require_child(root: Path, target: Path) -> None:
    target.resolve().relative_to(root.resolve())


def main() -> int:
    helper_only = "--helper-only" in sys.argv
    package_only = "--package-only" in sys.argv
    root = Path(__file__).resolve().parents[1]
    output_root = (root / "build" / "portable").resolve()
    _require_child(root, output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    dist_path = output_root / "dist"
    work_path = output_root / "work"
    spec_path = output_root / "spec"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "OfflineBili",
        "--icon",
        str(root / "assets" / "offline-bili.ico"),
        "--paths",
        str(root / "src"),
        "--distpath",
        str(dist_path),
        "--workpath",
        str(work_path),
        "--specpath",
        str(spec_path),
        "--hidden-import",
        "httpx",
        "--hidden-import",
        "orjson",
        "--hidden-import",
        "psutil",
        "--hidden-import",
        "google.protobuf",
        "--hidden-import",
        "qfluentwidgets",
        "--collect-all",
        "qfluentwidgets",
        str(root / "src" / "offline_bili" / "__main__.py"),
    ]
    if not helper_only and not package_only:
        subprocess.run(command, cwd=root, check=True)

    package = dist_path / "OfflineBili"
    if not package.is_dir():
        raise RuntimeError("GUI package does not exist; run a full portable build first")
    helper_dist = output_root / "helper-dist"
    helper_command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--console",
        "--name",
        "OfflineBiliHelper",
        "--paths",
        str(root / "src"),
        "--distpath",
        str(helper_dist),
        "--workpath",
        str(output_root / "helper-work"),
        "--specpath",
        str(output_root / "helper-spec"),
        "--hidden-import",
        "httpx",
        "--hidden-import",
        "orjson",
        "--hidden-import",
        "psutil",
        "--hidden-import",
        "google.protobuf",
        "--hidden-import",
        "sqlite3",
        "--hidden-import",
        "qfluentwidgets",
        "--collect-all",
        "qfluentwidgets",
        str(root / "src" / "offline_bili" / "helper_main.py"),
    ]
    if not package_only:
        subprocess.run(helper_command, cwd=root, check=True)
        shutil.copytree(
            helper_dist / "OfflineBiliHelper",
            package / "helper",
            dirs_exist_ok=True,
        )

    shutil.copytree(
        root / "vendor" / "Bili23-Downloader" / "src",
        package / "vendor" / "Bili23-Downloader" / "src",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(root / "tools", package / "tools", dirs_exist_ok=True)
    shutil.copytree(root / "assets", package / "assets", dirs_exist_ok=True)
    shutil.copy2(
        root / "vendor" / "Bili23-Downloader" / "LICENSE",
        package / "vendor" / "Bili23-Downloader" / "LICENSE",
    )
    for filename in ("README.md", "THIRD_PARTY.md", "LICENSE"):
        shutil.copy2(root / filename, package / filename)
    for dirname in ("data", "library", "logs"):
        portable_data = package / dirname
        _require_child(output_root, portable_data)
        if portable_data.exists():
            shutil.rmtree(portable_data)
        portable_data.mkdir()

    archive_base = output_root / "OfflineBili-Windows-x64"
    archive = shutil.make_archive(str(archive_base), "zip", dist_path, "OfflineBili")
    print(f"Portable package: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
