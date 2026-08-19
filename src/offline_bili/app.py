from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .history import HistoryStore
from .key_store import DeviceKeyStore
from .library import ManagedLibrary
from .paths import AppPaths
from .settings import SettingsStore
from .ui import MainWindow, apply_theme


def build_window(paths: AppPaths | None = None) -> MainWindow:
    paths = paths or AppPaths.discover()
    paths.ensure()
    settings_store = SettingsStore(paths.data / "settings.json")
    settings = settings_store.load()
    library_path = Path(settings.library_path).expanduser() if settings.library_path else paths.library
    key = DeviceKeyStore(paths.data / "integrity.key").load_or_create()
    library = ManagedLibrary(library_path, key)
    scan = library.scan()
    history = HistoryStore(paths.data / "history.db")
    return MainWindow(
        scan,
        history,
        settings,
        settings_store,
        paths.tools,
        paths.data / "cache",
        paths.root,
        paths.data,
        library,
    )


def main() -> int:
    if "--bili23-helper" in sys.argv:
        sys.argv.remove("--bili23-helper")
        from .bili23_helper import main as helper_main

        return helper_main()
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Offline Bili")
    try:
        window = build_window()
    except OSError as error:
        QMessageBox.critical(None, "无法读取本机密钥", str(error))
        return 1
    application.setWindowIcon(window.windowIcon())
    apply_theme(window)
    window.show()
    return application.exec()
