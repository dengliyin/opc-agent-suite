import threading
import time
from pathlib import Path
from dataclasses import replace

import pytest
from agent.config import Settings
from agent.files import character_image_path, storyboard_image_path, video_output_path
from agent.markdown_parser import Segment
from agent.product_lock import write_storyboard_product_lock_meta
from agent.tasks import JobManager
from PIL import Image


class FakeImageClient:
    def __init__(self):
        self.prompt_calls = []
        self.reference_calls = []

    def generate_from_prompt(self, prompt, output_path, progress=None):
        self.prompt_calls.append((prompt, output_path))
        if progress:
            progress("fake progress")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 768), (255, 255, 255)).save(output_path)

    def generate_with_references(self, prompt, image_paths, output_path, progress=None):
        self.reference_calls.append((prompt, list(image_paths), output_path))
        if progress:
            progress("fake progress")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 768), (255, 255, 255)).save(output_path)


class SequencedImageClient:
    def __init__(self, sizes):
        self.sizes = list(sizes)
        self.prompt_calls = []
        self.reference_calls = []

    def _next_size(self):
        if len(self.sizes) > 1:
            return self.sizes.pop(0)
        return self.sizes[0]

    def generate_from_prompt(self, prompt, output_path, progress=None):
        self.prompt_calls.append((prompt, output_path))
        if progress:
            progress("fake progress")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", self._next_size(), (255, 255, 255)).save(output_path)

    def generate_with_references(self, prompt, image_paths, output_path, progress=None):
        self.reference_calls.append((prompt, list(image_paths), output_path))
        if progress:
            progress("fake progress")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", self._next_size(), (255, 255, 255)).save(output_path)


class FakeOmniClient:
    def __init__(self):
        self.calls = []

    def generate_video(self, prompt, storyboard_path, output_path, progress=None, reference_paths=None, duration=None):
        self.calls.append((prompt, storyboard_path, output_path, list(reference_paths or []), duration))
        if progress:
            progress("fake video progress")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mp4")


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        provider="omni",
        provider_label="Omni",
        api_base_path="/omni/api",
        otu_api_key="otu",
        otu_base_url="https://otuapi.com",
        image_model="image2",
        image_fallback_models=[],
        omni_model="omni_flash-10s",
        grok_api_key="grok",
        grok_base_url="https://www.runninghub.cn",
        grok_image_aspect_ratio="9:16",
        grok_image_resolution="4k",
        grok_video_aspect_ratio="9:16",
        grok_video_resolution="720p",
        grok_video_duration=10,
        image_size="4096x3072",
        video_size="720x1280",
        overwrite=False,
        script_root=tmp_path / "scripts",
        reference_root=tmp_path / "refs",
        video_output_root=tmp_path / "videos",
        image_retry_attempts=3,
        image_retry_base_seconds=0,
        image_reference_max_side=2048,
        image_reference_jpeg_quality=88,
    )


def test_start_queues_multiple_jobs_for_same_agent_in_order(tmp_path: Path) -> None:
    manager = JobManager(settings_for(tmp_path))
    started = []
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()

    def blocking_pipeline(job_id: str) -> None:
        started.append(job_id)
        if len(started) == 1:
            first_started.set()
            release_first.wait(timeout=3)
        else:
            second_started.set()
            release_second.wait(timeout=3)

    manager._run_pipeline = blocking_pipeline

    first = manager.start("characters", overwrite=False, script_paths=["/tmp/a.md"], script_concurrency=2)
    assert first_started.wait(timeout=2)
    second = manager.start("direct_videos", overwrite=False, script_paths=["/tmp/b.md"], script_concurrency=3)

    assert manager.get(first["id"])["status"] == "running"
    assert manager.get(second["id"])["status"] == "queued"
    assert first["queued_ahead"] == 0
    assert second["queued_ahead"] == 1
    assert not second_started.is_set()
    assert any("已加入队列，前方 1 个任务" in entry["message"] for entry in manager.get(second["id"])["logs"])

    release_first.set()
    assert second_started.wait(timeout=2)
    assert started == [first["id"], second["id"]]
    assert manager.get(second["id"])["status"] == "running"
    release_second.set()
    deadline = time.time() + 2
    while time.time() < deadline:
        if manager.get(first["id"])["status"] == "completed" and manager.get(second["id"])["status"] == "completed":
            break
        time.sleep(0.01)
    assert manager.get(first["id"])["status"] == "completed"
    assert manager.get(second["id"])["status"] == "completed"


def test_cancel_removes_waiting_job_from_queue(tmp_path: Path) -> None:
    manager = JobManager(settings_for(tmp_path))
    first_started = threading.Event()
    release_first = threading.Event()
    started = []

    def blocking_pipeline(job_id: str) -> None:
        started.append(job_id)
        first_started.set()
        release_first.wait(timeout=3)

    manager._run_pipeline = blocking_pipeline
    first = manager.start("characters", script_paths=["/tmp/a.md"])
    assert first_started.wait(timeout=2)
    second = manager.start("characters", script_paths=["/tmp/b.md"])

    canceled = manager.cancel(second["id"])

    assert canceled[0]["status"] == "canceled"
    assert any("已取消排队任务" in entry["message"] for entry in manager.get(second["id"])["logs"])
    release_first.set()
    deadline = time.time() + 2
    while time.time() < deadline and manager.get(first["id"])["status"] != "completed":
        time.sleep(0.01)
    assert started == [first["id"]]


def test_start_requires_and_records_product_sku_selection(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "LUX-轻奢戒指"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    first = settings.reference_root / "LUX-轻奢戒指-RG001.png"
    second = settings.reference_root / "LUX-轻奢戒指-RG002.png"
    first.write_bytes(b"image")
    second.write_bytes(b"image")
    md_path = product_dir / "script.md"
    md_path.write_text(
        "# Segment 1：00:00 - 00:10\n"
        "## A. 人物造型参考板提示词\n人物\n"
        "## B. 故事板图片提示词\n故事\n",
        encoding="utf-8",
    )
    manager = JobManager(settings)
    manager._submit_job = lambda _job_id: object()

    with pytest.raises(ValueError, match="请先选择本次使用的 SKU"):
        manager.start("storyboards", script_paths=[str(md_path)])

    job = manager.start(
        "storyboards",
        script_paths=[str(md_path)],
        reference_images={"LUX-轻奢戒指": str(second)},
    )

    assert job["reference_images"] == {"LUX-轻奢戒指": str(second.resolve())}


def test_process_character_logs_progress_with_job_id(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")

    segment = Segment(
        index=1,
        title="# Segment 1：00:00 - 00:01",
        time_range="00:00 - 00:01",
        raw_text='### 镜头 1\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_test"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "characters",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)

    image_client = FakeImageClient()
    result = manager._process_character(job_id, image_client, script, segment, overwrite=True)
    refreshed = manager.get(job_id)

    assert result == "已生成"
    assert len(image_client.prompt_calls) == 1
    assert "输出比例硬约束" in image_client.prompt_calls[0][0]
    assert image_client.prompt_calls[0][1] == product_dir / "script-片段1-人物图.png"
    assert image_client.reference_calls == []
    assert any("fake progress" in entry["message"] for entry in refreshed["logs"])


def test_process_character_retries_invalid_grok_aspect_and_keeps_only_valid_output(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        provider="grok",
        provider_label="Grok",
        api_base_path="/grok/api",
        grok_retry_attempts=2,
        grok_retry_base_seconds=0,
    )
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    segment = Segment(
        index=1,
        title="# Segment 1：00:00 - 00:01",
        time_range="00:00 - 00:01",
        raw_text="",
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_grok_character_validation"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "characters",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)
    image_client = SequencedImageClient([(1536, 1024), (720, 1280)])

    result = manager._process_character(job_id, image_client, script, segment, overwrite=True, image_api="grok", image_settings=settings)
    output = character_image_path(md_path, 1, settings.artifact_prefix)
    refreshed = manager.get(job_id)

    assert result == "已生成"
    assert len(image_client.prompt_calls) == 2
    assert "最终图片必须严格为 9:16" in image_client.prompt_calls[0][0]
    assert Image.open(output).size == (720, 1280)
    assert any("API返回图片不符合要求" in entry["message"] for entry in refreshed["logs"])


def test_process_character_removes_invalid_grok_output_after_retries(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        provider="grok",
        provider_label="Grok",
        api_base_path="/grok/api",
        grok_retry_attempts=2,
        grok_retry_base_seconds=0,
    )
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    segment = Segment(
        index=1,
        title="# Segment 1：00:00 - 00:01",
        time_range="00:00 - 00:01",
        raw_text="",
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_grok_character_validation_fail"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "characters",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)
    image_client = SequencedImageClient([(1536, 1024), (1536, 1024)])

    with pytest.raises(RuntimeError, match="API平台返回图片不符合要求"):
        manager._process_character(job_id, image_client, script, segment, overwrite=True, image_api="grok", image_settings=settings)

    assert len(image_client.prompt_calls) == 2
    assert not character_image_path(md_path, 1, settings.artifact_prefix).exists()


def test_process_storyboard_uses_only_product_reference_and_character(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    character = product_dir / "script-片段1-人物图.png"
    character.write_bytes(b"person")

    segment = Segment(
        index=1,
        title="# Segment 1：00:00 - 00:01",
        time_range="00:00 - 00:01",
        raw_text='### 镜头 1\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_storyboard"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "storyboards",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)
    image_client = FakeImageClient()

    result = manager._process_storyboard(job_id, image_client, script, segment, overwrite=True)
    refreshed = manager.get(job_id)

    assert result == "已生成"
    assert len(image_client.reference_calls) == 1
    assert image_client.reference_calls[0][1] == [reference, character]
    assert "产品视觉参考图 1 张 + 人物图 1 张" in [entry["message"] for entry in refreshed["logs"]][0]


def test_process_video_logs_progress_with_job_id(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    storyboard = product_dir / "script-片段1-故事版.png"
    storyboard.write_bytes(b"story")
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    write_storyboard_product_lock_meta(storyboard, "P1", reference, 1)

    segment = Segment(
        index=1,
        title="# Segment 1：00:00 - 00:01",
        time_range="00:00 - 00:01",
        raw_text='### 镜头 1\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_video"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "videos",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)
    omni_client = FakeOmniClient()

    result = manager._process_video(job_id, omni_client, script, segment, overwrite=True)
    refreshed = manager.get(job_id)

    assert result == "已生成"
    assert omni_client.calls
    assert "完整脚本" in omni_client.calls[0][0]
    assert "[音频文案]" in omni_client.calls[0][0]
    assert "hello" in omni_client.calls[0][0]
    assert "产品参考图强制锁定说明" not in omni_client.calls[0][0]
    assert any("故事版图 + 当前片段完整脚本" in entry["message"] for entry in refreshed["logs"])
    assert any("fake video progress" in entry["message"] for entry in refreshed["logs"])


def test_process_direct_video_uses_character_product_and_script_without_storyboard(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    character = product_dir / "script-片段1-人物图.png"
    character.write_bytes(b"person")
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")

    segment = Segment(
        index=1,
        title="# Segment 1：00:00 - 00:01",
        time_range="00:00 - 00:01",
        raw_text='### 镜头 1\n* **[时间段]** 00:00 - 00:01\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_direct_video"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "direct_videos",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)
    omni_client = FakeOmniClient()

    result = manager._process_direct_video(job_id, omni_client, script, segment, overwrite=True)
    refreshed = manager.get(job_id)

    assert result == "已生成"
    assert omni_client.calls
    prompt, primary_reference, _output, extra_references, duration = omni_client.calls[0]
    assert primary_reference == character
    assert extra_references == [reference]
    assert duration is None
    assert "严格按脚本中每个镜头的时间段" in prompt
    assert "不得省略任何镜头，不得重排镜头顺序" in prompt
    assert "hello" in prompt
    assert any("人物图 + 产品参考图 + 当前片段完整脚本" in entry["message"] for entry in refreshed["logs"])


def test_process_direct_video_supports_grok_duration_and_references(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        provider="grok",
        provider_label="Grok",
        api_base_path="/grok/api",
        video_output_root=tmp_path / "grok-videos",
        function_video_duration=10,
    )
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    character = product_dir / "script-片段1-人物图.png"
    Image.new("RGB", (720, 1280), (0, 0, 255)).save(character)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    segment = Segment(
        index=1,
        title="# Segment 1：00:00.000 - 00:08.000",
        time_range="00:00.000 - 00:08.000",
        raw_text='### 镜头 1\n* **[时间段]** 00:00.000 - 00:08.000\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_direct_grok"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "direct_videos",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)
    grok_client = FakeOmniClient()

    result = manager._process_direct_video(job_id, grok_client, script, segment, overwrite=True, video_api="grok", video_settings=settings)

    assert result == "已生成"
    prompt, primary_reference, _output, extra_references, duration = grok_client.calls[0]
    assert primary_reference == character
    assert extra_references == [reference]
    assert duration == 8
    assert "严格按脚本中每个镜头的时间段" in prompt


def test_process_direct_video_reports_missing_grok_character(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        provider="grok",
        provider_label="Grok",
        api_base_path="/grok/api",
        video_output_root=tmp_path / "grok-videos",
    )
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    segment = Segment(
        index=1,
        title="# Segment 1：00:00.000 - 00:08.000",
        time_range="00:00.000 - 00:08.000",
        raw_text='### 镜头 1\n* **[时间段]** 00:00.000 - 00:08.000\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_direct_grok_missing_character"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "direct_videos",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)

    with pytest.raises(RuntimeError) as excinfo:
        manager._process_direct_video(job_id, FakeOmniClient(), script, segment, overwrite=True, video_api="grok", video_settings=settings)

    assert "缺少当前片段人物图" in str(excinfo.value)
    assert "比例" not in str(excinfo.value)


def test_process_direct_video_reports_stale_grok_character_dimensions(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        provider="grok",
        provider_label="Grok",
        api_base_path="/grok/api",
        video_output_root=tmp_path / "grok-videos",
    )
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    character = product_dir / "script-片段1-人物图.png"
    Image.new("RGB", (1536, 1024), (0, 0, 255)).save(character)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"ref")
    segment = Segment(
        index=1,
        title="# Segment 1：00:00.000 - 00:08.000",
        time_range="00:00.000 - 00:08.000",
        raw_text='### 镜头 1\n* **[时间段]** 00:00.000 - 00:08.000\n* **[音频文案]** "hello"',
        character_prompt="prompt",
        storyboard_prompt="story",
    )
    script = type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": [segment],
        },
    )()
    manager = JobManager(settings)
    job_id = "job_direct_grok_stale_character"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "direct_videos",
        "overwrite": False,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 1,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)

    with pytest.raises(RuntimeError) as excinfo:
        manager._process_direct_video(job_id, FakeOmniClient(), script, segment, overwrite=True, video_api="grok", video_settings=settings)

    message = str(excinfo.value)
    assert "当前片段人物图已存在但比例不符合要求" in message
    assert "1536x1024" in message
    assert "3:2" in message
    assert "9:16" in message


def test_run_marks_job_failed_when_steps_have_errors(tmp_path: Path) -> None:
    manager = JobManager(settings_for(tmp_path))
    job_id = "job_failed"
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": "characters",
        "overwrite": False,
        "status": "queued",
        "created_at": 0,
        "started_at": None,
        "finished_at": None,
        "total": 0,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)

    def failing_pipeline(inner_job_id: str) -> None:
        manager._error(inner_job_id, "boom")

    manager._run_pipeline = failing_pipeline
    manager._run(job_id)

    refreshed = manager.get(job_id)
    assert refreshed["status"] == "failed"
    assert "任务完成但有 1 个错误" in refreshed["logs"][-1]["message"]


def test_all_stage_runs_as_segment_relay_for_all_providers(monkeypatch, tmp_path: Path) -> None:
    base_settings = settings_for(tmp_path)
    for provider in ["omni", "grok"]:
        provider_settings = replace(
            base_settings,
            provider=provider,
            provider_label=provider.title(),
            api_base_path=f"/{provider}/api",
        )
        manager = JobManager(provider_settings)
        script = fake_script(tmp_path, provider_settings, segment_count=2)
        monkeypatch.setattr("agent.tasks.scan_scripts", lambda settings, script=script: [script])
        manager._image_client_for = lambda stage: (object(), "otu", provider_settings)
        manager._video_client_for = lambda: (object(), "otu", provider_settings)
        calls = []

        def record(stage_name):
            def inner(*args):
                segment = args[3]
                calls.append((stage_name, segment.index))
                return "ok"

            return inner

        manager._process_character = record("characters")
        manager._process_storyboard = record("storyboards")
        manager._process_video = record("videos")
        job_id = f"job_{provider}"
        seed_job(manager, job_id, "all")

        manager._run_pipeline(job_id)

        assert calls == [
            ("characters", 1),
            ("storyboards", 1),
            ("videos", 1),
            ("characters", 2),
            ("storyboards", 2),
            ("videos", 2),
        ]


def test_direct_videos_stage_runs_characters_then_fast_video_without_storyboard(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=2)
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    calls = []

    def record(stage_name):
        def inner(*args):
            segment = args[3]
            calls.append((stage_name, segment.index))
            return "ok"

        return inner

    manager._process_character = record("characters")
    manager._process_direct_video = record("direct_videos")

    def fail_storyboard(*_args):
        raise AssertionError("快速模式不应生成故事版图")

    manager._process_storyboard = fail_storyboard
    seed_job(manager, "job_direct_pipeline", "direct_videos")

    manager._run_pipeline("job_direct_pipeline")
    refreshed = manager.get("job_direct_pipeline")

    assert calls == [
        ("characters", 1),
        ("direct_videos", 1),
        ("characters", 2),
        ("direct_videos", 2),
    ]
    assert refreshed["total"] == 4
    assert refreshed["done"] == 4


def test_direct_videos_stage_skips_video_when_character_fails(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=1)
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    calls = []

    def fail_character(*args):
        segment = args[3]
        calls.append(("characters", segment.index))
        raise RuntimeError("character failed")

    def fail_direct_video(*_args):
        raise AssertionError("人物图失败时不应进入快速视频")

    manager._process_character = fail_character
    manager._process_direct_video = fail_direct_video
    seed_job(manager, "job_direct_character_failed", "direct_videos")

    manager._run_pipeline("job_direct_character_failed")
    refreshed = manager.get("job_direct_character_failed")

    assert calls == [("characters", 1)]
    assert refreshed["total"] == 2
    assert refreshed["done"] == 2
    assert any("前置人物图未完成，跳过" in entry["message"] for entry in refreshed["logs"])


def test_all_stage_continues_after_segment_error(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=2)
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    calls = []

    def failing_character(*args):
        segment = args[3]
        calls.append(("characters", segment.index))
        if segment.index == 1:
            raise RuntimeError("boom")
        return "ok"

    def record_later(stage_name):
        def inner(*args):
            segment = args[3]
            calls.append((stage_name, segment.index))
            return "ok"

        return inner

    manager._process_character = failing_character
    manager._process_storyboard = record_later("storyboards")
    manager._process_video = record_later("videos")
    seed_job(manager, "job_stop", "all")

    manager._run_pipeline("job_stop")
    refreshed = manager.get("job_stop")

    assert calls == [
        ("characters", 1),
        ("characters", 2),
        ("storyboards", 2),
        ("videos", 2),
    ]
    assert refreshed["done"] == 6
    assert len(refreshed["errors"]) == 1
    assert any("前置人物图未完成，跳过" in entry["message"] for entry in refreshed["logs"])


def test_cancel_stops_pipeline_before_next_segment(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=2)
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    calls = []

    def cancel_after_first(*args):
        segment = args[3]
        calls.append(segment.index)
        manager.cancel("job_cancel")
        return "ok"

    manager._process_character = cancel_after_first
    seed_job(manager, "job_cancel", "characters")

    manager._run("job_cancel")
    refreshed = manager.get("job_cancel")

    assert calls == [1]
    assert refreshed["status"] == "canceled"
    assert refreshed["done"] == 1
    assert any("已请求停止任务" in entry["message"] for entry in refreshed["logs"])


def test_repair_stage_only_targets_missing_assets(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=2)
    prepare_character(script, 1, settings)
    prepare_storyboard(script, 1, settings)
    prepare_video(script, 1, settings)
    prepare_character(script, 2, settings)
    prepare_storyboard(script, 2, settings)
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    calls = []

    def record(stage_name):
        def inner(*args):
            segment = args[3]
            calls.append((stage_name, segment.index))
            return "ok"

        return inner

    manager._process_character = record("characters")
    manager._process_storyboard = record("storyboards")
    manager._process_video = record("videos")
    seed_job(manager, "job_repair_missing", "repair")

    manager._run_pipeline("job_repair_missing")
    refreshed = manager.get("job_repair_missing")

    assert calls == [("videos", 2)]
    assert refreshed["total"] == 1
    assert refreshed["done"] == 1
    assert refreshed["errors"] == []


def test_repair_stage_runs_as_segment_relay_for_all_providers(monkeypatch, tmp_path: Path) -> None:
    base_settings = settings_for(tmp_path)
    for provider in ["omni", "grok"]:
        provider_settings = replace(
            base_settings,
            provider=provider,
            provider_label=provider.title(),
            api_base_path=f"/{provider}/api",
            script_root=tmp_path / provider / "scripts",
            reference_root=tmp_path / provider / "refs",
            video_output_root=tmp_path / provider / "videos",
        )
        manager = JobManager(provider_settings)
        script = fake_script(tmp_path / provider, provider_settings, segment_count=2)
        monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings, script=script: [script])
        manager._image_client_for = lambda stage, provider_settings=provider_settings: (object(), "otu", provider_settings)
        manager._video_client_for = lambda provider_settings=provider_settings: (object(), "otu", provider_settings)
        calls = []

        def character_step(*args, provider_settings=provider_settings):
            segment = args[3]
            calls.append(("characters", segment.index))
            prepare_character(script, segment.index, provider_settings)
            return "ok"

        def storyboard_step(*args, provider_settings=provider_settings):
            segment = args[3]
            calls.append(("storyboards", segment.index))
            prepare_storyboard(script, segment.index, provider_settings)
            return "ok"

        def video_step(*args, provider_settings=provider_settings):
            segment = args[3]
            calls.append(("videos", segment.index))
            prepare_video(script, segment.index, provider_settings)
            return "ok"

        manager._process_character = character_step
        manager._process_storyboard = storyboard_step
        manager._process_video = video_step
        job_id = f"job_repair_relay_{provider}"
        seed_job(manager, job_id, "repair")

        manager._run_pipeline(job_id)
        refreshed = manager.get(job_id)

        assert calls == [
            ("characters", 1),
            ("characters", 2),
            ("storyboards", 1),
            ("storyboards", 2),
            ("videos", 1),
            ("videos", 2),
        ]
        assert refreshed["total"] == 6
        assert refreshed["done"] == 6
        assert refreshed["errors"] == []


def test_repair_stage_continues_after_storyboard_error(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=2)
    prepare_character(script, 1, settings)
    prepare_character(script, 2, settings)
    prepare_storyboard(script, 2, settings)
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    calls = []

    def failing_storyboard(*args):
        segment = args[3]
        calls.append(("storyboards", segment.index))
        raise RuntimeError("storyboard blocked")

    def video_step(*args):
        segment = args[3]
        calls.append(("videos", segment.index))
        if segment.index == 1:
            raise RuntimeError("missing storyboard")
        return "ok"

    manager._process_storyboard = failing_storyboard
    manager._process_video = video_step
    seed_job(manager, "job_repair_continue", "repair")

    manager._run_pipeline("job_repair_continue")
    refreshed = manager.get("job_repair_continue")

    assert calls == [("storyboards", 1), ("videos", 2)]
    assert refreshed["total"] == 3
    assert refreshed["done"] == 3
    assert len(refreshed["errors"]) == 1
    assert any("前置故事版未完成，本轮暂不补视频" in entry["message"] for entry in refreshed["logs"])


def test_repair_blocks_reused_character_without_extra_error(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    manager = JobManager(settings)
    script = fake_script(tmp_path, settings, segment_count=2)
    script.segments[1] = Segment(
        index=2,
        title="# Segment 2：00:01 - 00:02",
        time_range="00:01 - 00:02",
        raw_text='### 镜头 1\n* **[音频文案]** "hello"',
        character_prompt="复用 character_01 人物图",
        storyboard_prompt="story",
    )
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: [script])
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    calls = []

    def failing_character(*args):
        segment = args[3]
        calls.append(("characters", segment.index))
        raise RuntimeError("image api down")

    manager._process_character = failing_character
    seed_job(manager, "job_repair_reuse_block", "repair")

    manager._run_pipeline("job_repair_reuse_block")
    refreshed = manager.get("job_repair_reuse_block")

    assert calls == [("characters", 1)]
    assert len(refreshed["errors"]) == 1
    assert "片段1 人物图：image api down" in refreshed["errors"][0]
    assert any("片段2 人物图：复用源人物图未完成：片段1，本轮暂不补人物图" in entry["message"] for entry in refreshed["logs"])


def test_repair_stage_runs_scripts_in_parallel(monkeypatch, tmp_path: Path) -> None:
    settings = replace(settings_for(tmp_path), script_concurrency=2)
    manager = JobManager(settings)

    def named_script(product_name: str):
        product_dir = settings.script_root / product_name
        product_dir.mkdir(parents=True, exist_ok=True)
        md_path = product_dir / f"{product_name}.md"
        md_path.write_text("placeholder", encoding="utf-8")
        reference = settings.reference_root / f"{product_name}.png"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(b"ref")
        return type(
            "Script",
            (),
            {
                "product_name": product_name,
                "product_dir": product_dir,
                "md_path": md_path,
                "reference_image": reference,
                "segments": [
                    Segment(
                        index=1,
                        title="# Segment 1：00:00 - 00:01",
                        time_range="00:00 - 00:01",
                        raw_text='### 镜头 1\n* **[音频文案]** "hello"',
                        character_prompt="prompt",
                        storyboard_prompt="story",
                    )
                ],
            },
        )()

    scripts = [named_script("P1"), named_script("P2")]
    monkeypatch.setattr("agent.tasks.scan_scripts", lambda current_settings: scripts)
    manager._image_client_for = lambda stage: (object(), "otu", settings)
    manager._video_client_for = lambda: (object(), "otu", settings)
    barrier = threading.Barrier(2)
    active_counts = []

    def character_step(*args):
        script = args[2]
        segment = args[3]
        barrier.wait(timeout=2)
        active_counts.append(len(manager.get("job_parallel")["active_scripts"]))
        prepare_character(script, segment.index, settings)
        return "ok"

    def storyboard_step(*args):
        script = args[2]
        segment = args[3]
        prepare_storyboard(script, segment.index, settings)
        return "ok"

    def video_step(*args):
        script = args[2]
        segment = args[3]
        prepare_video(script, segment.index, settings)
        return "ok"

    manager._process_character = character_step
    manager._process_storyboard = storyboard_step
    manager._process_video = video_step
    seed_job(manager, "job_parallel", "repair")

    manager._run_pipeline("job_parallel")
    refreshed = manager.get("job_parallel")

    assert refreshed["total"] == 6
    assert refreshed["done"] == 6
    assert refreshed["errors"] == []
    assert max(active_counts) == 2
    assert {item["status"] for item in refreshed["script_statuses"].values()} == {"done"}
    assert any("脚本并发 2" in entry["message"] for entry in refreshed["logs"])


def test_running_script_scheduler_uses_updated_concurrency(tmp_path: Path) -> None:
    settings = replace(settings_for(tmp_path), script_concurrency=1)
    manager = JobManager(settings)
    scripts = []
    for index in range(1, 4):
        product_dir = settings.script_root / f"P{index}"
        product_dir.mkdir(parents=True, exist_ok=True)
        md_path = product_dir / f"P{index}.md"
        md_path.write_text("placeholder", encoding="utf-8")
        scripts.append(
            type(
                "Script",
                (),
                {
                    "product_name": f"P{index}",
                    "md_path": md_path,
                },
            )()
        )

    seed_job(manager, "job_dynamic_concurrency", "repair")
    manager._jobs["job_dynamic_concurrency"]["script_concurrency"] = 1
    started = []
    started_lock = threading.Lock()
    first_started = threading.Event()
    all_started = threading.Event()
    release = threading.Event()
    worker_error = []

    def worker(script):
        with started_lock:
            started.append(script.product_name)
            if len(started) == 1:
                first_started.set()
            if len(started) == 3:
                all_started.set()
        release.wait(timeout=3)

    def run_scheduler():
        try:
            manager._run_scripts_concurrently("job_dynamic_concurrency", scripts, worker, "动态并发")
        except Exception as exc:
            worker_error.append(exc)

    thread = threading.Thread(target=run_scheduler)
    thread.start()
    assert first_started.wait(timeout=2)
    with started_lock:
        assert started == ["P1"]

    refreshed = manager.update_concurrency(3, "job_dynamic_concurrency")

    assert refreshed["script_concurrency"] == 3
    assert all_started.wait(timeout=4)
    release.set()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert worker_error == []
    with started_lock:
        assert set(started) == {"P1", "P2", "P3"}


def seed_job(manager: JobManager, job_id: str, stage: str) -> None:
    manager._jobs[job_id] = {
        "id": job_id,
        "stage": stage,
        "overwrite": False,
        "script_paths": None,
        "status": "running",
        "created_at": 0,
        "started_at": 0,
        "finished_at": None,
        "total": 0,
        "done": 0,
        "logs": [],
        "errors": [],
        "result": None,
    }
    manager._job_order.append(job_id)


def fake_script(tmp_path: Path, settings: Settings, segment_count: int):
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True, exist_ok=True)
    md_path = product_dir / "script.md"
    md_path.write_text("placeholder", encoding="utf-8")
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(b"ref")
    segments = [
        Segment(
            index=index,
            title=f"# Segment {index}：00:00 - 00:01",
            time_range="00:00 - 00:01",
            raw_text='### 镜头 1\n* **[音频文案]** "hello"',
            character_prompt="prompt",
            storyboard_prompt="story",
        )
        for index in range(1, segment_count + 1)
    ]
    return type(
        "Script",
        (),
        {
            "product_name": "P1",
            "product_dir": product_dir,
            "md_path": md_path,
            "reference_image": reference,
            "segments": segments,
        },
    )()


def prepare_character(script, segment_index: int, settings: Settings) -> Path:
    path = character_image_path(script.md_path, segment_index, settings.artifact_prefix)
    path.write_bytes(b"person")
    return path


def prepare_storyboard(script, segment_index: int, settings: Settings) -> Path:
    path = storyboard_image_path(script.md_path, segment_index, settings.artifact_prefix)
    path.write_bytes(b"story")
    assert script.reference_image is not None
    write_storyboard_product_lock_meta(path, script.product_name, script.reference_image, 1)
    return path


def prepare_video(script, segment_index: int, settings: Settings) -> Path:
    path = video_output_path(settings, script.product_name, script.md_path, segment_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"mp4")
    return path
