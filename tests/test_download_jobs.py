from offline_bili.bili23_adapter import VideoPartPreview, VideoPreview
from offline_bili.download import DownloadRequest
from offline_bili.download_jobs import DownloadJobStore


def _request():
    part = VideoPartPreview(cid=9, page=1, title="第一集", duration=60)
    preview = VideoPreview(
        source_url="https://www.bilibili.com/video/BV1-test",
        bvid="BV1-test",
        aid=1,
        title="测试视频",
        cover_url="",
        owner_name="UP",
        owner_face_url="",
        parts=(part,),
        qualities=(),
        cover_path="data/bili23/preview-cache/BV1-test-cover.jpg",
        owner_face_path="data/bili23/preview-cache/BV1-test-owner.jpg",
        description="一段简介",
        published_at=1_750_000_000,
        category="知识",
        stats={"view": 1234},
        tags=("数学",),
    )
    return DownloadRequest(preview, part, 80)


def test_running_job_is_recoverable_after_restart(tmp_path):
    path = tmp_path / "jobs.json"
    store = DownloadJobStore(path)
    job = store.add((_request(),))[0]
    store.set_status(job.job_id, "running")

    recovered = DownloadJobStore(path).list_jobs()[0]

    assert recovered.status == "failed"
    assert "中断" in recovered.error
    assert recovered.request.part.cid == 9
    assert recovered.request.preview.cover_path.endswith("BV1-test-cover.jpg")
    assert recovered.request.preview.description == "一段简介"
    assert recovered.request.preview.stats["view"] == 1234
    assert recovered.request.preview.tags == ("数学",)


def test_completed_job_can_be_removed(tmp_path):
    store = DownloadJobStore(tmp_path / "jobs.json")
    job = store.add((_request(),))[0]
    store.set_status(job.job_id, "completed")
    store.remove({job.job_id})

    assert store.list_jobs() == ()
