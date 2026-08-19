from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import shutil
import subprocess
import urllib.request


ARCHIVE_NAME = "mpv-dev-x86_64-20260809-git-dd5d17d328.7z"
ARCHIVE_URL = (
    "https://sourceforge.net/projects/mpv-player-windows/files/libmpv/"
    f"{ARCHIVE_NAME}/download"
)
ARCHIVE_SHA256 = "c6aebf40bb722efe79090bfeb61e68625f0837770347e5a8b610aef78900cf12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    destination = root / "tools" / "mpv"
    destination.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="offline-bili-mpv-") as temp_name:
        temp = Path(temp_name)
        archive = temp / ARCHIVE_NAME
        print(f"Downloading {ARCHIVE_NAME}...")
        urllib.request.urlretrieve(ARCHIVE_URL, archive)
        actual_hash = sha256(archive)
        if actual_hash != ARCHIVE_SHA256:
            raise RuntimeError(f"Archive hash mismatch: {actual_hash}")

        extracted = temp / "extracted"
        extracted.mkdir()
        # Windows 11 ships bsdtar; unlike py7zr, it supports this archive's BCJ2 filter.
        subprocess.run(
            ["tar", "-xf", str(archive), "-C", str(extracted)],
            check=True,
        )

        candidates = list(extracted.rglob("libmpv-2.dll"))
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one libmpv-2.dll, found {len(candidates)}")
        shutil.copy2(candidates[0], destination / "libmpv-2.dll")
        print(f"Installed libmpv-2.dll (archive sha256: {actual_hash})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
