from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .store import TaskStore


RESULT_PREFIX = "OPC_PIPELINE_RESULT="
TERMINAL_STATUSES = {"completed", "failed", "needs_review", "canceled", "publish_ready"}


class PipelineRunner:
    def __init__(self, store: TaskStore, workspace_root: Path) -> None:
        self.store = store
        self.workspace_root = workspace_root
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="auto-publish-pipeline", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def wake(self) -> None:
        self._wake.set()

    def request_publish(self, task_id: str, start_mode: str, scheduled_at: float = 0) -> dict[str, Any]:
        task = self.store.get(task_id)
        if task["status"] != "publish_ready":
            raise ValueError("任务当前不在等待发布状态")
        if start_mode not in {"immediate", "scheduled"}:
            raise ValueError("请选择立即开始或定时开始")
        if start_mode == "scheduled" and scheduled_at <= time.time():
            raise ValueError("首次发布时间必须晚于当前时间")
        artifacts = task["artifacts"]
        artifacts["publish_request"] = {"start_mode": start_mode, "scheduled_at": scheduled_at}
        result = self.store.update(task_id, status="queued", stage="publish_ready", artifacts=artifacts, error="")
        self.wake()
        return result

    def retry(self, task_id: str) -> dict[str, Any]:
        task = self.store.get(task_id)
        if task["status"] != "failed":
            raise ValueError("只有失败任务可以从断点继续")
        result = self.store.update(task_id, status="queued", error="")
        self.wake()
        return result

    def resolve_publish_review(self, task_id: str, published: bool) -> dict[str, Any]:
        task = self.store.get(task_id)
        if task["status"] != "needs_review":
            raise ValueError("任务当前不需要发布确认")
        artifacts = task["artifacts"]
        index = artifacts.get("active_publish_index")
        if index is None:
            raise ValueError("找不到需要确认的发布序号")
        statuses = artifacts.setdefault("publish_statuses", {})
        statuses[str(index)] = "done" if published else "pending"
        artifacts["active_publish_index"] = None
        result = self.store.update(task_id, status="queued", stage="publishing", artifacts=artifacts, error="")
        self.wake()
        return result

    def _loop(self) -> None:
        while not self._stop.is_set():
            runnable = next((task for task in reversed(self.store.list()) if task["status"] == "queued"), None)
            if not runnable:
                self._wake.wait(2)
                self._wake.clear()
                continue
            try:
                self._run(runnable["id"])
            except Exception as exc:
                self.store.append_log(runnable["id"], f"失败：{exc}")
                self.store.update(runnable["id"], status="failed", error=str(exc))

    def _run(self, task_id: str) -> None:
        task = self.store.update(task_id, status="running", error="")
        spec = task["spec"]
        artifacts = task["artifacts"]
        lock_path = self._acquire_lock(task_id, spec["clone_path"])
        try:
            minimum_new = max(0, spec["publish_count"] - len(spec["existing_videos"]))
            if "variants" not in artifacts:
                self.store.update(task_id, stage="mutating")
                artifacts["variants"] = self._mutate(task_id, spec) if spec["generation_count"] else []
                if len(artifacts["variants"]) < minimum_new:
                    raise RuntimeError("可用裂变脚本不足以满足发布配额")
                self.store.update(task_id, artifacts=artifacts)
            if "adapted_scripts" not in artifacts:
                self.store.update(task_id, stage="adapting")
                artifacts["adapted_scripts"] = self._adapt(task_id, spec, artifacts["variants"])
                if len(artifacts["adapted_scripts"]) < minimum_new:
                    raise RuntimeError("成功适配的脚本不足以满足发布配额")
                self.store.update(task_id, artifacts=artifacts)
            if "export_dirs" not in artifacts:
                self.store.update(task_id, stage="generating")
                if artifacts["adapted_scripts"]:
                    result = self._generate(task_id, spec, artifacts["adapted_scripts"], minimum_new)
                    artifacts["generation"] = result.get("job") or {}
                    artifacts["export_dirs"] = [item["export_dir"] for item in result.get("export", {}).get("exported") or []]
                else:
                    artifacts["generation"] = {}
                    artifacts["export_dirs"] = []
                if len(artifacts["export_dirs"]) < minimum_new:
                    raise RuntimeError("成功产出的片段不足以满足发布配额")
                self.store.update(task_id, artifacts=artifacts)
            if "generated_videos" not in artifacts:
                self.store.update(task_id, stage="assembling")
                artifacts["generated_videos"] = self._assemble(task_id, spec, artifacts["export_dirs"])
                candidates = [*spec["existing_videos"], *artifacts["generated_videos"]]
                if len(candidates) < spec["publish_count"]:
                    raise RuntimeError(f"成功成片只有{len(candidates)}条，不足发布配额{spec['publish_count']}条")
                artifacts["candidate_videos"] = candidates
                artifacts["publish_videos"] = candidates[: spec["publish_count"]]
                artifacts["reserve_videos"] = candidates[spec["publish_count"] :]
                self.store.update(task_id, artifacts=artifacts)

            request = artifacts.get("publish_request") or (
                {"start_mode": spec["start_mode"], "scheduled_at": spec["scheduled_at"]}
                if spec["auto_publish"] else None
            )
            if not request:
                self.store.update(task_id, status="publish_ready", stage="publish_ready", artifacts=artifacts)
                return
            scheduled_at = float(request.get("scheduled_at") or 0)
            if request.get("start_mode") == "scheduled" and scheduled_at > time.time():
                self.store.update(task_id, status="queued", stage="scheduled", artifacts=artifacts)
                self._wake.wait(min(5, max(0.2, scheduled_at - time.time())))
                self._wake.clear()
                return
            self.store.update(task_id, stage="publishing", artifacts=artifacts)
            self._publish(task_id, spec, artifacts)
            self.store.update(task_id, status="completed", stage="completed", artifacts=artifacts, error="")
        finally:
            lock_path.unlink(missing_ok=True)

    def _component_python(self, component: str) -> str:
        candidate = self.workspace_root / component / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if candidate.is_file():
            return str(candidate)
        return sys.executable

    def _command(self, task_id: str, command: list[str], cwd: Path) -> tuple[str, dict[str, Any] | None]:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output = completed.stdout or ""
        for line in output.splitlines()[-30:]:
            self.store.append_log(task_id, line)
        result = None
        for line in reversed(output.splitlines()):
            if line.startswith(RESULT_PREFIX):
                result = json.loads(line[len(RESULT_PREFIX) :])
                break
        if completed.returncode:
            error = str((result or {}).get("error") or output.strip().splitlines()[-1] if output.strip() else "阶段执行失败")
            raise RuntimeError(error)
        return output, result

    def _mutate(self, task_id: str, spec: dict[str, Any]) -> list[str]:
        root = self.workspace_root / "Script-Generation"
        output_dir = Path(spec["clone_path"]).parent
        before = {path.resolve() for path in output_dir.glob("裂变-*.md")}
        command = [
            self._component_python("Script-Generation"), "-m",
            "opc_engine.features.script_generation.generate_product_script",
            "--enable-mutation", "--mutation-source", spec["clone_path"],
            "--product-name", spec["product_name"], "--output-dir", str(output_dir),
            "--mutation-variants", str(spec["variant_count"]),
            "--country", spec["country"], "--target-language", spec["target_language"],
        ]
        self._command(task_id, command, root)
        created = sorted(str(path) for path in ({path.resolve() for path in output_dir.glob("裂变-*.md")} - before))
        if len(created) > spec["generation_count"]:
            created = created[: spec["generation_count"]]
        return created

    def _adapt(self, task_id: str, spec: dict[str, Any], variants: list[str]) -> list[str]:
        component = "Script-Adaptation"
        root = self.workspace_root / component / "software" / "Script-Adaptation-app"
        model_root_name = "SCRIPT_ROOT" if spec["video_model"] == "omni" else "GROK_SCRIPT_ROOT"
        default = Path(os.path.expandvars(os.environ["OPC_VAULT_ROOT"])) / "wiki" / "视频" / "纯AI视频" / "04适配脚本" / spec["video_model"]
        model_root = Path(os.path.expandvars(os.environ.get(model_root_name, str(default)))).expanduser()
        outputs = []
        for index, variant in enumerate(variants, start=1):
            stem = f"10005-{task_id}-{index:03d}"
            command = [
                self._component_python(component), "-m",
                "opc_engine.features.script_adaptation.script_adaptation_agent",
                "--stage", "adapt", "--execute", "--script-file", variant,
                "--target-model", spec["video_model"], "--output-stem", stem,
            ]
            try:
                self._command(task_id, command, root)
                matches = list(model_root.rglob(stem + ".md"))
                if len(matches) != 1:
                    raise RuntimeError(f"未找到唯一的适配脚本输出：{stem}.md")
                outputs.append(str(matches[0].resolve()))
            except Exception as exc:
                self.store.append_log(task_id, f"适配候选{index}失败，继续处理备用候选：{exc}")
        return outputs

    def _generate(self, task_id: str, spec: dict[str, Any], scripts: list[str], minimum_success: int) -> dict[str, Any]:
        root = self.workspace_root / "Video-Generation"
        command = [
            self._component_python("Video-Generation"), "-m", "agent.pipeline_cli",
            "--provider", spec["video_model"], "--reference-image", spec["reference_image"],
            "--concurrency", str(spec["concurrency"]),
            "--minimum-success", str(minimum_success),
        ]
        for script in scripts:
            command.extend(["--script", script])
        _output, result = self._command(task_id, command, root)
        if not result:
            raise RuntimeError("片段产出没有返回结构化结果")
        return result

    def _assemble(self, task_id: str, spec: dict[str, Any], export_dirs: list[str]) -> list[str]:
        root = self.workspace_root / "Video-Assembly-hd"
        outputs = []
        for script_dir in export_dirs:
            command = [
                self._component_python("Video-Assembly-hd"), str(root / "app" / "video_assembly.py"),
                "assemble", "--script-dir", script_dir, "--caption-mode", spec["caption_mode"],
            ]
            try:
                output, _result = self._command(task_id, command, root)
                matches = re.findall(r"^\s*output:\s+(.+?)\s+\(\d+ bytes\)\s*$", output, re.MULTILINE)
                if not matches:
                    matches = re.findall(r"^SKIP existing:\s+(.+?)\s*$", output, re.MULTILINE)
                if len(matches) != 1 or not Path(matches[0]).is_file():
                    raise RuntimeError(f"合成阶段没有生成有效成片：{script_dir}")
                outputs.append(str(Path(matches[0]).resolve()))
            except Exception as exc:
                self.store.append_log(task_id, f"候选成片合成失败，继续处理备用候选：{exc}")
        return outputs

    def _publish(self, task_id: str, spec: dict[str, Any], artifacts: dict[str, Any]) -> None:
        root = self.workspace_root / "Finished-Video-Manager"
        statuses = artifacts.setdefault("publish_statuses", {})
        assignments = spec["assignments"]
        for index, assignment in enumerate(assignments):
            if statuses.get(str(index)) == "done":
                continue
            artifacts["active_publish_index"] = index
            self.store.update(task_id, artifacts=artifacts)
            command = [
                self._component_python("Finished-Video-Manager"), "-m", "finished_video_manager.pipeline_bridge",
                "publish", "--profile-id", assignment["profile_id"],
                "--video-path", artifacts["publish_videos"][index], "--caption", assignment["caption"],
                "--product-id", assignment["product_id"], "--product-short-name", assignment["product_short_name"],
            ]
            self._command(task_id, command, root)
            statuses[str(index)] = "done"
            artifacts["active_publish_index"] = None
            self.store.update(task_id, artifacts=artifacts)
            next_profile = assignments[index + 1]["profile_id"] if index + 1 < len(assignments) else ""
            if next_profile != assignment["profile_id"]:
                close_command = [
                    self._component_python("Finished-Video-Manager"), "-m", "finished_video_manager.pipeline_bridge",
                    "close", "--profile-id", assignment["profile_id"],
                ]
                self._command(task_id, close_command, root)
            if index + 1 < len(assignments):
                time.sleep(10)

    def _acquire_lock(self, task_id: str, source: str) -> Path:
        lock_root = self.store.path.parent / "locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(str(Path(source).resolve()).encode()).hexdigest()[:20]
        path = lock_root / f"{digest}.lock"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("该复刻脚本正在被另一个10005任务处理") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(task_id)
        return path
