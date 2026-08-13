from __future__ import annotations

import base64
import json
import mimetypes
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
from PIL import Image, ImageOps

from .config import Settings
from .files import ensure_parent


class ApiError(RuntimeError):
    pass


class RetryableVideoTaskError(ApiError):
    pass


class Image2Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_from_prompt(
        self,
        prompt: str,
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.otu_api_key:
            raise ApiError("OTU_API_KEY 未配置")

        headers = {"Authorization": f"Bearer {self.settings.otu_api_key}"}
        attempts = max(1, self.settings.image_retry_attempts)
        last_error: Optional[Exception] = None

        with httpx.Client(timeout=1200.0) as client:
            candidates = self.settings.image_model_candidates
            for model_index, model in enumerate(candidates):
                for attempt in range(1, attempts + 1):
                    normalized_prompt = _normalize_image_prompt(prompt, self.settings.image_size)
                    if progress:
                        progress(f"调用图片模型 {model}，第 {attempt}/{attempts} 次尝试，prompt {len(normalized_prompt)} 字符")
                    try:
                        if _is_async_gpt_image_model(model):
                            body, image_bytes = self._generate_async_image(
                                client,
                                headers,
                                model,
                                normalized_prompt,
                                [],
                                progress,
                            )
                        else:
                            if progress:
                                progress("请求 /v1/images/generations（纯文生图）")
                            body = self._post_generations_json(client, headers, model, normalized_prompt, [])
                            image_bytes = _extract_image_bytes(client, body)
                        ensure_parent(output_path)
                        output_path.write_bytes(image_bytes)
                        return {
                            "path": str(output_path),
                            "model": model,
                            "task_id": body.get("id"),
                            "response_keys": sorted(body.keys()),
                            "attempt": attempt,
                        }
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        if _is_model_unavailable_error(exc) and model_index < len(candidates) - 1:
                            next_model = candidates[model_index + 1]
                            if progress:
                                progress(f"模型 {model} 当前不可用，切换到 {next_model}")
                            break
                        if not _is_retryable_status(exc.response.status_code) or attempt >= attempts:
                            raise
                        delay = self.settings.image_retry_base_seconds * attempt
                        if progress:
                            progress(f"图片接口返回 {exc.response.status_code}，{delay:.0f}s 后重试")
                        time.sleep(delay)
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        last_error = exc
                        if attempt >= attempts:
                            raise
                        delay = self.settings.image_retry_base_seconds * attempt
                        if progress:
                            progress(f"图片接口网络/超时错误，{delay:.0f}s 后重试")
                        time.sleep(delay)
                    except ApiError as exc:
                        last_error = exc
                        if attempt >= attempts:
                            raise
                        delay = self.settings.image_retry_base_seconds * attempt
                        if progress:
                            progress(f"异步图片任务失败，{delay:.0f}s 后重新提交：{exc}")
                        time.sleep(delay)

        raise ApiError(f"图片生成调用失败：{last_error}")

    def generate_with_references(
        self,
        prompt: str,
        image_paths: List[Path],
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.otu_api_key:
            raise ApiError("OTU_API_KEY 未配置")
        if not image_paths:
            raise ApiError("图片生成调用缺少参考图")

        headers = {"Authorization": f"Bearer {self.settings.otu_api_key}"}
        attempts = max(1, self.settings.image_retry_attempts)
        last_error: Optional[Exception] = None

        with httpx.Client(timeout=1200.0) as client:
            candidates = self.settings.image_model_candidates
            for model_index, model in enumerate(candidates):
                for attempt in range(1, attempts + 1):
                    normalized_prompt = _normalize_image_prompt(prompt, self.settings.image_size)
                    if progress:
                        progress(f"调用图片模型 {model}，第 {attempt}/{attempts} 次尝试，prompt {len(normalized_prompt)} 字符")
                    try:
                        with tempfile.TemporaryDirectory(prefix="omni_refs_") as tmp_dir:
                            upload_paths = [
                                _prepare_reference_image(
                                    path,
                                    Path(tmp_dir),
                                    self.settings.image_reference_max_side,
                                    self.settings.image_reference_jpeg_quality,
                                )
                                for path in image_paths
                            ]
                            if progress:
                                summary = "，".join(_describe_file(path) for path in upload_paths)
                                progress(f"上传参考图：{summary}")
                            if _is_async_gpt_image_model(model):
                                body, image_bytes = self._generate_async_image(
                                    client,
                                    headers,
                                    model,
                                    normalized_prompt,
                                    upload_paths,
                                    progress,
                                )
                            else:
                                if progress:
                                    progress("请求 /v1/images/edits（同步图生图）")
                                body = self._post_edits_json(client, headers, model, normalized_prompt, upload_paths)
                                image_bytes = _extract_image_bytes(client, body)
                        ensure_parent(output_path)
                        output_path.write_bytes(image_bytes)
                        return {
                            "path": str(output_path),
                            "model": model,
                            "task_id": body.get("id"),
                            "response_keys": sorted(body.keys()),
                            "attempt": attempt,
                        }
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        if _is_model_unavailable_error(exc) and model_index < len(candidates) - 1:
                            next_model = candidates[model_index + 1]
                            if progress:
                                progress(f"模型 {model} 当前不可用，切换到 {next_model}")
                            break
                        if not _is_retryable_status(exc.response.status_code) or attempt >= attempts:
                            raise
                        delay = self.settings.image_retry_base_seconds * attempt
                        if progress:
                            progress(f"图片接口返回 {exc.response.status_code}，{delay:.0f}s 后重试")
                        time.sleep(delay)
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        last_error = exc
                        if attempt >= attempts:
                            raise
                        delay = self.settings.image_retry_base_seconds * attempt
                        if progress:
                            progress(f"图片接口网络/超时错误，{delay:.0f}s 后重试")
                        time.sleep(delay)
                    except ApiError as exc:
                        last_error = exc
                        if attempt >= attempts:
                            raise
                        delay = self.settings.image_retry_base_seconds * attempt
                        if progress:
                            progress(f"异步图片任务失败，{delay:.0f}s 后重新提交：{exc}")
                        time.sleep(delay)

        raise ApiError(f"图片生成调用失败：{last_error}")

    def _generate_async_image(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        model: str,
        prompt: str,
        image_paths: List[Path],
        progress: Optional[Callable[[str], None]],
    ) -> tuple[Dict[str, Any], bytes]:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": self.settings.image_size,
        }
        if image_paths:
            payload["images"] = [_image_to_data_uri(path) for path in image_paths[:8]]
        if progress:
            mode = f"图生图，参考图 {len(image_paths[:8])} 张" if image_paths else "纯文生图"
            progress(f"提交 /v1/videos 异步图片任务（{mode}）")
        response = client.post(self.settings.video_url, headers=headers, json=payload)
        response.raise_for_status()
        completed = self._wait_for_async_image(client, headers, response.json(), progress)
        image_url = completed.get("url")
        if not image_url:
            raise ApiError(f"gpt-image-2 任务完成但未返回 url：{json.dumps(completed, ensure_ascii=False)[:500]}")
        if progress:
            progress(f"异步图片任务 {completed.get('id') or ''} 已完成，下载结果")
        image_response = client.get(image_url, follow_redirects=True, timeout=900.0)
        try:
            image_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiError(_format_http_status_error("gpt-image-2 图片下载失败", exc)) from exc
        return completed, image_response.content

    def _wait_for_async_image(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        task: Dict[str, Any],
        progress: Optional[Callable[[str], None]],
    ) -> Dict[str, Any]:
        task_id = task.get("id")
        if not task_id:
            raise ApiError(f"gpt-image-2 未返回任务 ID：{json.dumps(task, ensure_ascii=False)[:500]}")

        latest = task
        deadline = time.monotonic() + self.settings.image_timeout_seconds
        last_reported_status = ""
        last_reported_at = 0.0
        status_url = f"{self.settings.video_url.rstrip('/')}/{task_id}"
        while time.monotonic() < deadline:
            status = str(latest.get("status") or "").lower()
            if status == "completed":
                return latest
            if status == "failed":
                error_payload = latest.get("error", latest)
                raise ApiError(f"gpt-image-2 任务失败：{json.dumps(error_payload, ensure_ascii=False)}")
            now = time.monotonic()
            if progress and (status != last_reported_status or now - last_reported_at >= 30):
                progress(f"异步图片任务 {task_id} 状态：{status or 'unknown'}，进度 {latest.get('progress', 0)}%")
                last_reported_status = status
                last_reported_at = now
            time.sleep(self.settings.image_poll_interval_seconds)
            try:
                response = client.get(status_url, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if not _is_retryable_status(exc.response.status_code):
                    raise ApiError(_format_http_status_error("gpt-image-2 轮询失败", exc)) from exc
                if progress:
                    progress(f"异步图片轮询临时返回 HTTP {exc.response.status_code}，继续等待任务 {task_id}")
                continue
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if progress:
                    progress(f"异步图片轮询网络/超时错误，继续等待任务 {task_id}：{exc}")
                continue
            latest = response.json()
        raise ApiError(f"gpt-image-2 任务超时：{task_id}")

    def _post_generations_json(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        model: str,
        prompt: str,
        image_paths: List[Path],
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "prompt": prompt,
            "size": self.settings.image_size,
            "response_format": "b64_json",
        }
        if image_paths:
            payload["image"] = [_image_to_data_uri(path) for path in image_paths]
        response = client.post(self.settings.image_generations_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    def _post_edits_json(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        model: str,
        prompt: str,
        image_paths: List[Path],
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "prompt": prompt,
            "size": self.settings.image_size,
            "response_format": "b64_json",
            "image": [_image_to_data_uri(path) for path in image_paths],
        }
        response = client.post(self.settings.image_edits_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    def _post_edits_multipart(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        model: str,
        prompt: str,
        image_paths: List[Path],
    ) -> Dict[str, Any]:
        data = {
            "model": model,
            "prompt": prompt,
            "size": self.settings.image_size,
        }
        with ExitStack() as stack:
            files = []
            for path in image_paths:
                mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
                files.append(("image[]", (path.name, stack.enter_context(path.open("rb")), mime_type)))
            response = client.post(self.settings.image_edits_url, headers=headers, data=data, files=files)
            response.raise_for_status()
            return response.json()


class OmniClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_video(
        self,
        prompt: str,
        storyboard_path: Path,
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
        reference_paths: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.otu_api_key:
            raise ApiError("OTU_API_KEY 未配置")
        if not storyboard_path.exists():
            raise ApiError(f"故事版图片不存在：{storyboard_path}")
        extra_references = [path for path in (reference_paths or []) if path != storyboard_path]
        for path in extra_references:
            if not path.exists():
                raise ApiError(f"Omni 参考图不存在：{path}")

        headers = {"Authorization": f"Bearer {self.settings.otu_api_key}"}
        upload_paths = [storyboard_path, *extra_references]
        attempts = max(1, self.settings.omni_retry_attempts)
        upstream_retries = max(0, self.settings.omni_upstream_retry_attempts)

        with httpx.Client(timeout=900.0) as client:
            for task_attempt in range(1, upstream_retries + 2):
                last_error: Optional[Exception] = None
                for attempt in range(1, attempts + 1):
                    if progress:
                        progress(f"调用视频模型 {self.settings.omni_model}，第 {task_attempt}/{upstream_retries + 1} 次提交，第 {attempt}/{attempts} 次尝试")
                    try:
                        if progress:
                            if len(upload_paths) == 1:
                                progress("请求 /v1/videos（multipart/form-data，本地故事版图 input_reference）")
                            else:
                                progress(f"请求 /v1/videos（multipart/form-data，本地参考图 input_reference x{len(upload_paths)}）")
                        task = self._submit_video_task(client, headers, prompt, upload_paths)
                        break
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        if not _is_retryable_status(exc.response.status_code) or attempt >= attempts:
                            raise ApiError(_format_http_status_error("Omni 提交失败", exc)) from exc
                        delay = self.settings.omni_retry_base_seconds * attempt
                        if progress:
                            progress(f"视频接口返回 {exc.response.status_code}，{delay:.0f}s 后重试")
                        time.sleep(delay)
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        last_error = exc
                        if attempt >= attempts:
                            raise ApiError(f"Omni 提交网络/超时失败：{exc}") from exc
                        delay = self.settings.omni_retry_base_seconds * attempt
                        if progress:
                            progress(f"视频接口网络/超时错误，{delay:.0f}s 后重试")
                        time.sleep(delay)
                else:
                    raise ApiError(f"Omni 提交失败：{last_error}")

                try:
                    completed = self._wait_for_video(client, headers, task, progress)
                    break
                except RetryableVideoTaskError as exc:
                    if task_attempt > upstream_retries:
                        raise ApiError(str(exc)) from exc
                    if progress:
                        progress(f"Omni 返回 upstream_error，自动重新提交 {task_attempt}/{upstream_retries}：{exc}")
                    continue

            video_url = completed.get("video_url")
            if not video_url:
                raise ApiError("Omni 任务完成但未返回 video_url")

            video_response = client.get(video_url, follow_redirects=True, timeout=900.0)
            try:
                video_response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ApiError(_format_http_status_error("Omni 视频下载失败", exc)) from exc
            ensure_parent(output_path)
            output_path.write_bytes(video_response.content)
            return {
                "task_id": completed.get("id"),
                "path": str(output_path),
                "video_url": video_url,
            }

    def _submit_video_task(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        prompt: str,
        image_paths: List[Path],
    ) -> Dict[str, Any]:
        with ExitStack() as stack:
            files = [
                ("model", (None, self.settings.omni_model)),
                ("prompt", (None, prompt)),
                ("size", (None, self.settings.video_size)),
            ]
            for image_path in image_paths:
                mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
                files.append(("input_reference", (image_path.name, stack.enter_context(image_path.open("rb")), mime_type)))
            response = client.post(self.settings.video_url, headers=headers, files=files)
            response.raise_for_status()
            return response.json()

    def _wait_for_video(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        task: Dict[str, Any],
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        status = task.get("status")
        if status == "completed":
            return task
        if status == "failed":
            error_payload = task.get("error", task)
            message = f"Omni 任务失败：{json.dumps(error_payload, ensure_ascii=False)}"
            if _is_upstream_error(error_payload):
                raise RetryableVideoTaskError(message)
            raise ApiError(message)

        task_id = task.get("id")
        if not task_id:
            raise ApiError(f"Omni 未返回任务 ID：{json.dumps(task, ensure_ascii=False)}")

        deadline = time.monotonic() + self.settings.omni_timeout_seconds
        status_url = f"{self.settings.video_url.rstrip('/')}/{task_id}"
        while time.monotonic() < deadline:
            time.sleep(self.settings.omni_poll_interval_seconds)
            try:
                response = client.get(status_url, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if not _is_retryable_status(exc.response.status_code):
                    raise ApiError(_format_http_status_error("Omni 轮询失败", exc)) from exc
                if progress:
                    progress(f"Omni 轮询临时返回 HTTP {exc.response.status_code}，继续等待任务 {task_id}")
                continue
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if progress:
                    progress(f"Omni 轮询网络/超时错误，继续等待任务 {task_id}：{exc}")
                continue
            body = response.json()
            status = body.get("status")
            if status == "completed":
                return body
            if status == "failed":
                error_payload = body.get("error", body)
                message = f"Omni 任务失败：{json.dumps(error_payload, ensure_ascii=False)}"
                if _is_upstream_error(error_payload):
                    raise RetryableVideoTaskError(message)
                raise ApiError(message)
        raise ApiError(f"Omni 任务超时：{task_id}")


class GrokClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.grok_api_key}",
            "Content-Type": "application/json",
        }

    @property
    def _text_to_image_url(self) -> str:
        return f"{self.settings.grok_base_url.rstrip('/')}/openapi/v2/rhart-image-g-2/text-to-image"

    @property
    def _image_to_image_url(self) -> str:
        return f"{self.settings.grok_base_url.rstrip('/')}/openapi/v2/rhart-image-g-2/image-to-image"

    @property
    def _image_to_video_url(self) -> str:
        return f"{self.settings.grok_base_url.rstrip('/')}/openapi/v2/rhart-video-g/image-to-video"

    @property
    def _query_url(self) -> str:
        return f"{self.settings.grok_base_url.rstrip('/')}/openapi/v2/query"

    def generate_from_prompt(
        self,
        prompt: str,
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.grok_api_key:
            raise ApiError("GROK_API_KEY 未配置")
        payload = {
            "prompt": prompt,
            "aspectRatio": self.settings.grok_image_aspect_ratio,
            "resolution": self.settings.grok_image_resolution,
        }
        if progress:
            progress(f"请求 Grok 文生图 G-2.0，{self.settings.grok_image_resolution}，{self.settings.grok_image_aspect_ratio}")
        return self._submit_wait_download(self._text_to_image_url, payload, output_path, "Grok 文生图", progress)

    def generate_with_references(
        self,
        prompt: str,
        image_paths: List[Path],
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.grok_api_key:
            raise ApiError("GROK_API_KEY 未配置")
        if not image_paths:
            raise ApiError("Grok 图生图缺少参考图")

        with tempfile.TemporaryDirectory(prefix="grok_refs_") as tmp_dir:
            upload_paths = [
                _prepare_reference_image(
                    path,
                    Path(tmp_dir),
                    self.settings.image_reference_max_side,
                    self.settings.image_reference_jpeg_quality,
                )
                for path in image_paths
            ]
            if progress:
                summary = "，".join(_describe_file(path) for path in upload_paths)
                progress(f"参考图转 data URI：{summary}")
            payload = {
                "prompt": prompt,
                "imageUrls": [_image_to_data_uri(path) for path in upload_paths],
                "aspectRatio": self.settings.grok_image_aspect_ratio,
                "resolution": self.settings.grok_image_resolution,
            }
            if progress:
                progress(f"请求 Grok 图生图 G-2.0，{self.settings.grok_image_resolution}，{self.settings.grok_image_aspect_ratio}")
            return self._submit_wait_download(self._image_to_image_url, payload, output_path, "Grok 图生图", progress)

    def generate_video(
        self,
        prompt: str,
        storyboard_path: Path,
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
        duration: Optional[int] = None,
        reference_paths: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.grok_api_key:
            raise ApiError("GROK_API_KEY 未配置")
        if not storyboard_path.exists():
            raise ApiError(f"故事版图片不存在：{storyboard_path}")

        with tempfile.TemporaryDirectory(prefix="grok_video_ref_") as tmp_dir:
            upload_path = _prepare_grok_video_reference_image(
                storyboard_path,
                Path(tmp_dir),
                self.settings.image_reference_jpeg_quality,
                self.settings.grok_video_aspect_ratio,
            )
            extra_upload_paths = [
                _prepare_reference_image(
                    path,
                    Path(tmp_dir),
                    self.settings.image_reference_max_side,
                    self.settings.image_reference_jpeg_quality,
                )
                for path in (reference_paths or [])
                if path.exists()
            ]
            seconds = _clamp_int(duration or self.settings.grok_video_duration, 6, 30)
            if progress:
                extra_summary = f"，附加参考图：{'，'.join(_describe_file(path) for path in extra_upload_paths)}" if extra_upload_paths else ""
                progress(f"故事版首镜头转 {self.settings.grok_video_aspect_ratio} 视频参考图：{_describe_file(upload_path)}{extra_summary}")
            reference_variants = _grok_video_reference_variants(upload_path, extra_upload_paths)
            last_error: Optional[ApiError] = None
            for variant_index, (variant_label, variant_paths) in enumerate(reference_variants, start=1):
                payload = {
                    "prompt": prompt,
                    "aspectRatio": self.settings.grok_video_aspect_ratio,
                    "imageUrls": [_image_to_data_uri(path) for path in variant_paths][:7],
                    "resolution": self.settings.grok_video_resolution,
                    "duration": seconds,
                }
                if progress:
                    progress(
                        f"请求 Grok 图生视频 X v1.5，{self.settings.grok_video_resolution}，{seconds}s，"
                        f"参考策略 {variant_index}/{len(reference_variants)}：{variant_label}（{len(payload['imageUrls'])} 张）"
                    )
                try:
                    return self._submit_wait_download(self._image_to_video_url, payload, output_path, "Grok 图生视频", progress)
                except ApiError as exc:
                    if not _is_grok_model_task_failure(exc) or variant_index >= len(reference_variants):
                        raise
                    last_error = exc
                    if progress:
                        progress(f"Grok 模型生成失败，切换更稳参考策略重试：{exc}")
            if last_error:
                raise last_error
            raise ApiError("Grok 图生视频未执行")

    def _submit_wait_download(
        self,
        url: str,
        payload: Dict[str, Any],
        output_path: Path,
        label: str,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        attempts = max(1, self.settings.grok_retry_attempts)
        with httpx.Client(timeout=900.0) as client:
            last_error: Optional[Exception] = None
            for attempt in range(1, attempts + 1):
                if progress:
                    progress(f"{label}提交任务，第 {attempt}/{attempts} 次尝试")
                try:
                    response = client.post(url, headers=self._headers, json=payload)
                    response.raise_for_status()
                    task = response.json()
                    if not _runninghub_task_id(task):
                        raise ApiError(f"{label}未返回 taskId：{json.dumps(task, ensure_ascii=False)[:500]}")

                    completed = self._wait_for_task(client, task, label, progress)
                    result_url = _extract_runninghub_result_url(completed)
                    if not result_url:
                        raise ApiError(f"{label}任务完成但未返回结果 URL：{json.dumps(completed, ensure_ascii=False)[:500]}")

                    result_response = client.get(result_url, follow_redirects=True, timeout=900.0)
                    try:
                        result_response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise ApiError(_format_http_status_error(f"{label}结果下载失败", exc)) from exc
                    ensure_parent(output_path)
                    output_path.write_bytes(result_response.content)
                    return {
                        "task_id": completed.get("taskId"),
                        "path": str(output_path),
                        "url": result_url,
                    }
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    if not _is_retryable_status(exc.response.status_code) or attempt >= attempts:
                        raise ApiError(_format_http_status_error(f"{label}提交失败", exc)) from exc
                    delay = self.settings.grok_retry_base_seconds * attempt
                    if progress:
                        progress(f"Grok 接口返回 {exc.response.status_code}，{delay:.0f}s 后重试")
                    time.sleep(delay)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    if attempt >= attempts:
                        raise ApiError(f"{label}提交网络/超时失败：{exc}") from exc
                    delay = self.settings.grok_retry_base_seconds * attempt
                    if progress:
                        progress(f"Grok 接口网络/超时错误，{delay:.0f}s 后重试")
                    time.sleep(delay)
                except ApiError as exc:
                    last_error = exc
                    if not _is_runninghub_retryable_error(exc) or attempt >= attempts:
                        raise
                    delay = self.settings.grok_retry_base_seconds * attempt
                    if progress:
                        progress(f"{label}返回可重试错误，{delay:.0f}s 后重试：{_short_error(exc)}")
                    time.sleep(delay)
            raise ApiError(f"{label}提交失败：{last_error}")

    def _wait_for_task(
        self,
        client: httpx.Client,
        task: Dict[str, Any],
        label: str,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        task_id = _runninghub_task_id(task)
        if not task_id:
            raise ApiError(f"{label}未返回 taskId：{json.dumps(task, ensure_ascii=False)[:500]}")

        deadline = time.monotonic() + self.settings.grok_timeout_seconds
        latest = task
        last_reported_status = ""
        last_reported_at = 0.0
        while time.monotonic() < deadline:
            status = str(latest.get("status") or "").upper()
            if status == "SUCCESS":
                if progress:
                    progress(f"{label}任务 {task_id} 状态：SUCCESS，开始下载结果")
                return latest
            if status == "FAILED":
                raise ApiError(f"{label}任务失败：{json.dumps(latest, ensure_ascii=False)[:800]}")
            now = time.monotonic()
            should_report = status != last_reported_status or now - last_reported_at >= 30
            if progress and should_report:
                progress(f"{label}任务 {task_id} 状态：{status or 'UNKNOWN'}")
                last_reported_status = status
                last_reported_at = now
            time.sleep(self.settings.grok_poll_interval_seconds)
            response = client.post(self._query_url, headers=self._headers, json={"taskId": task_id})
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if not _is_retryable_status(exc.response.status_code):
                    raise ApiError(_format_http_status_error(f"{label}查询失败", exc)) from exc
                if progress:
                    progress(f"{label}查询临时返回 HTTP {exc.response.status_code}，继续等待任务 {task_id}")
                continue
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if progress:
                    progress(f"{label}查询网络/超时错误，继续等待任务 {task_id}：{exc}")
                continue
            latest = response.json()
        raise ApiError(f"{label}任务超时：{task_id}")


class RunningHubSkyReelsClient(GrokClient):
    @property
    def _skyreels_omni_fast_url(self) -> str:
        return f"{self.settings.grok_base_url.rstrip('/')}/openapi/v2/skyreels-v4/omni-reference-fast"

    def generate_video(
        self,
        prompt: str,
        storyboard_path: Path,
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
        duration: Optional[int] = None,
        reference_paths: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        if not self.settings.grok_api_key:
            raise ApiError("GROK_API_KEY 未配置")
        if not storyboard_path.exists():
            raise ApiError(f"参考图片不存在：{storyboard_path}")

        existing_references = [path for path in (reference_paths or []) if path.exists()]
        image_paths = [storyboard_path, *existing_references][:3]
        seconds = _clamp_int(duration or self.settings.grok_video_duration, 3, 15)
        prompt_text = _normalize_skyreels_prompt(prompt, len(image_paths))

        with tempfile.TemporaryDirectory(prefix="skyreels_refs_") as tmp_dir:
            upload_paths = [
                _prepare_reference_image(
                    path,
                    Path(tmp_dir),
                    self.settings.image_reference_max_side,
                    self.settings.image_reference_jpeg_quality,
                )
                for path in image_paths
            ]
            ref_image_data = [_image_to_data_uri(path) for path in upload_paths]
            base_payload = {
                "prompt": prompt_text,
                "aspectRatio": self.settings.grok_video_aspect_ratio,
                "duration": seconds,
                "promptOptimizer": True,
                "resolution": self.settings.grok_video_resolution,
            }
            if progress:
                summary = "，".join(_describe_file(path) for path in upload_paths)
                progress(
                    "请求 RunningHub SkyReels V4 Omni 参考视频-fast，"
                    f"{self.settings.grok_video_resolution}，{self.settings.grok_video_aspect_ratio}，{seconds}s，"
                    f"参考图 {len(upload_paths)}/3：{summary}，prompt {len(prompt_text)} 字符"
                )
            return self._submit_skyreels_variants(base_payload, ref_image_data, output_path, progress)

    def _submit_skyreels_variants(
        self,
        base_payload: Dict[str, Any],
        ref_image_data: List[str],
        output_path: Path,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        variants = _skyreels_ref_image_variants(ref_image_data)
        last_error: Optional[ApiError] = None
        for index, (variant_label, ref_images) in enumerate(variants, start=1):
            payload = {**base_payload, "refImages": ref_images}
            if progress:
                progress(f"SkyReels V4 Omni 参考图格式：{variant_label}，第 {index}/{len(variants)} 种")
            try:
                return self._submit_wait_download(self._skyreels_omni_fast_url, payload, output_path, "SkyReels V4 Omni", progress)
            except ApiError as exc:
                last_error = exc
                if not _is_skyreels_variant_fallback_error(exc) or index == len(variants):
                    raise
                if progress:
                    progress(f"SkyReels V4 Omni 当前参考图格式失败，切换下一种：{_short_error(exc)}")
        if last_error:
            raise last_error
        raise ApiError("SkyReels V4 Omni 未提交任务")


def _extract_image_bytes(client: httpx.Client, body: Dict[str, Any]) -> bytes:
    data = body.get("data")
    if not data or not isinstance(data, list):
        raise ApiError(f"image2 响应缺少 data：{json.dumps(body, ensure_ascii=False)[:500]}")

    first = data[0]
    if not isinstance(first, dict):
        raise ApiError("image2 响应 data[0] 格式不正确")

    b64_json = first.get("b64_json")
    if b64_json:
        return _decode_base64_image(b64_json)

    url = first.get("url")
    if url:
        response = client.get(url, follow_redirects=True, timeout=900.0)
        response.raise_for_status()
        return response.content

    raise ApiError(f"image2 响应缺少 b64_json/url：{json.dumps(first, ensure_ascii=False)[:500]}")


def _is_async_gpt_image_model(model: str) -> bool:
    return str(model).lower() in {"gpt-image-2", "gpt-image-2-2k", "gpt-image-2-4k"}


def _decode_base64_image(value: str) -> bytes:
    if "," in value and value.strip().startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}


def _runninghub_task_id(body: Dict[str, Any]) -> Optional[str]:
    task_id = body.get("taskId") or body.get("id")
    return str(task_id) if task_id else None


def _skyreels_ref_image_variants(ref_image_data: List[str]) -> List[tuple[str, List[Dict[str, str]]]]:
    def build(value_key: str, *, include_type: bool = True) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        for index, data_uri in enumerate(ref_image_data, start=1):
            item = {"tag": f"image_{index}", value_key: data_uri}
            if include_type:
                item = {"type": "image", **item}
            items.append(item)
        return items

    return [
        ("type+tag+url", build("url")),
        ("type+tag+imageUrl", build("imageUrl")),
        ("tag+url", build("url", include_type=False)),
        ("type+tag+image", build("image")),
    ]


def _is_skyreels_ref_images_error(exc: ApiError) -> bool:
    text = str(exc).lower()
    return "refimages" in text or "ref_images" in text


def _is_skyreels_variant_fallback_error(exc: ApiError) -> bool:
    if _is_skyreels_ref_images_error(exc):
        return True
    text = str(exc).lower()
    return "skyreels v4 omni任务失败" in text and (
        '"errorcode": "1005"' in text
        or '"errorcode":"1005"' in text
        or "internal server error" in text
        or "系统内部错误" in text
    )


def _is_runninghub_retryable_error(exc: ApiError) -> bool:
    text = str(exc).lower()
    retryable_tokens = [
        '"errorcode": "1000"',
        '"errorcode":"1000"',
        '"errorcode": "1010"',
        '"errorcode":"1010"',
        '"errorcode": "1011"',
        '"errorcode":"1011"',
        '"errorcode": "1005"',
        '"errorcode":"1005"',
        "internal server error",
        "系统内部错误",
        "unknown error",
        "未知错误",
        "service unavailable",
        "服务暂不可用",
        "model is currently busy",
        "模型负载较高",
        "please retry",
        "请重试",
    ]
    return any(token in text for token in retryable_tokens)


def _short_error(exc: Exception, limit: int = 220) -> str:
    text = str(exc).strip().replace("\n", " ")
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


def _is_model_unavailable_error(exc: httpx.HTTPStatusError) -> bool:
    try:
        body = exc.response.json()
    except Exception:
        body = {}
    error = body.get("error") if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        error = {}
    code = str(error.get("code") or "").lower()
    message = str(error.get("message") or "").lower()
    return (
        "model_not_found" in code
        or "model_not_found" in message
        or "no available channel for model" in message
    )


def _extract_model_ids(body: Any) -> List[str]:
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if not isinstance(data, list):
        return []

    model_ids: List[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
        else:
            model_id = str(item)
        if model_id:
            model_ids.append(str(model_id))
    return model_ids


def _extract_runninghub_result_url(body: Dict[str, Any]) -> Optional[str]:
    results = body.get("results")
    if not isinstance(results, list):
        return None
    for item in results:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return None


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _format_http_status_error(context: str, exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    detail = ""
    try:
        body = response.json()
        detail = json.dumps(body, ensure_ascii=False)
    except Exception:
        detail = response.text
    detail = detail.strip()
    if len(detail) > 800:
        detail = f"{detail[:800]}..."
    if detail:
        return f"{context}：HTTP {response.status_code}，响应：{detail}"
    return f"{context}：HTTP {response.status_code}"


def _normalize_image_prompt(prompt: str, image_size: str) -> str:
    aspect_ratio = _aspect_ratio_from_size(image_size) or "4:3"
    normalized = prompt.replace("8K分辨率", f"4K分辨率，画面比例{aspect_ratio}，输出尺寸{image_size}")
    normalized = normalized.replace("8K 分辨率", f"4K分辨率，画面比例{aspect_ratio}，输出尺寸{image_size}")
    normalized = normalized.replace("8K", "4K")
    return normalized


def _aspect_ratio_from_size(size: str) -> str:
    try:
        width_text, height_text = str(size).lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except Exception:
        return ""
    if width <= 0 or height <= 0:
        return ""

    def gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a or 1

    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _image_to_data_uri(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _prepare_reference_image(path: Path, tmp_dir: Path, max_side: int, jpeg_quality: int) -> Path:
    max_side = max(512, max_side)
    jpeg_quality = min(95, max(50, jpeg_quality))
    output = tmp_dir / f"{path.stem}-ref.jpg"

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        width, height = image.size
        scale = min(1.0, max_side / max(width, height))
        if scale < 1.0:
            resized = (max(1, round(width * scale)), max(1, round(height * scale)))
            image = image.resize(resized, Image.Resampling.LANCZOS)
        image.save(output, format="JPEG", quality=jpeg_quality, optimize=True)
    return output


def _prepare_grok_video_reference_image(path: Path, tmp_dir: Path, jpeg_quality: int, aspect_ratio: str) -> Path:
    jpeg_quality = min(95, max(50, jpeg_quality))
    target_size = _target_size_for_aspect_ratio(aspect_ratio)
    output = tmp_dir / f"{path.stem}-video-{aspect_ratio.replace(':', 'x')}.jpg"

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        frame = _extract_storyboard_first_frame(image)
        frame = ImageOps.fit(frame, target_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
        frame.save(output, format="JPEG", quality=jpeg_quality, optimize=True)
    return output


def _extract_storyboard_first_frame(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width < 900 or height < 650 or width / max(1, height) < 1.15:
        return image.copy()

    header = min(max(round(height * 0.04), 28), 64)
    columns = 4
    rows = 3
    cell_width = width / columns
    cell_height = (height - header) / rows
    left = round(cell_width * 0.02)
    top = header + round(cell_height * 0.03)
    right = round(cell_width * 0.98)
    bottom = header + round(cell_height * 0.70)
    return image.crop((left, top, right, bottom))


def _target_size_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    try:
        width_ratio, height_ratio = [int(part) for part in aspect_ratio.split(":", 1)]
    except Exception:
        width_ratio, height_ratio = 9, 16
    if width_ratio <= 0 or height_ratio <= 0:
        width_ratio, height_ratio = 9, 16

    long_side = 1280
    if height_ratio >= width_ratio:
        height = long_side
        width = max(64, round(height * width_ratio / height_ratio))
    else:
        width = long_side
        height = max(64, round(width * height_ratio / width_ratio))
    return width, height


def _grok_video_reference_variants(primary_path: Path, extra_paths: List[Path]) -> List[tuple[str, List[Path]]]:
    variants: List[tuple[str, List[Path]]] = []
    full_paths = [primary_path, *extra_paths]
    variants.append(("9:16首镜头 + 产品/人物参考", full_paths))
    if extra_paths:
        product_only_paths = [primary_path, extra_paths[0]]
        if product_only_paths != full_paths:
            variants.append(("9:16首镜头 + 产品参考", product_only_paths))
    variants.append(("仅9:16首镜头", [primary_path]))

    unique_variants: List[tuple[str, List[Path]]] = []
    seen: set[tuple[str, ...]] = set()
    for label, paths in variants:
        key = tuple(str(path) for path in paths)
        if key not in seen:
            seen.add(key)
            unique_variants.append((label, paths))
    return unique_variants


def _normalize_skyreels_prompt(prompt: str, image_count: int) -> str:
    reference_labels = [
        "@image_1=当前片段故事版图/镜头结构参考",
        "@image_2=产品参考图，必须锁定产品外观",
        "@image_3=人物参考图，保持人物一致",
    ][: max(1, image_count)]
    prefix = (
        "严格按当前片段完整脚本生成短视频，不得省略、不得重排镜头时间段。"
        "参考图标签："
        + "；".join(reference_labels)
        + "。输出必须竖屏/横屏比例遵循接口 aspectRatio。脚本如下：\n"
    )
    max_length = 2500
    if len(prefix) >= max_length:
        return prefix[:max_length]
    remaining = max_length - len(prefix)
    if len(prompt) <= remaining:
        return prefix + prompt
    suffix = "\n[因 RunningHub SkyReels prompt 2500 字符限制，后续脚本文本已截断。]"
    body_length = max(0, remaining - len(suffix))
    return prefix + prompt[:body_length] + suffix


def _is_grok_model_task_failure(exc: ApiError) -> bool:
    message = str(exc)
    return "Grok 图生视频任务失败" in message or "Model response exception" in message or "模型响应异常" in message


def _is_upstream_error(payload: Any) -> bool:
    if isinstance(payload, dict):
        code = str(payload.get("code", "")).lower()
        if code == "upstream_error":
            return True
        message = json.dumps(payload, ensure_ascii=False).lower()
    else:
        message = str(payload).lower()
    return "upstream_error" in message


def _describe_file(path: Path) -> str:
    size_mb = path.stat().st_size / (1024 * 1024)
    try:
        with Image.open(path) as image:
            return f"{image.width}x{image.height}/{size_mb:.1f}MB"
    except Exception:
        return f"{size_mb:.1f}MB"
