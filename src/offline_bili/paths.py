from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys


@dataclass(frozen=True)
class AppPaths:
    root: Path
    app: Path
    data: Path
    library: Path
    logs: Path
    tools: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        override = os.environ.get("OFFLINE_BILI_HOME")
        if override:
            root = Path(override).expanduser().resolve()
        elif getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            root = Path(__file__).resolve().parents[2]

        return cls.from_root(root)

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        root = root.resolve()
        return cls(
            root=root,
            app=root / "app",
            data=root / "data",
            library=root / "library",
            logs=root / "logs",
            tools=root / "tools",
        )

    def ensure(self) -> None:
        for directory in (self.app, self.data, self.library, self.logs, self.tools):
            directory.mkdir(parents=True, exist_ok=True)

