import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

import agent.api_clients as api_clients
import httpx
import pytest
from agent.api_clients import GrokClient, Image2Client, OmniClient, RunningHubSkyReelsClient
from agent.config import Settings
from PIL import Image


class FakeResponse:
    def __init__(self, body: Dict[str, Any] = None, content: bytes = b"", status_code: int = 200) -> None:
        self._body = body or {}
        self.content = content
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://otuapi.com/v1/images/generations")
            response = httpx.Response(self.status_code, json=self._body, request=request)
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=request, response=response)


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
        omni_poll_interval_seconds=0,
        omni_timeout_seconds=1,
        image_retry_attempts=3,
        image_retry_base_seconds=0,
        image_reference_max_side=2048,
        image_reference_jpeg_quality=88,
    )


def test_image2_client_saves_b64_response(monkeypatch: Any, tmp_path: Path) -> None:
    reference = tmp_path / "ref.png"
    Image.new("RGB", (3200, 2400), (255, 0, 0)).save(reference)
    output = tmp_path / "out.png"
    expected = b"image-bytes"

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            assert url == "https://otuapi.com/v1/images/generations"
            assert json["model"] == "image2"
            assert json["size"] == "4096x3072"
            assert "4K" in json["prompt"]
            assert "8K" not in json["prompt"]
            assert json["image"][0].startswith("data:image/jpeg;base64,")
            encoded = base64.b64encode(expected).decode("ascii")
            return FakeResponse({"data": [{"b64_json": encoded}]})

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    Image2Client(settings_for(tmp_path)).generate_with_references("8K分辨率 prompt", [reference], output)

    assert output.read_bytes() == expected


def test_image2_client_prompt_only_omits_image_field(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "character.png"
    expected = b"character-bytes"

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            assert url == "https://otuapi.com/v1/images/generations"
            assert json["model"] == "image2"
            assert json["size"] == "4096x3072"
            assert "image" not in json
            encoded = base64.b64encode(expected).decode("ascii")
            return FakeResponse({"data": [{"b64_json": encoded}]})

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    Image2Client(settings_for(tmp_path)).generate_from_prompt("人物图 prompt", output)

    assert output.read_bytes() == expected


def test_gpt_image_2_prompt_uses_async_video_endpoint(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "character.png"
    expected = b"async-character"
    base_settings = settings_for(tmp_path)
    settings = Settings(
        **{
            **base_settings.__dict__,
            "image_model": "gpt-image-2-4K",
            "image_poll_interval_seconds": 0,
            "image_timeout_seconds": 1,
        }
    )
    polls = 0

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            assert url == "https://otuapi.com/v1/videos"
            assert json == {
                "model": "gpt-image-2-4K",
                "prompt": "人物图 prompt",
                "size": "4096x3072",
            }
            return FakeResponse({"id": "task_image_1", "object": "image", "status": "queued", "progress": 0})

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            nonlocal polls
            if url.endswith("/task_image_1"):
                polls += 1
                if polls == 1:
                    return FakeResponse({"id": "task_image_1", "status": "in_progress", "progress": 50})
                return FakeResponse(
                    {
                        "id": "task_image_1",
                        "status": "completed",
                        "progress": 100,
                        "url": "https://cdn.example/character.png",
                    }
                )
            assert url == "https://cdn.example/character.png"
            return FakeResponse(content=expected)

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    result = Image2Client(settings).generate_from_prompt("人物图 prompt", output)

    assert result["task_id"] == "task_image_1"
    assert output.read_bytes() == expected


def test_gpt_image_2_references_use_async_images_array(monkeypatch: Any, tmp_path: Path) -> None:
    reference = tmp_path / "ref.png"
    Image.new("RGB", (1024, 1024), (255, 0, 0)).save(reference)
    output = tmp_path / "storyboard.png"
    expected = b"async-storyboard"
    base_settings = settings_for(tmp_path)
    settings = Settings(
        **{
            **base_settings.__dict__,
            "image_model": "gpt-image-2-4K",
            "image_poll_interval_seconds": 0,
            "image_timeout_seconds": 1,
        }
    )

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            assert url == "https://otuapi.com/v1/videos"
            assert json["model"] == "gpt-image-2-4K"
            assert json["size"] == "4096x3072"
            assert "image" not in json
            assert len(json["images"]) == 1
            assert json["images"][0].startswith("data:image/jpeg;base64,")
            return FakeResponse(
                {
                    "id": "task_image_2",
                    "object": "image",
                    "status": "completed",
                    "progress": 100,
                    "url": "https://cdn.example/storyboard.png",
                }
            )

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            assert url == "https://cdn.example/storyboard.png"
            return FakeResponse(content=expected)

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    result = Image2Client(settings).generate_with_references("故事版 prompt", [reference], output)

    assert result["task_id"] == "task_image_2"
    assert output.read_bytes() == expected


def test_gpt_image_2_retries_failed_async_task(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "character.png"
    expected = b"retry-success"
    base_settings = settings_for(tmp_path)
    settings = Settings(
        **{
            **base_settings.__dict__,
            "image_model": "gpt-image-2-4K",
            "image_fallback_models": [],
            "image_poll_interval_seconds": 0,
            "image_timeout_seconds": 1,
        }
    )
    submissions = 0
    progress_messages = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            nonlocal submissions
            submissions += 1
            if submissions == 1:
                return FakeResponse(
                    {
                        "id": "task_failed",
                        "status": "failed",
                        "error": {"code": "upstream_error", "message": "temporary"},
                    }
                )
            return FakeResponse(
                {
                    "id": "task_success",
                    "status": "completed",
                    "progress": 100,
                    "url": "https://cdn.example/retry.png",
                }
            )

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            assert url == "https://cdn.example/retry.png"
            return FakeResponse(content=expected)

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    result = Image2Client(settings).generate_from_prompt(
        "人物图 prompt",
        output,
        progress=progress_messages.append,
    )

    assert submissions == 2
    assert result["task_id"] == "task_success"
    assert output.read_bytes() == expected
    assert any("异步图片任务失败" in message for message in progress_messages)


def test_image2_client_falls_back_when_primary_model_unavailable(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "character.png"
    expected = b"fallback-bytes"
    seen_models = []
    base_settings = settings_for(tmp_path)
    settings = Settings(
        **{
            **base_settings.__dict__,
            "image_model": "image-4k",
            "image_fallback_models": ["image2"],
        }
    )

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            seen_models.append(json["model"])
            if json["model"] == "image-4k":
                return FakeResponse(
                    {
                        "error": {
                            "code": "model_not_found",
                            "message": "No available channel for model image-4k under group svip",
                        }
                    },
                    status_code=503,
                )
            encoded = base64.b64encode(expected).decode("ascii")
            return FakeResponse({"data": [{"b64_json": encoded}]})

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    result = Image2Client(settings).generate_from_prompt("人物图 prompt", output)

    assert seen_models == ["image-4k", "image2"]
    assert result["model"] == "image2"
    assert output.read_bytes() == expected


def test_omni_client_polls_and_downloads_video(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    storyboard.write_bytes(b"story")
    output = tmp_path / "video.mp4"

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], files: Any) -> FakeResponse:
            field_names = [field[0] for field in files]
            assert field_names == ["model", "prompt", "size", "input_reference"]
            assert files[0][1] == (None, "omni_flash-10s")
            assert files[2][1] == (None, "720x1280")
            return FakeResponse({"id": "task_1", "status": "queued", "progress": 0})

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            if url.endswith("/task_1"):
                return FakeResponse({"id": "task_1", "status": "completed", "video_url": "https://cdn.example/video.mp4"})
            return FakeResponse(content=b"mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    OmniClient(settings_for(tmp_path)).generate_video("prompt", storyboard, output)

    assert output.read_bytes() == b"mp4"


def test_omni_client_can_upload_multiple_local_input_references(monkeypatch: Any, tmp_path: Path) -> None:
    character = tmp_path / "character.png"
    character.write_bytes(b"person")
    product = tmp_path / "product.png"
    product.write_bytes(b"product")
    output = tmp_path / "video.mp4"

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], files: Any) -> FakeResponse:
            field_names = [field[0] for field in files]
            assert field_names == ["model", "prompt", "size", "input_reference", "input_reference"]
            assert files[3][1][0] == "character.png"
            assert files[4][1][0] == "product.png"
            return FakeResponse({"id": "task_multi", "status": "queued", "progress": 0})

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            if url.endswith("/task_multi"):
                return FakeResponse({"id": "task_multi", "status": "completed", "video_url": "https://cdn.example/video.mp4"})
            return FakeResponse(content=b"mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    OmniClient(settings_for(tmp_path)).generate_video("prompt", character, output, reference_paths=[product])

    assert output.read_bytes() == b"mp4"


def test_omni_client_keeps_polling_after_retryable_502(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    storyboard.write_bytes(b"story")
    output = tmp_path / "video.mp4"
    get_count = 0
    progress_messages = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], files: Any) -> FakeResponse:
            return FakeResponse({"id": "task_502", "status": "queued", "progress": 0})

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            nonlocal get_count
            get_count += 1
            if url.endswith("/task_502") and get_count == 1:
                return FakeResponse({"error": "bad gateway"}, status_code=502)
            if url.endswith("/task_502"):
                return FakeResponse({"id": "task_502", "status": "completed", "video_url": "https://cdn.example/video.mp4"})
            return FakeResponse(content=b"mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    OmniClient(settings_for(tmp_path)).generate_video("prompt", storyboard, output, progress=progress_messages.append)

    assert output.read_bytes() == b"mp4"
    assert any("HTTP 502" in message for message in progress_messages)


def test_omni_client_resubmits_three_times_after_upstream_error(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    storyboard.write_bytes(b"story")
    output = tmp_path / "video.mp4"
    post_count = 0
    progress_messages = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], files: Any) -> FakeResponse:
            nonlocal post_count
            post_count += 1
            return FakeResponse({"id": f"task_{post_count}", "status": "queued", "progress": 0})

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            if url.endswith("/task_4"):
                return FakeResponse({"id": "task_4", "status": "completed", "video_url": "https://cdn.example/video.mp4"})
            if "/task_" in url:
                return FakeResponse(
                    {
                        "id": url.rsplit("/", 1)[-1],
                        "status": "failed",
                        "error": {"code": "upstream_error", "message": "生成过程中出现异常，请重新发起请求"},
                    }
                )
            return FakeResponse(content=b"mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    OmniClient(settings_for(tmp_path)).generate_video("prompt", storyboard, output, progress=progress_messages.append)

    assert post_count == 4
    assert output.read_bytes() == b"mp4"
    assert sum("自动重新提交" in message for message in progress_messages) == 3


def test_omni_client_retries_submit_503_and_reports_body(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    storyboard.write_bytes(b"story")
    output = tmp_path / "video.mp4"
    base_settings = settings_for(tmp_path)
    settings = Settings(
        **{
            **base_settings.__dict__,
            "omni_retry_attempts": 2,
            "omni_retry_base_seconds": 0,
        }
    )
    post_count = 0

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], files: Any) -> FakeResponse:
            nonlocal post_count
            post_count += 1
            return FakeResponse(
                {"error": {"message": "No available channel for model omni_flash-10s under group svip"}},
                status_code=503,
            )

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    with pytest.raises(api_clients.ApiError, match="No available channel for model omni_flash-10s"):
        OmniClient(settings).generate_video("prompt", storyboard, output)

    assert post_count == 2


def test_grok_text_to_image_submits_queries_and_downloads(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "grok-character.png"
    settings = Settings(**{**settings_for(tmp_path).__dict__, "provider": "grok", "provider_label": "Grok", "api_base_path": "/grok/api"})
    posts = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            posts.append((url, json))
            if url.endswith("/text-to-image"):
                assert json["prompt"] == "人物 prompt"
                assert json["aspectRatio"] == "9:16"
                assert json["resolution"] == "4k"
                return FakeResponse({"taskId": "task_grok_1", "status": "RUNNING", "results": None})
            assert url.endswith("/query")
            assert json == {"taskId": "task_grok_1"}
            return FakeResponse({"taskId": "task_grok_1", "status": "SUCCESS", "results": [{"url": "https://cdn.example/grok.png"}]})

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            assert url == "https://cdn.example/grok.png"
            return FakeResponse(content=b"png")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    GrokClient(settings).generate_from_prompt("人物 prompt", output)

    assert output.read_bytes() == b"png"
    assert posts[0][0].endswith("/openapi/v2/rhart-image-g-2/text-to-image")


def test_grok_text_to_image_retries_runninghub_no_task_id(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "grok-character.png"
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "grok",
            "provider_label": "Grok",
            "api_base_path": "/grok/api",
            "grok_retry_attempts": 2,
            "grok_retry_base_seconds": 0,
        }
    )
    submit_count = 0
    progress_messages = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            nonlocal submit_count
            if url.endswith("/text-to-image"):
                submit_count += 1
                if submit_count == 1:
                    return FakeResponse(
                        {
                            "taskId": "",
                            "status": "",
                            "errorCode": "1000",
                            "errorMessage": "Unknown error, please retry or contact support",
                            "results": None,
                        }
                    )
                return FakeResponse({"taskId": "task_retry_ok", "status": "SUCCESS", "results": [{"url": "https://cdn.example/grok.png"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            assert url == "https://cdn.example/grok.png"
            return FakeResponse(content=b"png")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    GrokClient(settings).generate_from_prompt("人物 prompt", output, progress=progress_messages.append)

    assert submit_count == 2
    assert output.read_bytes() == b"png"
    assert any("可重试错误" in message for message in progress_messages)


def test_grok_image_to_image_uses_image_urls(monkeypatch: Any, tmp_path: Path) -> None:
    reference = tmp_path / "ref.png"
    Image.new("RGB", (640, 480), (255, 0, 0)).save(reference)
    output = tmp_path / "grok-story.png"
    settings = Settings(**{**settings_for(tmp_path).__dict__, "provider": "grok", "provider_label": "Grok", "api_base_path": "/grok/api"})

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            if url.endswith("/image-to-image"):
                assert json["imageUrls"][0].startswith("data:image/jpeg;base64,")
                assert json["aspectRatio"] == "9:16"
                assert json["resolution"] == "4k"
                return FakeResponse({"taskId": "task_grok_2", "status": "SUCCESS", "results": [{"url": "https://cdn.example/story.png"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(content=b"story")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    GrokClient(settings).generate_with_references("故事 prompt", [reference], output)

    assert output.read_bytes() == b"story"


def test_grok_image_to_video_uses_video_payload(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    Image.new("RGB", (640, 480), (0, 255, 0)).save(storyboard)
    product = tmp_path / "product.png"
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(product)
    output = tmp_path / "grok-video.mp4"
    settings = Settings(**{**settings_for(tmp_path).__dict__, "provider": "grok", "provider_label": "Grok", "api_base_path": "/grok/api"})

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            if url.endswith("/image-to-video"):
                assert json["aspectRatio"] == "9:16"
                assert json["resolution"] == "720p"
                assert json["duration"] == 8
                assert json["imageUrls"][0].startswith("data:image/jpeg;base64,")
                assert len(json["imageUrls"]) == 2
                first_ref = base64.b64decode(json["imageUrls"][0].split(",", 1)[1])
                with Image.open(BytesIO(first_ref)) as image:
                    assert image.size == (720, 1280)
                return FakeResponse({"taskId": "task_grok_3", "status": "SUCCESS", "results": [{"url": "https://cdn.example/video.mp4"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(content=b"mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    GrokClient(settings).generate_video("视频 prompt", storyboard, output, duration=8, reference_paths=[product])

    assert output.read_bytes() == b"mp4"


def test_grok_image_to_video_retries_with_safer_reference_strategy(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    Image.new("RGB", (640, 480), (0, 255, 0)).save(storyboard)
    product = tmp_path / "product.png"
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(product)
    character = tmp_path / "character.png"
    Image.new("RGB", (1448, 1086), (0, 0, 255)).save(character)
    output = tmp_path / "grok-video.mp4"
    settings = Settings(**{**settings_for(tmp_path).__dict__, "provider": "grok", "provider_label": "Grok", "api_base_path": "/grok/api"})
    submitted_reference_counts = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            if url.endswith("/image-to-video"):
                submitted_reference_counts.append(len(json["imageUrls"]))
                if len(submitted_reference_counts) == 1:
                    return FakeResponse({"taskId": "task_grok_failed", "status": "FAILED", "errorCode": "1012"})
                return FakeResponse({"taskId": "task_grok_ok", "status": "SUCCESS", "results": [{"url": "https://cdn.example/video.mp4"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(content=b"mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    GrokClient(settings).generate_video("视频 prompt", storyboard, output, duration=8, reference_paths=[product, character])

    assert submitted_reference_counts == [3, 2]
    assert output.read_bytes() == b"mp4"


def test_runninghub_skyreels_omni_fast_uses_reference_payload(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    product = tmp_path / "product.png"
    character = tmp_path / "character.png"
    Image.new("RGB", (1448, 2048), (0, 255, 0)).save(storyboard)
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(product)
    Image.new("RGB", (1448, 1086), (0, 0, 255)).save(character)
    output = tmp_path / "skyreels-video.mp4"
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "omni",
            "provider_label": "Omni",
            "api_base_path": "/omni/api",
            "grok_video_aspect_ratio": "9:16",
            "grok_video_resolution": "1080p",
            "grok_video_duration": 10,
        }
    )
    submitted_payloads = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            if url.endswith("/skyreels-v4/omni-reference-fast"):
                submitted_payloads.append(json)
                assert json["aspectRatio"] == "9:16"
                assert json["resolution"] == "1080p"
                assert json["duration"] == 15
                assert json["promptOptimizer"] is True
                assert len(json["refImages"]) == 3
                assert all(isinstance(item, dict) for item in json["refImages"])
                assert json["refImages"][0]["type"] == "image"
                assert json["refImages"][0]["tag"] == "image_1"
                assert json["refImages"][0]["url"].startswith("data:image/jpeg;base64,")
                assert len(json["prompt"]) <= 2500
                assert "@image_1" in json["prompt"]
                return FakeResponse({"taskId": "task_skyreels", "status": "RUNNING", "results": None})
            if url.endswith("/query"):
                assert json == {"taskId": "task_skyreels"}
                return FakeResponse({"taskId": "task_skyreels", "status": "SUCCESS", "results": [{"url": "https://cdn.example/skyreels.mp4"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            assert url == "https://cdn.example/skyreels.mp4"
            return FakeResponse(content=b"skyreels-mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    RunningHubSkyReelsClient(settings).generate_video("视频 prompt" * 400, storyboard, output, duration=30, reference_paths=[product, character])

    assert submitted_payloads
    assert output.read_bytes() == b"skyreels-mp4"


def test_runninghub_skyreels_retries_ref_image_object_key(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    product = tmp_path / "product.png"
    Image.new("RGB", (1448, 2048), (0, 255, 0)).save(storyboard)
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(product)
    output = tmp_path / "skyreels-video.mp4"
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "omni",
            "provider_label": "Omni",
            "api_base_path": "/omni/api",
            "grok_video_resolution": "1080p",
        }
    )
    submitted_keys = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            if url.endswith("/skyreels-v4/omni-reference-fast"):
                first_ref = json["refImages"][0]
                submitted_keys.append(tuple(sorted(first_ref.keys())))
                if "url" in first_ref:
                    return FakeResponse(
                        {
                            "taskId": "",
                            "status": "",
                            "errorCode": "1007",
                            "errorMessage": "field 'refImages[0].url' is invalid",
                            "results": None,
                        }
                    )
                assert "imageUrl" in first_ref
                return FakeResponse({"taskId": "task_skyreels", "status": "RUNNING", "results": None})
            if url.endswith("/query"):
                return FakeResponse({"taskId": "task_skyreels", "status": "SUCCESS", "results": [{"url": "https://cdn.example/skyreels.mp4"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(content=b"skyreels-mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    RunningHubSkyReelsClient(settings).generate_video("视频 prompt", storyboard, output, reference_paths=[product])

    assert submitted_keys == [("tag", "type", "url"), ("imageUrl", "tag", "type")]
    assert output.read_bytes() == b"skyreels-mp4"


def test_runninghub_skyreels_retries_internal_server_task_failure(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    product = tmp_path / "product.png"
    Image.new("RGB", (1448, 2048), (0, 255, 0)).save(storyboard)
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(product)
    output = tmp_path / "skyreels-video.mp4"
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "omni",
            "provider_label": "Omni",
            "api_base_path": "/omni/api",
            "grok_retry_attempts": 2,
            "grok_retry_base_seconds": 0,
            "grok_video_resolution": "1080p",
        }
    )
    submit_count = 0
    progress_messages = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            nonlocal submit_count
            if url.endswith("/skyreels-v4/omni-reference-fast"):
                submit_count += 1
                task_id = "task_fail" if submit_count == 1 else "task_ok"
                return FakeResponse({"taskId": task_id, "status": "RUNNING", "results": None})
            if url.endswith("/query"):
                if json == {"taskId": "task_fail"}:
                    return FakeResponse(
                        {
                            "taskId": "task_fail",
                            "status": "FAILED",
                            "errorCode": "1005",
                            "errorMessage": "Internal server error, please retry later | 系统内部错误，请稍后重试",
                            "results": None,
                        }
                    )
                return FakeResponse({"taskId": "task_ok", "status": "SUCCESS", "results": [{"url": "https://cdn.example/skyreels.mp4"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(content=b"skyreels-mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    RunningHubSkyReelsClient(settings).generate_video("视频 prompt", storyboard, output, progress=progress_messages.append, reference_paths=[product])

    assert submit_count == 2
    assert output.read_bytes() == b"skyreels-mp4"
    assert any("可重试错误" in message for message in progress_messages)


def test_runninghub_skyreels_switches_ref_image_format_after_internal_error(monkeypatch: Any, tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    product = tmp_path / "product.png"
    Image.new("RGB", (1448, 2048), (0, 255, 0)).save(storyboard)
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(product)
    output = tmp_path / "skyreels-video.mp4"
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "omni",
            "provider_label": "Omni",
            "api_base_path": "/omni/api",
            "grok_retry_attempts": 1,
            "grok_retry_base_seconds": 0,
            "grok_video_resolution": "1080p",
        }
    )
    submitted_keys = []

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> FakeResponse:
            if url.endswith("/skyreels-v4/omni-reference-fast"):
                first_ref = json["refImages"][0]
                submitted_keys.append(tuple(sorted(first_ref.keys())))
                task_id = "task_bad_format" if "url" in first_ref else "task_good_format"
                return FakeResponse({"taskId": task_id, "status": "RUNNING", "results": None})
            if url.endswith("/query"):
                if json == {"taskId": "task_bad_format"}:
                    return FakeResponse(
                        {
                            "taskId": "task_bad_format",
                            "status": "FAILED",
                            "errorCode": "1005",
                            "errorMessage": "Internal server error, please retry later | 系统内部错误，请稍后重试",
                            "results": None,
                        }
                    )
                return FakeResponse({"taskId": "task_good_format", "status": "SUCCESS", "results": [{"url": "https://cdn.example/skyreels.mp4"}]})
            raise AssertionError(url)

        def get(self, url: str, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(content=b"skyreels-mp4")

    monkeypatch.setattr(api_clients.httpx, "Client", lambda timeout: FakeClient())

    RunningHubSkyReelsClient(settings).generate_video("视频 prompt", storyboard, output, reference_paths=[product])

    assert submitted_keys == [("tag", "type", "url"), ("imageUrl", "tag", "type")]
    assert output.read_bytes() == b"skyreels-mp4"
