from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .api_clients import ApiError, GrokClient, Image2Client, OmniClient, RunningHubSkyReelsClient
from .config import Settings, mask_secrets
from .files import (
    ScriptFile,
    character_image_path,
    ensure_parent,
    image_matches_aspect,
    scan_scripts,
    script_to_dict,
    storyboard_image_path,
    summarize_catalog,
    video_output_path,
)
from .markdown_parser import Segment, build_direct_video_prompt, build_video_prompt, character_source_segment_index
from .product_lock import (
    build_storyboard_product_lock_prompt,
    has_current_storyboard_product_lock,
    write_storyboard_product_lock_meta,
)


VALID_STAGES = {"all", "characters", "storyboards", "videos", "direct_videos", "repair", "smart"}


class JobCancelled(Exception):
    pass


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{settings.provider}-job-queue")
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._job_order: List[str] = []
        self._futures: Dict[str, Any] = {}

    def start(
        self,
        stage: str = "all",
        overwrite: Optional[bool] = None,
        script_paths: Optional[List[str]] = None,
        script_concurrency: Optional[int] = None,
        reference_images: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if stage not in VALID_STAGES:
            raise ValueError(f"未知任务阶段：{stage}")

        selected_scripts = _normalize_script_paths(script_paths)
        selected_references = _normalize_reference_images(reference_images)
        if stage != "characters":
            scripts = scan_scripts(self.settings)
            if selected_scripts is not None:
                scripts = [script for script in scripts if script.md_path.resolve() in selected_scripts]
            _bind_script_references(scripts, selected_references, require_selection=True)
        selected_concurrency = _normalize_script_concurrency(script_concurrency, self.settings.script_concurrency)
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        job = {
            "id": job_id,
            "stage": stage,
            "overwrite": self.settings.overwrite if overwrite is None else bool(overwrite),
            "script_paths": sorted(str(path) for path in selected_scripts) if selected_scripts is not None else None,
            "reference_images": {key: str(path) for key, path in selected_references.items()},
            "script_concurrency": selected_concurrency,
            "status": "queued",
            "cancel_requested": False,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "total": 0,
            "done": 0,
            "stats": {"generated": 0, "skipped": 0},
            "active_scripts": {},
            "script_statuses": {},
            "logs": [],
            "errors": [],
            "result": None,
        }
        with self._lock:
            queued_ahead = sum(1 for item in self._jobs.values() if item.get("status") in {"queued", "running"})
            job["queued_ahead"] = queued_ahead
            self._jobs[job_id] = job
            self._job_order.append(job_id)
        if queued_ahead:
            self._log(job_id, "info", f"任务已加入队列，前方 {queued_ahead} 个任务")
        else:
            self._log(job_id, "info", "任务已加入队列，等待调度")
        future = self._submit_job(job_id)
        with self._lock:
            self._futures[job_id] = future
        return self.get(job_id)

    def _submit_job(self, job_id: str) -> Any:
        return self._executor.submit(self._run, job_id)

    def cancel(self, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        now = time.time()
        target_ids: List[str] = []
        with self._lock:
            for candidate_id in reversed(self._job_order):
                job = self._jobs[candidate_id]
                if job_id is not None and candidate_id != job_id:
                    continue
                if job.get("status") not in {"queued", "running"}:
                    continue
                job["cancel_requested"] = True
                target_ids.append(candidate_id)
                future = self._futures.get(candidate_id)
                if job.get("status") == "queued":
                    if future is None or future.cancel():
                        job["status"] = "canceled"
                        job["finished_at"] = now
                if job_id is not None:
                    break

        for target_id in target_ids:
            target = self.get(target_id)
            if target.get("started_at") is None:
                self._log(target_id, "info", "已取消排队任务")
            else:
                self._log(target_id, "info", "已请求停止任务：当前 API 调用返回后不会继续处理后续片段")
        return [self.get(target_id) for target_id in target_ids]

    def update_concurrency(self, script_concurrency: int, job_id: Optional[str] = None) -> Dict[str, Any]:
        selected_concurrency = _normalize_script_concurrency(script_concurrency, self.settings.script_concurrency)
        target_id: Optional[str] = None
        with self._lock:
            if job_id is not None:
                job = self._jobs.get(job_id)
                if job and job.get("status") in {"queued", "running"}:
                    target_id = job_id
            else:
                for status in ("running", "queued"):
                    for candidate_id in reversed(self._job_order):
                        job = self._jobs[candidate_id]
                        if job.get("status") == status:
                            target_id = candidate_id
                            break
                    if target_id is not None:
                        break
            if target_id is None:
                raise ValueError("没有正在运行的任务可调整并发")
            previous = self._jobs[target_id].get("script_concurrency")
            self._jobs[target_id]["script_concurrency"] = selected_concurrency
        if previous != selected_concurrency:
            self._log(target_id, "info", f"脚本并发已调整为 {selected_concurrency}；正在调用中的脚本不会被中断")
        return self.get(target_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._snapshot(self._jobs[job_id]) for job_id in reversed(self._job_order)]

    def latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._job_order:
                return None
            return self._snapshot(self._jobs[self._job_order[-1]])

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._snapshot(self._jobs[job_id])

    def _run(self, job_id: str) -> None:
        if self._is_cancel_requested(job_id):
            self._update(job_id, status="canceled", finished_at=time.time())
            return
        self._update(job_id, status="running", started_at=time.time())
        self._log(job_id, "info", "任务开始")
        try:
            self._raise_if_cancelled(job_id)
            self._run_pipeline(job_id)
            snapshot = self.get(job_id)
            if snapshot.get("cancel_requested"):
                self._mark_incomplete_script_statuses(job_id, "canceled", "任务已停止")
                self._update(job_id, status="canceled", finished_at=time.time(), active_scripts={})
                self._log(job_id, "info", "任务已停止")
            elif snapshot.get("errors"):
                self._update(job_id, status="failed", finished_at=time.time(), active_scripts={})
                self._log(job_id, "error", f"任务完成但有 {len(snapshot['errors'])} 个错误")
            else:
                self._update(job_id, status="completed", finished_at=time.time(), active_scripts={})
                self._log(job_id, "success", "任务完成")
        except JobCancelled:
            self._mark_incomplete_script_statuses(job_id, "canceled", "任务已停止")
            self._update(job_id, status="canceled", finished_at=time.time(), active_scripts={})
            self._log(job_id, "info", "任务已停止")
        except Exception as exc:
            message = self._safe(str(exc))
            self._mark_incomplete_script_statuses(job_id, "failed", message)
            self._update(job_id, status="failed", finished_at=time.time(), active_scripts={})
            self._error(job_id, message)

    def _run_pipeline(self, job_id: str) -> None:
        self._raise_if_cancelled(job_id)
        job = self.get(job_id)
        stage = job["stage"]
        overwrite = job["overwrite"]
        selected_scripts = _normalize_script_paths(job.get("script_paths"))
        selected_references = _normalize_reference_images(job.get("reference_images"))
        scripts = scan_scripts(self.settings)
        if selected_scripts is not None:
            scripts = [script for script in scripts if script.md_path.resolve() in selected_scripts]
            if not scripts:
                raise ValueError("没有匹配的已勾选脚本")
        scripts = _bind_script_references(scripts, selected_references, require_selection=stage != "characters")
        if stage == "smart":
            if overwrite:
                self._run_relay_pipeline(job_id, selected_scripts, scripts, overwrite)
            else:
                self._run_repair_pipeline(job_id, selected_scripts, scripts)
            return
        if stage == "repair":
            self._run_repair_pipeline(job_id, selected_scripts, scripts)
            return
        if stage == "all":
            self._run_relay_pipeline(job_id, selected_scripts, scripts, overwrite)
            return
        if stage == "direct_videos":
            self._run_direct_video_relay_pipeline(job_id, selected_scripts, scripts, overwrite)
            return

        stages = _expand_stages(stage)
        if selected_scripts is not None:
            scripts = [script for script in scripts if script.md_path.resolve() in selected_scripts]
            if not scripts:
                raise ValueError("没有匹配的已勾选脚本")
        self._init_script_statuses(job_id, scripts)
        self._update(job_id, total=sum(len(script.segments) * len(stages) for script in scripts))
        scope = "已勾选" if selected_scripts is not None else "全部"
        concurrency = self._script_concurrency(job_id, scripts)
        self._log(job_id, "info", f"扫描到 {len(scripts)} 个{scope}脚本，执行阶段：{', '.join(stages)}；脚本并发 {concurrency}")

        for current_stage in stages:
            self._raise_if_cancelled(job_id)
            self._log(job_id, "info", f"开始执行{_stage_display_label(current_stage)}")
            error_count_before_stage = len(self.get(job_id).get("errors", []))

            def process_stage_script(script: ScriptFile) -> None:
                self._raise_if_cancelled(job_id)
                local_failed = False
                self._set_script_status(job_id, script, "running", f"{_stage_display_label(current_stage)}开始", current_stage)
                if current_stage in {"storyboards", "videos", "direct_videos"} and script.reference_image is None:
                    self._error(job_id, f"{script.product_name} 缺少产品参考图，跳过{_stage_display_label(current_stage)}：{script.md_path.name}")
                    self._increment(job_id, len(script.segments))
                    self._set_script_status(job_id, script, "failed", f"缺少产品参考图，跳过{_stage_display_label(current_stage)}", current_stage)
                    return

                self._log(job_id, "info", f"{_stage_display_label(current_stage)} · 处理 {script.product_name} / {script.md_path.name}")
                try:
                    for segment in script.segments:
                        self._raise_if_cancelled(job_id)
                        self._set_active_script(job_id, script, current_stage, segment)
                        self._set_script_status(job_id, script, "running", f"{_stage_display_label(current_stage)} · 片段{segment.index}", current_stage, segment)
                        if current_stage == "characters":
                            image_client, image_api, image_settings = self._image_client_for("characters")
                            step_ok = self._run_step(
                                job_id,
                                f"片段{segment.index} 人物图",
                                self._process_character,
                                job_id,
                                image_client,
                                script,
                                segment,
                                overwrite,
                                image_api,
                                image_settings,
                                script=script,
                                stage=current_stage,
                                segment=segment,
                            )
                        elif current_stage == "storyboards":
                            image_client, image_api, image_settings = self._image_client_for("storyboards")
                            step_ok = self._run_step(
                                job_id,
                                f"片段{segment.index} 故事版图",
                                self._process_storyboard,
                                job_id,
                                image_client,
                                script,
                                segment,
                                overwrite,
                                image_api,
                                image_settings,
                                script=script,
                                stage=current_stage,
                                segment=segment,
                            )
                        elif current_stage == "videos":
                            video_client, video_api, video_settings = self._video_client_for()
                            step_ok = self._run_step(
                                job_id,
                                f"片段{segment.index} {self.settings.video_display_label}",
                                self._process_video,
                                job_id,
                                video_client,
                                script,
                                segment,
                                overwrite,
                                video_api,
                                video_settings,
                                script=script,
                                stage=current_stage,
                                segment=segment,
                            )
                        elif current_stage == "direct_videos":
                            video_client, video_api, video_settings = self._video_client_for()
                            step_ok = self._run_step(
                                job_id,
                                f"片段{segment.index} 快速模式{self.settings.video_display_label}",
                                self._process_direct_video,
                                job_id,
                                video_client,
                                script,
                                segment,
                                overwrite,
                                video_api,
                                video_settings,
                                script=script,
                                stage=current_stage,
                                segment=segment,
                            )
                        else:
                            step_ok = True
                        if not step_ok:
                            local_failed = True
                finally:
                    if not self._is_cancel_requested(job_id):
                        status = "failed" if local_failed else "done"
                        message = f"{_stage_display_label(current_stage)}完成" if not local_failed else f"{_stage_display_label(current_stage)}有错误"
                        self._set_script_status(job_id, script, status, message, current_stage)
                    self._clear_active_script(job_id, script)

            self._run_scripts_concurrently(job_id, scripts, process_stage_script, _stage_display_label(current_stage))

            error_count_after_stage = len(self.get(job_id).get("errors", []))
            if stage == "all" and error_count_after_stage > error_count_before_stage:
                remaining = [_stage_display_label(item) for item in stages[stages.index(current_stage) + 1 :]]
                if remaining:
                    self._log(
                        job_id,
                        "error",
                        f"{_stage_display_label(current_stage)}出现错误，已停止全流程，不再执行{'、'.join(remaining)}",
                    )
                break

        refreshed = scan_scripts(self.settings)
        self._update(
            job_id,
            result={
                "summary": summarize_catalog(self.settings, refreshed),
                "catalog": [script_to_dict(self.settings, script) for script in refreshed],
            },
        )

    def _run_direct_video_relay_pipeline(self, job_id: str, selected_scripts: Optional[set[Path]], scripts: List[ScriptFile], overwrite: bool) -> None:
        self._raise_if_cancelled(job_id)
        if selected_scripts is not None:
            scripts = [script for script in scripts if script.md_path.resolve() in selected_scripts]
            if not scripts:
                raise ValueError("没有匹配的已勾选脚本")

        self._init_script_statuses(job_id, scripts)
        self._update(job_id, total=sum(len(script.segments) * 2 for script in scripts))
        scope = "已勾选" if selected_scripts is not None else "全部"
        concurrency = self._script_concurrency(job_id, scripts)
        self._log(
            job_id,
            "info",
            f"扫描到 {len(scripts)} 个{scope}脚本，功能4快速模式按片段顺序执行：人物图 → 快速视频；脚本并发 {concurrency}",
        )

        def process_script(script: ScriptFile) -> None:
            self._raise_if_cancelled(job_id)
            local_failed = False
            self._set_script_status(job_id, script, "running", "功能4快速模式开始", "direct_videos")
            self._log(job_id, "info", f"功能4 快速模式 · 处理 {script.product_name} / {script.md_path.name}")
            try:
                for segment in script.segments:
                    self._raise_if_cancelled(job_id)
                    self._set_active_script(job_id, script, "characters", segment)
                    self._set_script_status(job_id, script, "running", f"功能1 · 片段{segment.index}", "characters", segment)
                    image_client, image_api, image_settings = self._image_client_for("characters")
                    character_ok = self._run_step(
                        job_id,
                        f"片段{segment.index} 人物图",
                        self._process_character,
                        job_id,
                        image_client,
                        script,
                        segment,
                        overwrite,
                        image_api,
                        image_settings,
                        script=script,
                        stage="characters",
                        segment=segment,
                    )

                    self._set_active_script(job_id, script, "direct_videos", segment)
                    self._set_script_status(job_id, script, "running", f"功能4 快速模式 · 片段{segment.index}", "direct_videos", segment)
                    if not character_ok:
                        local_failed = True
                        self._skip_step(job_id, f"片段{segment.index} 快速模式{self.settings.video_display_label}", "前置人物图未完成，跳过")
                        continue
                    if script.reference_image is None:
                        local_failed = True
                        self._error(job_id, f"片段{segment.index} 快速模式{self.settings.video_display_label}：{script.product_name} 缺少产品参考图，跳过")
                        self._increment(job_id, 1)
                        continue
                    video_client, video_api, video_settings = self._video_client_for()
                    video_ok = self._run_step(
                        job_id,
                        f"片段{segment.index} 快速模式{self.settings.video_display_label}",
                        self._process_direct_video,
                        job_id,
                        video_client,
                        script,
                        segment,
                        overwrite,
                        video_api,
                        video_settings,
                        script=script,
                        stage="direct_videos",
                        segment=segment,
                    )
                    if not video_ok:
                        local_failed = True
            finally:
                if not self._is_cancel_requested(job_id):
                    self._set_script_status(
                        job_id,
                        script,
                        "failed" if local_failed else "done",
                        "功能4快速模式有错误" if local_failed else "功能4快速模式完成",
                        "direct_videos",
                    )
                self._clear_active_script(job_id, script)

        self._run_scripts_concurrently(job_id, scripts, process_script, "功能4快速模式")

        refreshed = scan_scripts(self.settings)
        self._update(
            job_id,
            result={
                "summary": summarize_catalog(self.settings, refreshed),
                "catalog": [script_to_dict(self.settings, script) for script in refreshed],
            },
        )

    def _run_relay_pipeline(self, job_id: str, selected_scripts: Optional[set[Path]], scripts: List[ScriptFile], overwrite: bool) -> None:
        self._raise_if_cancelled(job_id)
        if selected_scripts is not None:
            scripts = [script for script in scripts if script.md_path.resolve() in selected_scripts]
            if not scripts:
                raise ValueError("没有匹配的已勾选脚本")

        self._init_script_statuses(job_id, scripts)
        self._update(job_id, total=sum(len(script.segments) * 3 for script in scripts))
        scope = "已勾选" if selected_scripts is not None else "全部"
        concurrency = self._script_concurrency(job_id, scripts)
        self._log(
            job_id,
            "info",
            f"扫描到 {len(scripts)} 个{scope}脚本，全流程按片段接力执行：人物图 → 故事版 → 视频；脚本并发 {concurrency}",
        )

        def process_script(script: ScriptFile) -> None:
            self._raise_if_cancelled(job_id)
            local_failed = False
            self._set_script_status(job_id, script, "running", "全流程开始", "all")
            self._log(job_id, "info", f"全流程 · 处理 {script.product_name} / {script.md_path.name}")
            missing_reference = script.reference_image is None
            try:
                for segment in script.segments:
                    self._raise_if_cancelled(job_id)
                    self._set_active_script(job_id, script, "characters", segment)
                    self._set_script_status(job_id, script, "running", f"功能1 · 片段{segment.index}", "characters", segment)
                    image_client, image_api, image_settings = self._image_client_for("characters")
                    character_ok = self._run_step(
                        job_id,
                        f"片段{segment.index} 人物图",
                        self._process_character,
                        job_id,
                        image_client,
                        script,
                        segment,
                        overwrite,
                        image_api,
                        image_settings,
                        script=script,
                        stage="characters",
                        segment=segment,
                    )

                    if not character_ok:
                        local_failed = True
                        self._set_active_script(job_id, script, "storyboards", segment)
                        self._set_script_status(job_id, script, "running", f"功能2 · 片段{segment.index}：前置人物图未完成", "storyboards", segment)
                        self._skip_step(job_id, f"片段{segment.index} 故事版图", "前置人物图未完成，跳过")
                        self._set_active_script(job_id, script, "videos", segment)
                        self._set_script_status(job_id, script, "running", f"功能3 · 片段{segment.index}：前置人物图未完成", "videos", segment)
                        self._skip_step(job_id, f"片段{segment.index} {self.settings.video_display_label}", "前置人物图未完成，跳过")
                        continue

                    if missing_reference:
                        local_failed = True
                        self._set_active_script(job_id, script, "storyboards", segment)
                        self._set_script_status(job_id, script, "running", f"功能2 · 片段{segment.index}：缺少产品参考图", "storyboards", segment)
                        self._error(job_id, f"片段{segment.index} 故事版图：{script.product_name} 缺少产品参考图，跳过")
                        self._increment(job_id, 1)
                        self._set_active_script(job_id, script, "videos", segment)
                        self._set_script_status(job_id, script, "running", f"功能3 · 片段{segment.index}：前置故事版未完成", "videos", segment)
                        self._skip_step(job_id, f"片段{segment.index} {self.settings.video_display_label}", "前置故事版未完成，跳过")
                        continue

                    self._set_active_script(job_id, script, "storyboards", segment)
                    self._set_script_status(job_id, script, "running", f"功能2 · 片段{segment.index}", "storyboards", segment)
                    image_client, image_api, image_settings = self._image_client_for("storyboards")
                    storyboard_ok = self._run_step(
                        job_id,
                        f"片段{segment.index} 故事版图",
                        self._process_storyboard,
                        job_id,
                        image_client,
                        script,
                        segment,
                        overwrite,
                        image_api,
                        image_settings,
                        script=script,
                        stage="storyboards",
                        segment=segment,
                    )

                    if not storyboard_ok:
                        local_failed = True
                        self._set_active_script(job_id, script, "videos", segment)
                        self._set_script_status(job_id, script, "running", f"功能3 · 片段{segment.index}：前置故事版未完成", "videos", segment)
                        self._skip_step(job_id, f"片段{segment.index} {self.settings.video_display_label}", "前置故事版未完成，跳过")
                        continue

                    self._set_active_script(job_id, script, "videos", segment)
                    self._set_script_status(job_id, script, "running", f"功能3 · 片段{segment.index}", "videos", segment)
                    video_client, video_api, video_settings = self._video_client_for()
                    video_ok = self._run_step(
                        job_id,
                        f"片段{segment.index} {self.settings.video_display_label}",
                        self._process_video,
                        job_id,
                        video_client,
                        script,
                        segment,
                        overwrite,
                        video_api,
                        video_settings,
                        script=script,
                        stage="videos",
                        segment=segment,
                    )
                    if not video_ok:
                        local_failed = True
            finally:
                if not self._is_cancel_requested(job_id):
                    self._set_script_status(job_id, script, "failed" if local_failed else "done", "全流程有错误" if local_failed else "全流程完成", "all")
                self._clear_active_script(job_id, script)

        self._run_scripts_concurrently(job_id, scripts, process_script, "全流程")

        refreshed = scan_scripts(self.settings)
        self._update(
            job_id,
            result={
                "summary": summarize_catalog(self.settings, refreshed),
                "catalog": [script_to_dict(self.settings, script) for script in refreshed],
            },
        )

    def _run_repair_pipeline(self, job_id: str, selected_scripts: Optional[set[Path]], scripts: List[ScriptFile]) -> None:
        self._raise_if_cancelled(job_id)
        if selected_scripts is not None:
            scripts = [script for script in scripts if script.md_path.resolve() in selected_scripts]
            if not scripts:
                raise ValueError("没有匹配的已勾选脚本")

        self._init_script_statuses(job_id, scripts)
        counts = self._repair_target_counts(scripts)
        total = sum(counts.values())
        self._update(job_id, total=total)
        scope = "已勾选" if selected_scripts is not None else "全部"
        concurrency = self._script_concurrency(job_id, scripts)
        self._log(
            job_id,
            "info",
            f"补漏扫描到 {len(scripts)} 个{scope}脚本：人物 {counts['characters']}，故事版 {counts['storyboards']}，视频 {counts['videos']}；脚本并发 {concurrency}",
        )
        if total == 0:
            self._log(job_id, "success", "没有发现缺漏资产")

        failures: Dict[str, bool] = {}
        touched: set[str] = set()
        progress_lock = threading.Lock()

        def mark_script_touched(script: ScriptFile) -> None:
            with progress_lock:
                touched.add(str(script.md_path))

        def mark_script_failed(script: ScriptFile) -> None:
            with progress_lock:
                failures[str(script.md_path)] = True

        def script_failed(script: ScriptFile) -> bool:
            with progress_lock:
                return bool(failures.get(str(script.md_path)))

        def needs_any(stage: str, script: ScriptFile) -> bool:
            return any(self._needs_repair(stage, script, segment) for segment in script.segments)

        def process_stage_script(stage: str, script: ScriptFile) -> None:
            stage_failed = False
            stage_touched = False
            stage_label = _stage_display_label(stage)
            self._set_script_status(job_id, script, "running", f"分层补漏{stage_label}检查中", stage)
            try:
                for segment in script.segments:
                    self._raise_if_cancelled(job_id)
                    if not self._needs_repair(stage, script, segment):
                        continue
                    stage_touched = True
                    mark_script_touched(script)

                    if stage == "characters":
                        self._set_active_script(job_id, script, "characters", segment)
                        self._set_script_status(job_id, script, "running", f"补漏功能1 · 片段{segment.index}", "characters", segment)
                        block_reason = self._repair_character_block_reason(script, segment)
                        if block_reason:
                            self._skip_step(job_id, f"片段{segment.index} 人物图", f"{block_reason}，本轮暂不补人物图")
                            continue
                        image_client, image_api, image_settings = self._image_client_for("characters")
                        step_ok = self._run_step(
                            job_id,
                            f"片段{segment.index} 人物图",
                            self._process_character,
                            job_id,
                            image_client,
                            script,
                            segment,
                            False,
                            image_api,
                            image_settings,
                            script=script,
                            stage=stage,
                            segment=segment,
                        )
                        if not step_ok:
                            stage_failed = True
                            mark_script_failed(script)
                        continue

                    if stage == "storyboards":
                        self._set_active_script(job_id, script, "storyboards", segment)
                        self._set_script_status(job_id, script, "running", f"补漏功能2 · 片段{segment.index}", "storyboards", segment)
                        if self._needs_repair("characters", script, segment):
                            self._skip_step(job_id, f"片段{segment.index} 故事版图", "前置人物图未完成，本轮暂不补故事版")
                        elif script.reference_image is None:
                            stage_failed = True
                            mark_script_failed(script)
                            self._error(job_id, f"片段{segment.index} 故事版图：{script.product_name} 缺少产品参考图，跳过")
                            self._increment(job_id, 1)
                        else:
                            image_client, image_api, image_settings = self._image_client_for("storyboards")
                            step_ok = self._run_step(
                                job_id,
                                f"片段{segment.index} 故事版图",
                                self._process_storyboard,
                                job_id,
                                image_client,
                                script,
                                segment,
                                False,
                                image_api,
                                image_settings,
                                script=script,
                                stage=stage,
                                segment=segment,
                            )
                            if not step_ok:
                                stage_failed = True
                                mark_script_failed(script)
                        continue

                    if stage == "videos":
                        self._set_active_script(job_id, script, "videos", segment)
                        self._set_script_status(job_id, script, "running", f"补漏功能3 · 片段{segment.index}", "videos", segment)
                        if script.reference_image is None:
                            stage_failed = True
                            mark_script_failed(script)
                            self._error(job_id, f"片段{segment.index} {self.settings.video_display_label}：{script.product_name} 缺少产品参考图，跳过")
                            self._increment(job_id, 1)
                        elif self._needs_repair("storyboards", script, segment):
                            self._skip_step(job_id, f"片段{segment.index} {self.settings.video_display_label}", "前置故事版未完成，本轮暂不补视频")
                        else:
                            video_client, video_api, video_settings = self._video_client_for()
                            video_ok = self._run_step(
                                job_id,
                                f"片段{segment.index} {self.settings.video_display_label}",
                                self._process_video,
                                job_id,
                                video_client,
                                script,
                                segment,
                                False,
                                video_api,
                                video_settings,
                                script=script,
                                stage=stage,
                                segment=segment,
                            )
                            if not video_ok:
                                stage_failed = True
                                mark_script_failed(script)
            finally:
                if not self._is_cancel_requested(job_id):
                    if stage_touched:
                        status = "failed" if script_failed(script) else "running"
                        message = f"分层补漏{stage_label}有错误" if stage_failed else f"分层补漏{stage_label}完成"
                        self._set_script_status(job_id, script, status, message, stage)
                self._clear_active_script(job_id, script)

        for stage in ["characters", "storyboards", "videos"]:
            self._raise_if_cancelled(job_id)
            stage_scripts = [script for script in scripts if needs_any(stage, script)]
            stage_total = sum(1 for script in scripts for segment in script.segments if self._needs_repair(stage, script, segment))
            stage_label = _stage_display_label(stage)
            if not stage_total:
                self._log(job_id, "success", f"分层补漏 · {stage_label}无缺漏")
                continue
            self._log(
                job_id,
                "info",
                f"分层补漏 · 开始{stage_label}：{len(stage_scripts)} 个脚本，{stage_total} 个片段",
            )
            self._run_scripts_concurrently(
                job_id,
                stage_scripts,
                lambda script, current_stage=stage: process_stage_script(current_stage, script),
                f"分层补漏{stage_label}",
            )

        with progress_lock:
            touched_paths = set(touched)
            failed_paths = set(path for path, failed in failures.items() if failed)
        for script in scripts:
            if self._is_cancel_requested(job_id):
                break
            script_key = str(script.md_path)
            if script_key in touched_paths:
                self._set_script_status(
                    job_id,
                    script,
                    "failed" if script_key in failed_paths else "done",
                    "补漏有错误" if script_key in failed_paths else "补漏完成",
                    "repair",
                )
            else:
                self._set_script_status(job_id, script, "done", "无缺漏", "repair")

        refreshed = scan_scripts(self.settings)
        self._update(
            job_id,
            result={
                "summary": summarize_catalog(self.settings, refreshed),
                "catalog": [script_to_dict(self.settings, script) for script in refreshed],
            },
        )

    def _repair_target_counts(self, scripts: List[ScriptFile]) -> Dict[str, int]:
        counts = {"characters": 0, "storyboards": 0, "videos": 0}
        for script in scripts:
            for segment in script.segments:
                for stage in counts:
                    if self._needs_repair(stage, script, segment):
                        counts[stage] += 1
        return counts

    def _needs_repair(self, stage: str, script: ScriptFile, segment: Segment) -> bool:
        if stage == "characters":
            _client, api, image_settings = self._image_client_for("characters")
            output = character_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
            return not _image_output_current_for_api(image_settings, output, api)
        if stage == "storyboards":
            _client, api, image_settings = self._image_client_for("storyboards")
            output = storyboard_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
            return not (
                has_current_storyboard_product_lock(output, script.product_name, script.reference_image)
                and _image_output_current_for_api(image_settings, output, api)
            )
        if stage == "videos":
            output = video_output_path(self.settings, script.product_name, script.md_path, segment.index)
            return not output.exists()
        return False

    def _repair_character_block_reason(self, script: ScriptFile, segment: Segment) -> str:
        if not segment.reuses_character:
            return ""
        try:
            source_index = character_source_segment_index(script.segments, segment)
        except ValueError as exc:
            return str(exc)
        if source_index == segment.index:
            return ""
        _client, api, image_settings = self._image_client_for("characters")
        source = character_image_path(script.md_path, source_index, self.settings.artifact_prefix)
        if _image_output_current_for_api(image_settings, source, api):
            return ""
        if source.exists():
            expected_aspect = _expected_image_aspect_for_api(image_settings, api)
            return f"复用源人物图比例不是 {expected_aspect}：片段{source_index}"
        return f"复用源人物图未完成：片段{source_index}"

    def _run_step(
        self,
        job_id: str,
        label: str,
        fn: Any,
        *args: Any,
        script: Optional[ScriptFile] = None,
        stage: str = "",
        segment: Optional[Segment] = None,
    ) -> bool:
        started = False
        try:
            self._raise_if_cancelled(job_id)
            started = True
            message = fn(*args)
            self._record_step_outcome(job_id, message)
            self._log(job_id, "success", f"{label}：{message}")
            return True
        except JobCancelled:
            raise
        except Exception as exc:
            reason = self._safe(str(exc))
            step_error = f"{label}：{reason}"
            if script is not None:
                self._append_script_error(job_id, script, stage, segment, step_error)
                self._error(job_id, f"{script.product_name} / {script.md_path.name} · {step_error}")
            else:
                self._error(job_id, step_error)
            return False
        finally:
            if started:
                self._increment(job_id, 1)

    def _skip_step(self, job_id: str, label: str, reason: str) -> None:
        self._record_step_outcome(job_id, "已存在，跳过")
        self._log(job_id, "info", f"{label}：{reason}")
        self._increment(job_id, 1)

    def _script_concurrency(self, job_id: str, scripts: List[ScriptFile]) -> int:
        if not scripts:
            return 1
        configured = self.get(job_id).get("script_concurrency")
        return max(1, min(_normalize_script_concurrency(configured, self.settings.script_concurrency), len(scripts)))

    def _run_scripts_concurrently(self, job_id: str, scripts: List[ScriptFile], worker: Any, label: str) -> None:
        if not scripts:
            return

        max_workers = min(20, len(scripts))
        pending = iter(scripts)
        pending_exhausted = False
        futures: Dict[Any, ScriptFile] = {}

        def submit_until_limit(executor: ThreadPoolExecutor) -> None:
            nonlocal pending_exhausted
            while not pending_exhausted and len(futures) < self._script_concurrency(job_id, scripts):
                self._raise_if_cancelled(job_id)
                try:
                    script = next(pending)
                except StopIteration:
                    pending_exhausted = True
                    return
                futures[executor.submit(worker, script)] = script

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            submit_until_limit(executor)
            while futures:
                self._raise_if_cancelled(job_id)
                done, _pending = wait(futures.keys(), timeout=1, return_when=FIRST_COMPLETED)
                if not done:
                    submit_until_limit(executor)
                    continue
                for future in done:
                    script = futures.pop(future)
                    try:
                        future.result()
                    except JobCancelled:
                        raise
                    except Exception as exc:
                        self._set_script_status(job_id, script, "failed", self._safe(str(exc)))
                        self._error(job_id, f"{label} · {script.product_name} / {script.md_path.name}：{self._safe(str(exc))}")
                submit_until_limit(executor)

    def _init_script_statuses(self, job_id: str, scripts: List[ScriptFile]) -> None:
        now = time.time()
        statuses = {
            str(script.md_path): {
                "product_name": script.product_name,
                "md_name": script.md_path.name,
                "md_path": str(script.md_path),
                "status": "pending",
                "stage": "",
                "segment_index": None,
                "segment_label": "",
                "message": "等待执行",
                "errors": [],
                "updated_at": now,
            }
            for script in scripts
        }
        self._update(job_id, script_statuses=statuses)

    def _set_script_status(
        self,
        job_id: str,
        script: ScriptFile,
        status: str,
        message: str,
        stage: str = "",
        segment: Optional[Segment] = None,
    ) -> None:
        safe_message = self._safe(message)
        with self._lock:
            previous = self._jobs[job_id].setdefault("script_statuses", {}).get(str(script.md_path), {})
            errors = list(previous.get("errors") or [])
            if status == "failed" and errors and ("有错误" in safe_message or safe_message in {"补漏有错误", "全流程有错误"}):
                safe_message = errors[-1]
        payload = {
            "product_name": script.product_name,
            "md_name": script.md_path.name,
            "md_path": str(script.md_path),
            "status": status,
            "stage": stage,
            "segment_index": segment.index if segment else None,
            "segment_label": f"片段{segment.index}" if segment else "",
            "message": safe_message,
            "errors": errors,
            "updated_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id].setdefault("script_statuses", {})[str(script.md_path)] = payload

    def _append_script_error(
        self,
        job_id: str,
        script: ScriptFile,
        stage: str,
        segment: Optional[Segment],
        message: str,
    ) -> None:
        safe_message = self._safe(message)
        now = time.time()
        with self._lock:
            statuses = self._jobs[job_id].setdefault("script_statuses", {})
            payload = statuses.setdefault(
                str(script.md_path),
                {
                    "product_name": script.product_name,
                    "md_name": script.md_path.name,
                    "md_path": str(script.md_path),
                    "status": "failed",
                    "stage": stage,
                    "segment_index": segment.index if segment else None,
                    "segment_label": f"片段{segment.index}" if segment else "",
                    "message": safe_message,
                    "errors": [],
                    "updated_at": now,
                },
            )
            errors = list(payload.get("errors") or [])
            errors.append(safe_message)
            payload.update(
                {
                    "status": "failed",
                    "stage": stage,
                    "segment_index": segment.index if segment else None,
                    "segment_label": f"片段{segment.index}" if segment else "",
                    "message": safe_message,
                    "errors": errors[-10:],
                    "updated_at": now,
                }
            )

    def _mark_incomplete_script_statuses(self, job_id: str, status: str, message: str) -> None:
        now = time.time()
        safe_message = self._safe(message)
        with self._lock:
            for payload in self._jobs[job_id].setdefault("script_statuses", {}).values():
                if payload.get("status") in {"done", "failed", "canceled"}:
                    continue
                payload["status"] = status
                payload["message"] = safe_message
                payload["updated_at"] = now

    def _set_active_script(self, job_id: str, script: ScriptFile, stage: str, segment: Optional[Segment]) -> None:
        payload = {
            "product_name": script.product_name,
            "md_name": script.md_path.name,
            "md_path": str(script.md_path),
            "stage": stage,
            "segment_index": segment.index if segment else None,
            "segment_label": f"片段{segment.index}" if segment else "",
            "updated_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id].setdefault("active_scripts", {})[str(script.md_path)] = payload

    def _clear_active_script(self, job_id: str, script: ScriptFile) -> None:
        with self._lock:
            self._jobs[job_id].setdefault("active_scripts", {}).pop(str(script.md_path), None)

    def _process_character(
        self,
        job_id: str,
        image_client: Image2Client,
        script: ScriptFile,
        segment: Segment,
        overwrite: bool,
        image_api: Optional[str] = None,
        image_settings: Optional[Settings] = None,
    ) -> str:
        image_settings = image_settings or self.settings
        image_api = image_api or ("grok" if self.settings.provider == "grok" else "otu")
        output = character_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
        if output.exists() and not overwrite:
            if _image_output_current_for_api(image_settings, output, image_api):
                return "已存在，跳过"
            expected_aspect = _expected_image_aspect_for_api(image_settings, image_api)
            self._log(job_id, "info", f"片段{segment.index} 人物图：旧图比例不是 {expected_aspect}，自动重做")

        if segment.reuses_character:
            source_index = character_source_segment_index(script.segments, segment)
            source = character_image_path(script.md_path, source_index, self.settings.artifact_prefix)
            if not _image_output_current_for_api(image_settings, source, image_api):
                expected_aspect = _expected_image_aspect_for_api(image_settings, image_api)
                if source.exists():
                    raise RuntimeError(f"复用源人物图比例不是 {expected_aspect}：片段{source_index}，请先重新运行源片段")
                raise RuntimeError(f"复用源人物图不存在：片段{source_index}")
            ensure_parent(output)
            if source.resolve() != output.resolve():
                shutil.copy2(source, output)
            return f"复用片段{source_index}人物图"

        self._validate_generated_image_or_retry(
            job_id,
            lambda: image_client.generate_from_prompt(
                _image_prompt_with_aspect_guard(segment.character_prompt, _expected_image_aspect_for_api(image_settings, image_api)),
                output,
                progress=lambda message: self._log(job_id, "info", f"片段{segment.index} {self.settings.character_display_label}：{message}"),
            ),
            output,
            image_settings,
            image_api,
            f"片段{segment.index} 人物图",
        )
        return "已生成"

    def _process_storyboard(
        self,
        job_id: str,
        image_client: Image2Client,
        script: ScriptFile,
        segment: Segment,
        overwrite: bool,
        image_api: Optional[str] = None,
        image_settings: Optional[Settings] = None,
    ) -> str:
        image_settings = image_settings or self.settings
        image_api = image_api or ("grok" if self.settings.provider == "grok" else "otu")
        output = storyboard_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
        has_product_lock = has_current_storyboard_product_lock(output, script.product_name, script.reference_image)
        has_valid_aspect = _image_output_current_for_api(image_settings, output, image_api)
        if output.exists() and has_product_lock and has_valid_aspect and not overwrite:
            return "已存在，跳过"
        if output.exists() and has_product_lock and not has_valid_aspect and not overwrite:
            expected_aspect = _expected_image_aspect_for_api(image_settings, image_api)
            self._log(job_id, "info", f"片段{segment.index} 故事版图：旧图比例不是 {expected_aspect}，自动重做")
        if output.exists() and not has_product_lock:
            self._log(job_id, "info", f"片段{segment.index} 故事版图：旧故事版缺少当前产品锁，自动重做")

        character_path = character_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
        _character_client, character_api, character_settings = self._image_client_for("characters")
        if not _image_output_current_for_api(character_settings, character_path, character_api):
            if character_path.exists():
                raise RuntimeError(_stale_image_message(character_settings, character_api, character_path, "当前片段人物图", "功能1"))
            raise RuntimeError("缺少当前片段人物图")

        assert script.reference_image is not None
        storyboard_aspect_ratio = _expected_image_aspect_for_api(image_settings, image_api)
        storyboard_size = "" if image_api == "grok" else image_settings.image_size
        locked_prompt = build_storyboard_product_lock_prompt(
            script.product_name,
            segment.storyboard_prompt,
            storyboard_size,
            storyboard_aspect_ratio,
        )
        self._log(job_id, "info", f"片段{segment.index} 故事版图：产品视觉参考图 1 张 + 人物图 1 张")
        self._validate_generated_image_or_retry(
            job_id,
            lambda: image_client.generate_with_references(
                _image_prompt_with_aspect_guard(locked_prompt, storyboard_aspect_ratio),
                [script.reference_image, character_path],
                output,
                progress=lambda message: self._log(job_id, "info", f"片段{segment.index} {self.settings.storyboard_display_label}：{message}"),
            ),
            output,
            image_settings,
            image_api,
            f"片段{segment.index} 故事版图",
        )
        write_storyboard_product_lock_meta(output, script.product_name, script.reference_image, 1)
        return "已生成"

    def _validate_generated_image_or_retry(
        self,
        job_id: str,
        generate_once: Callable[[], Any],
        output: Path,
        image_settings: Settings,
        image_api: str,
        label: str,
    ) -> None:
        attempts = _image_validation_attempts(image_settings, image_api)
        last_message = ""
        for attempt in range(1, attempts + 1):
            if output.exists():
                output.unlink()
            generate_once()
            if _generated_image_current_for_api(image_settings, output, image_api):
                return
            last_message = _stale_image_message(image_settings, image_api, output, label, "当前功能")
            if output.exists():
                output.unlink()
            if attempt >= attempts:
                break
            delay = _image_validation_retry_delay(image_settings, image_api, attempt)
            self._log(job_id, "warning", f"{label}：API返回图片不符合要求，已删除并重试 {attempt + 1}/{attempts}；{last_message}")
            if delay > 0:
                time.sleep(delay)
        raise RuntimeError(f"{label}：API平台返回图片不符合要求，已重试 {attempts} 次仍失败；{last_message}")

    def _process_video(
        self,
        job_id: str,
        omni_client: Any,
        script: ScriptFile,
        segment: Segment,
        overwrite: bool,
        video_api: Optional[str] = None,
        video_settings: Optional[Settings] = None,
    ) -> str:
        video_settings = video_settings or self.settings
        video_api = video_api or ("grok" if self.settings.provider == "grok" else "otu")
        output = video_output_path(self.settings, script.product_name, script.md_path, segment.index)
        output_matches_reference = len(getattr(script, "reference_images", (script.reference_image,))) <= 1 or has_current_storyboard_product_lock(
            output, script.product_name, script.reference_image
        )
        if output.exists() and output_matches_reference and not overwrite:
            return "已存在，跳过"
        if output.exists() and not output_matches_reference and not overwrite:
            self._log(job_id, "info", f"片段{segment.index} {self.settings.video_display_label}：产品 SKU 已切换，自动重做")
        if output.exists() and overwrite:
            self._log(job_id, "info", f"片段{segment.index} {self.settings.video_display_label}：强制重跑，旧视频会保留到新视频成功覆盖")

        storyboard_path = storyboard_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
        if not has_current_storyboard_product_lock(storyboard_path, script.product_name, script.reference_image):
            raise RuntimeError("缺少通过产品锁生成的当前片段故事版图，请先重新运行功能2")
        _storyboard_client, storyboard_api, storyboard_settings = self._image_client_for("storyboards")
        if not _image_output_current_for_api(storyboard_settings, storyboard_path, storyboard_api):
            raise RuntimeError(_stale_image_message(storyboard_settings, storyboard_api, storyboard_path, "当前片段故事版图", "功能2"))

        video_prompt = build_video_prompt(segment)
        self._log(
            job_id,
            "info",
            f"片段{segment.index} {self.settings.video_display_label}：使用故事版图 + 当前片段完整脚本，prompt {len(video_prompt)} 字符",
        )
        if video_api == "grok":
            character_path = character_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
            extra_references = [path for path in [script.reference_image, character_path] if path is not None and path.exists()]
            omni_client.generate_video(
                video_prompt,
                storyboard_path,
                output,
                progress=lambda message: self._log(job_id, "info", f"片段{segment.index} {self.settings.video_display_label}：{message}"),
                duration=_segment_duration_seconds(segment, video_settings.grok_video_duration),
                reference_paths=extra_references,
            )
        else:
            omni_client.generate_video(
                video_prompt,
                storyboard_path,
                output,
                progress=lambda message: self._log(job_id, "info", f"片段{segment.index} {self.settings.video_display_label}：{message}"),
            )
        assert script.reference_image is not None
        write_storyboard_product_lock_meta(output, script.product_name, script.reference_image, 1)
        return "已生成"

    def _process_direct_video(
        self,
        job_id: str,
        omni_client: Any,
        script: ScriptFile,
        segment: Segment,
        overwrite: bool,
        video_api: Optional[str] = None,
        video_settings: Optional[Settings] = None,
    ) -> str:
        video_settings = video_settings or self.settings
        video_api = video_api or ("grok" if self.settings.provider == "grok" else "otu")

        output = video_output_path(self.settings, script.product_name, script.md_path, segment.index)
        output_matches_reference = len(getattr(script, "reference_images", (script.reference_image,))) <= 1 or has_current_storyboard_product_lock(
            output, script.product_name, script.reference_image
        )
        if output.exists() and output_matches_reference and not overwrite:
            return "已存在，跳过"
        if output.exists() and not output_matches_reference and not overwrite:
            self._log(job_id, "info", f"片段{segment.index} 快速模式{self.settings.video_display_label}：产品 SKU 已切换，自动重做")
        if output.exists() and overwrite:
            self._log(job_id, "info", f"片段{segment.index} 快速模式{self.settings.video_display_label}：强制重跑，旧视频会保留到新视频成功覆盖")

        character_path = character_image_path(script.md_path, segment.index, self.settings.artifact_prefix)
        _character_client, character_api, character_settings = self._image_client_for("characters")
        if not _image_output_current_for_api(character_settings, character_path, character_api):
            if character_path.exists():
                raise RuntimeError(_stale_image_message(character_settings, character_api, character_path, "当前片段人物图", "功能1"))
            raise RuntimeError("缺少当前片段人物图，请先运行功能1")
        if script.reference_image is None or not script.reference_image.exists():
            raise RuntimeError("缺少产品参考图，无法生成快速模式视频")

        video_prompt = build_direct_video_prompt(segment)
        self._log(
            job_id,
            "info",
            f"片段{segment.index} 快速模式{self.settings.video_display_label}：使用人物图 + 产品参考图 + 当前片段完整脚本，prompt {len(video_prompt)} 字符",
        )
        if video_api == "grok":
            omni_client.generate_video(
                video_prompt,
                character_path,
                output,
                progress=lambda message: self._log(job_id, "info", f"片段{segment.index} 快速模式{self.settings.video_display_label}：{message}"),
                duration=_segment_duration_seconds(segment, video_settings.grok_video_duration),
                reference_paths=[script.reference_image],
            )
        else:
            omni_client.generate_video(
                video_prompt,
                character_path,
                output,
                progress=lambda message: self._log(job_id, "info", f"片段{segment.index} 快速模式{self.settings.video_display_label}：{message}"),
                reference_paths=[script.reference_image],
            )
        write_storyboard_product_lock_meta(output, script.product_name, script.reference_image, 1)
        return "已生成"

    def _image_client_for(self, stage: str) -> tuple[Any, str, Settings]:
        api, model = _split_api_model(_stage_api_model(self.settings, stage))
        if stage == "characters":
            image_size = self.settings.character_image_size or self.settings.image_size
            aspect_ratio = self.settings.character_image_aspect_ratio or self.settings.grok_image_aspect_ratio
            resolution = self.settings.character_image_resolution or self.settings.grok_image_resolution
        else:
            image_size = self.settings.storyboard_image_size or self.settings.image_size
            aspect_ratio = self.settings.storyboard_image_aspect_ratio or self.settings.grok_image_aspect_ratio
            resolution = self.settings.storyboard_image_resolution or self.settings.grok_image_resolution
        if api == "grok":
            runtime_settings = replace(
                self.settings,
                grok_image_aspect_ratio=aspect_ratio,
                grok_image_resolution=resolution,
            )
            return GrokClient(runtime_settings), "grok", runtime_settings
        runtime_settings = replace(self.settings, image_model=model, image_fallback_models=[], image_size=image_size)
        return Image2Client(runtime_settings), "otu", runtime_settings

    def _video_client_for(self) -> tuple[Any, str, Settings]:
        api, model = _split_api_model(_stage_api_model(self.settings, "videos"))
        if api == "grok":
            runtime_settings = replace(
                self.settings,
                grok_video_aspect_ratio=self.settings.function_video_aspect_ratio or self.settings.grok_video_aspect_ratio,
                grok_video_resolution=self.settings.function_video_resolution or self.settings.grok_video_resolution,
                grok_video_duration=_safe_int(self.settings.function_video_duration, self.settings.grok_video_duration),
            )
            if _is_skyreels_video_model(model):
                return RunningHubSkyReelsClient(runtime_settings), "grok", runtime_settings
            return GrokClient(runtime_settings), "grok", runtime_settings
        video_size = self.settings.function_video_size or self.settings.video_size
        runtime_settings = replace(self.settings, omni_model=model, video_size=video_size, function_video_duration=10)
        return OmniClient(runtime_settings), "otu", runtime_settings

    def _increment(self, job_id: str, amount: int) -> None:
        with self._lock:
            self._jobs[job_id]["done"] += amount

    def _record_step_outcome(self, job_id: str, message: str) -> None:
        with self._lock:
            stats = self._jobs[job_id].setdefault("stats", {"generated": 0, "skipped": 0})
            if "已存在，跳过" in message:
                stats["skipped"] = stats.get("skipped", 0) + 1
            elif "已生成" in message or message.startswith("复用"):
                stats["generated"] = stats.get("generated", 0) + 1

    def _log(self, job_id: str, level: str, message: str) -> None:
        entry = {"ts": time.time(), "level": level, "message": self._safe(message)}
        with self._lock:
            logs = self._jobs[job_id]["logs"]
            logs.append(entry)
            if len(logs) > 500:
                del logs[:-500]

    def _error(self, job_id: str, message: str) -> None:
        safe = self._safe(message)
        self._log(job_id, "error", safe)
        with self._lock:
            self._jobs[job_id]["errors"].append(safe)

    def _update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(kwargs)

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.get("cancel_requested"))

    def _raise_if_cancelled(self, job_id: str) -> None:
        if self._is_cancel_requested(job_id):
            raise JobCancelled()

    def _safe(self, text: str) -> str:
        return mask_secrets(text, self.settings.secret_values())

    def _snapshot(self, job: Dict[str, Any]) -> Dict[str, Any]:
        payload = json.loads(json.dumps(job, ensure_ascii=False, default=str))
        if job.get("status") == "queued":
            target_index = self._job_order.index(job["id"])
            payload["queued_ahead"] = sum(
                1
                for candidate_id in self._job_order[:target_index]
                if self._jobs[candidate_id].get("status") in {"queued", "running"}
            )
        elif job.get("status") == "running":
            payload["queued_ahead"] = 0
        return payload


def _expand_stages(stage: str) -> List[str]:
    if stage == "all":
        return ["characters", "storyboards", "videos"]
    if stage == "direct_videos":
        return ["characters", "direct_videos"]
    if stage in VALID_STAGES:
        return [stage]
    raise ValueError(f"未知任务阶段：{stage}")


def _stage_display_label(stage: str) -> str:
    return {
        "smart": "功能5 完整模式",
        "characters": "功能1",
        "storyboards": "功能2",
        "videos": "功能3",
        "direct_videos": "功能4 快速模式",
    }.get(stage, stage)


def _normalize_script_paths(script_paths: Optional[List[str]]) -> Optional[set[Path]]:
    if script_paths is None:
        return None
    return {Path(path).expanduser().resolve() for path in script_paths if path}


def _normalize_reference_images(reference_images: Optional[Dict[str, str]]) -> Dict[str, Path]:
    return {
        str(product_name): Path(path).expanduser().resolve()
        for product_name, path in (reference_images or {}).items()
        if product_name and path
    }


def _bind_script_references(
    scripts: List[ScriptFile],
    selected_references: Dict[str, Path],
    *,
    require_selection: bool,
) -> List[ScriptFile]:
    bound: List[ScriptFile] = []
    for script in scripts:
        raw_options = getattr(script, "reference_images", ())
        if not raw_options and getattr(script, "reference_image", None) is not None:
            raw_options = (script.reference_image,)
        options = tuple(path.resolve() for path in raw_options)
        selected = selected_references.get(script.product_name)
        if selected is not None and selected not in options:
            raise ValueError(f"{script.product_name} 选择的产品参考图不属于该产品")
        if selected is None and len(options) == 1:
            selected = options[0]
        if require_selection and not options:
            raise ValueError(f"{script.product_name} 缺少产品参考图")
        if require_selection and len(options) > 1 and selected is None:
            raise ValueError(f"{script.product_name} 有 {len(options)} 张产品参考图，请先选择本次使用的 SKU")
        if hasattr(script, "__dataclass_fields__"):
            bound.append(replace(script, reference_image=selected))
        else:
            script.reference_image = selected
            bound.append(script)
    return bound


def _normalize_script_concurrency(value: Optional[int], fallback: int) -> int:
    try:
        parsed = int(value if value is not None else fallback)
    except Exception:
        parsed = fallback
    return max(1, min(20, parsed))


def _stage_api_model(settings: Settings, stage: str) -> str:
    value = {
        "characters": settings.character_api_model,
        "storyboards": settings.storyboard_api_model,
        "videos": settings.video_api_model,
    }.get(stage, "")
    if value:
        return value
    if stage in {"characters", "storyboards"}:
        return "grok:G-2.0" if settings.provider == "grok" else f"otu:{settings.image_model}"
    if settings.provider == "grok":
        return "grok:X v1.5"
    return f"otu:{settings.omni_model}"


def _is_skyreels_video_model(model: str) -> bool:
    return "skyreels" in model.lower()


def _split_api_model(value: str) -> tuple[str, str]:
    if ":" not in value:
        return "otu", value
    api, model = value.split(":", 1)
    return api.strip() or "otu", model.strip()


def _image_prompt_with_aspect_guard(prompt: str, aspect_ratio: str) -> str:
    if not aspect_ratio:
        return prompt
    guard = (
        "【最高优先级：输出比例硬约束】\n"
        f"最终图片必须严格为 {aspect_ratio} 画面比例。"
        "不得输出横图、方图、拼接边框外扩图或任何与该比例不一致的画布；"
        "主体构图必须适配这个画幅，不要先生成其他比例再留白填充。\n"
    )
    if "输出比例硬约束" in prompt:
        return prompt
    return f"{guard}\n{prompt}"


def _image_validation_attempts(settings: Settings, api: str) -> int:
    if api == "grok":
        return max(1, settings.grok_retry_attempts)
    return max(1, settings.image_retry_attempts)


def _image_validation_retry_delay(settings: Settings, api: str, attempt: int) -> float:
    if api == "grok":
        return max(0.0, settings.grok_retry_base_seconds * attempt)
    return max(0.0, settings.image_retry_base_seconds * attempt)


def _generated_image_current_for_api(settings: Settings, path: Path, api: str) -> bool:
    if not path.exists():
        return False
    expected_aspect = _expected_image_aspect_for_api(settings, api)
    if not expected_aspect:
        return _is_readable_image(path)
    return image_matches_aspect(path, expected_aspect)


def _image_output_current_for_api(settings: Settings, path: Path, api: str) -> bool:
    if not path.exists():
        return False
    expected_aspect = _expected_image_aspect_for_api(settings, api)
    if not expected_aspect:
        return True
    if api != "grok" and not _is_readable_image(path):
        return True
    return image_matches_aspect(path, expected_aspect)


def _is_readable_image(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def _expected_image_aspect_for_api(settings: Settings, api: str) -> str:
    if api == "grok":
        return settings.grok_image_aspect_ratio or "9:16"
    return _aspect_from_size(settings.image_size) or "4:3"


def _stale_image_message(settings: Settings, api: str, path: Path, label: str, rerun_stage: str) -> str:
    expected_aspect = _expected_image_aspect_for_api(settings, api)
    actual = _image_aspect_description(path)
    if actual:
        return f"{label}已存在但比例不符合要求：{actual}，需要 {expected_aspect}，请重新运行{rerun_stage}"
    return f"{label}已存在但无法读取或格式不正确，需要 {expected_aspect}，请重新运行{rerun_stage}"


def _image_aspect_description(path: Path) -> str:
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
    except Exception:
        return ""
    if width <= 0 or height <= 0:
        return ""

    def gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a or 1

    divisor = gcd(width, height)
    return f"{width}x{height}（{width // divisor}:{height // divisor}）"


def _aspect_from_size(size: str) -> str:
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


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _segment_duration_seconds(segment: Segment, fallback: int) -> int:
    matches = re.findall(r"(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?", segment.time_range or "")
    if len(matches) < 2:
        return max(6, min(30, fallback))

    def to_seconds(match: tuple[str, str, str]) -> float:
        minutes, seconds, millis = match
        return int(minutes) * 60 + int(seconds) + (int(millis.ljust(3, "0")) / 1000 if millis else 0)

    duration = round(max(0.0, to_seconds(matches[1]) - to_seconds(matches[0])))
    return max(6, min(30, duration or fallback))
