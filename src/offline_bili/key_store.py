from __future__ import annotations

from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import secrets


CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class DeviceKeyStore:
    def __init__(self, path: Path):
        self.path = path

    def load_or_create(self) -> bytes:
        if os.name != "nt":
            raise RuntimeError("Device-bound integrity keys require Windows")
        if self.path.exists():
            return _unprotect(self.path.read_bytes())

        key = secrets.token_bytes(32)
        protected = _protect(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(protected)
        return key


def _protect(value: bytes) -> bytes:
    return _crypt(value, protect=True)


def _unprotect(value: bytes) -> bytes:
    return _crypt(value, protect=False)


def _crypt(value: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(
        len(value),
        ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output = _DataBlob()

    if protect:
        function = crypt32.CryptProtectData
        arguments = (
            ctypes.byref(source),
            "Offline Bili integrity key",
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
    else:
        function = crypt32.CryptUnprotectData
        description = wintypes.LPWSTR()
        arguments = (
            ctypes.byref(source),
            ctypes.byref(description),
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )

    if not function(*arguments):
        error = ctypes.get_last_error()
        raise OSError(error, "Windows could not unlock the device-bound key")

    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)

