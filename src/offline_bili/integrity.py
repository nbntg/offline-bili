from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
import hashlib
import hmac
import json


MANIFEST_NAME = ".offline-bili.json"
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    reason: str = ""
    manifest: dict[str, Any] | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_manifest(
    package_dir: Path,
    video_unit_id: str,
    metadata: dict[str, Any],
    relative_files: Iterable[str],
    key: bytes,
) -> Path:
    package_dir = package_dir.resolve()
    files = []
    seen: set[str] = set()

    for relative in sorted(relative_files):
        normalized = _safe_relative_path(relative)
        if normalized == MANIFEST_NAME or normalized in seen:
            raise ValueError(f"Invalid manifest file entry: {relative}")
        seen.add(normalized)

        full_path = (package_dir / Path(normalized)).resolve()
        _require_within(package_dir, full_path)
        if not full_path.is_file():
            raise FileNotFoundError(full_path)

        stat = full_path.stat()
        files.append(
            {
                "path": normalized,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(full_path),
            }
        )

    payload = {
        "version": MANIFEST_VERSION,
        "video_unit_id": video_unit_id,
        "metadata": metadata,
        "files": files,
    }
    document = {**payload, "signature": _sign(payload, key)}
    manifest_path = package_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path


def verify_package(package_dir: Path, key: bytes) -> VerificationResult:
    package_dir = package_dir.resolve()
    manifest_path = package_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return VerificationResult(False, "missing manifest")

    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        signature = document.pop("signature")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return VerificationResult(False, "invalid manifest")

    if document.get("version") != MANIFEST_VERSION:
        return VerificationResult(False, "unsupported manifest version")
    if not hmac.compare_digest(str(signature), _sign(document, key)):
        return VerificationResult(False, "invalid manifest signature")

    entries = document.get("files")
    if not isinstance(entries, list):
        return VerificationResult(False, "invalid file list")

    expected: set[str] = set()
    try:
        for entry in entries:
            relative = _safe_relative_path(entry["path"])
            if relative in expected:
                return VerificationResult(False, "duplicate file entry")
            expected.add(relative)

            full_path = (package_dir / Path(relative)).resolve()
            _require_within(package_dir, full_path)
            if not full_path.is_file():
                return VerificationResult(False, f"missing file: {relative}")
            if full_path.stat().st_size != entry["size"]:
                return VerificationResult(False, f"size mismatch: {relative}")
            if sha256_file(full_path) != entry["sha256"]:
                return VerificationResult(False, f"hash mismatch: {relative}")
    except (KeyError, TypeError, ValueError, OSError):
        return VerificationResult(False, "invalid file entry")

    actual = {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    }
    if actual != expected:
        return VerificationResult(False, "unrecorded or missing files")

    return VerificationResult(True, manifest={**document, "signature": signature})


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sign(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical_json(payload), hashlib.sha256).hexdigest()


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("unsafe relative path")
    return path.as_posix()


def _require_within(root: Path, child: Path) -> None:
    try:
        child.relative_to(root)
    except ValueError as error:
        raise ValueError("path escapes package directory") from error

