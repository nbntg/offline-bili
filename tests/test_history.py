from offline_bili.history import HistoryStore


def test_completion_threshold_is_99_percent(tmp_path):
    store = HistoryStore(tmp_path / "history.db")

    unfinished = store.record_progress("video-1", 98.9, 100)
    finished = store.record_progress("video-2", 99.0, 100)

    assert not unfinished.completed
    assert finished.completed


def test_manual_status_change_does_not_delete_history(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.record_progress("video-1", 20, 100)

    store.set_completed("video-1", True)

    assert store.list_recent()[0].completed


def test_history_entry_can_be_looked_up_and_deleted(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.record_progress("video-1", 20, 100)

    assert store.get("video-1").position_seconds == 20
    store.delete("video-1")

    assert store.get("video-1") is None
