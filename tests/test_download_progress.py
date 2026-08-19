from pathlib import Path
from types import SimpleNamespace

from offline_bili.download import DownloadThread


class FakeCoordinator:
    def download(self, _request, _cancelled, progress):
        progress(42, "正在下载视频")
        progress(100, "已完成并校验")
        return Path("finished")


def test_download_thread_forwards_media_and_batch_progress():
    request = SimpleNamespace(part=SimpleNamespace(title="测试视频"))
    thread = DownloadThread(FakeCoordinator(), (("job-1", request),))
    events = []
    thread.progress.connect(lambda *event: events.append(event))

    thread.run()

    assert events[0] == (1, 1, 0, "测试视频")
    assert (1, 1, 42, "测试视频 · 正在下载视频") in events
    assert events[-1] == (1, 1, 100, "测试视频")
