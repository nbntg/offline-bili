# Third-party components

## Bili23 Downloader

- Upstream: https://github.com/ScottSloan/Bili23-Downloader
- Pinned commit: `2d3ff2cadd7783a38870e1cfd3f6a9914d00bea0` (version 2.14.0)
- License: GPL-3.0
- Local change: `util/common/config.py` honors `OFFLINE_BILI_BILI23_DATA`, keeping its configuration inside this portable application's data directory.

The upstream source is kept under `vendor/Bili23-Downloader`. Offline Bili invokes the adapted parsing/downloading boundary in an isolated helper process.

## mpv / libmpv

- Project: https://mpv.io/
- Windows build source: https://sourceforge.net/projects/mpv-player-windows/files/libmpv/
- Pinned archive: `mpv-dev-x86_64-20260809-git-dd5d17d328.7z`
- Archive SHA-256: `c6aebf40bb722efe79090bfeb61e68625f0837770347e5a8b610aef78900cf12`
- License: GPLv2+ build

The development fetch script installs only `libmpv-2.dll` into `tools/mpv` for portable packaging.

## FFmpeg

- Project: https://ffmpeg.org/
- Windows build source: https://github.com/BtbN/FFmpeg-Builds
- Pinned release: `autobuild-2026-08-17-13-05`
- Pinned archive: `ffmpeg-N-126188-g426841da9d-win64-gpl.zip`
- Archive SHA-256: `423d30b197e52e20e0702278a30bc63e006cc383c968935874c4c13dda9eb299`
- License: GPLv3 build

The development fetch script installs `ffmpeg.exe` into `tools/ffmpeg`. It remuxes Bilibili's separate DASH video and audio streams into the default MP4 without re-encoding.
