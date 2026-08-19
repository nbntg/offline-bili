from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import hashlib
import shutil
import urllib.request


ARCHIVE_NAME = "ffmpeg-N-126188-g426841da9d-win64-gpl.zip"
ARCHIVE_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-08-17-13-05/" + ARCHIVE_NAME
)
ARCHIVE_SHA256 = "423d30b197e52e20e0702278a30bc63e006cc383c968935874c4c13dda9eb299"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    destination = root / "tools" / "ffmpeg"
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="offline-bili-ffmpeg-") as temp_name:
        archive = Path(temp_name) / ARCHIVE_NAME
        print(f"Downloading {ARCHIVE_NAME}...")
        urllib.request.urlretrieve(ARCHIVE_URL, archive)
        actual_hash = sha256(archive)
        if actual_hash != ARCHIVE_SHA256:
            raise RuntimeError(f"Archive hash mismatch: {actual_hash}")
        with ZipFile(archive) as bundle:
            executable = next(name for name in bundle.namelist() if name.endswith("/bin/ffmpeg.exe"))
            with bundle.open(executable) as source, (destination / "ffmpeg.exe").open("wb") as target:
                shutil.copyfileobj(source, target)
        print(f"Installed ffmpeg.exe (archive sha256: {actual_hash})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
