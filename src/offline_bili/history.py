from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True)
class HistoryEntry:
    video_unit_id: str
    position_seconds: float
    duration_seconds: float
    completed: bool
    last_played_at: int


class HistoryStore:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._initialize()

    def record_progress(
        self,
        video_unit_id: str,
        position_seconds: float,
        duration_seconds: float,
    ) -> HistoryEntry:
        completed = duration_seconds > 0 and position_seconds / duration_seconds >= 0.99
        timestamp = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO history(video_unit_id, position_seconds, duration_seconds, completed, last_played_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(video_unit_id) DO UPDATE SET
                    position_seconds = excluded.position_seconds,
                    duration_seconds = excluded.duration_seconds,
                    completed = excluded.completed,
                    last_played_at = excluded.last_played_at
                """,
                (video_unit_id, position_seconds, duration_seconds, int(completed), timestamp),
            )
        return HistoryEntry(video_unit_id, position_seconds, duration_seconds, completed, timestamp)

    def set_completed(self, video_unit_id: str, completed: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE history SET completed = ? WHERE video_unit_id = ?",
                (int(completed), video_unit_id),
            )

    def list_recent(self) -> tuple[HistoryEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT video_unit_id, position_seconds, duration_seconds, completed, last_played_at
                FROM history ORDER BY last_played_at DESC
                """
            ).fetchall()
        return tuple(HistoryEntry(row[0], row[1], row[2], bool(row[3]), row[4]) for row in rows)

    def get(self, video_unit_id: str) -> HistoryEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT video_unit_id, position_seconds, duration_seconds, completed, last_played_at
                FROM history WHERE video_unit_id = ?
                """,
                (video_unit_id,),
            ).fetchone()
        return HistoryEntry(row[0], row[1], row[2], bool(row[3]), row[4]) if row else None

    def delete(self, video_unit_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM history WHERE video_unit_id = ?", (video_unit_id,))

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM history")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS history(
                    video_unit_id TEXT PRIMARY KEY,
                    position_seconds REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    completed INTEGER NOT NULL,
                    last_played_at INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)
