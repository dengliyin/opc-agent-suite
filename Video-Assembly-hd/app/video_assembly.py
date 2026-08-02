#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


APP_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = APP_ROOT / "runtime"
VENDOR_ROOT = APP_ROOT / "vendor"
CAPTION_TOOL_ROOT = VENDOR_ROOT / "tiktok-karaoke-captions"
CAPTION_TOOL_PATH = CAPTION_TOOL_ROOT / "caption.py"
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT") or "/__OPC_VAULT_ROOT_NOT_CONFIGURED__"
).expanduser()
PENDING_ROOT = Path(
    os.environ.get(
        "VIDEO_ASSEMBLY_PENDING_ROOT",
        str(VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "06合成工作区"),
    )
).expanduser()
OUTPUT_ROOT = Path(
    os.environ.get(
        "VIDEO_ASSEMBLY_OUTPUT_ROOT",
        str(VAULT_ROOT / "wiki" / "视频" / "成品视频"),
    )
).expanduser()
WORK_ROOT = Path(os.environ.get("VIDEO_ASSEMBLY_WORK_ROOT", str(APP_ROOT)))
REPORT_PATH = Path(
    os.environ.get("VIDEO_ASSEMBLY_REPORT_PATH", str(APP_ROOT / "data" / "latest-scan.json"))
)

VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
CLEANABLE_MEDIA_EXTS = VIDEO_EXTS | {".png", ".jpg", ".jpeg", ".webp", ".webm"}
EXPORT_MARKER_SUFFIX = ".exported.json"
CAPTION_MODES = ("none", "karaoke")
DEFAULT_CAPTION_MODE = "none"
COUNTRY_LANGUAGE_CODES = {
    "AT": "de",
    "BE": "nl",
    "BR": "pt",
    "CA": "en",
    "CH": "de",
    "DE": "de",
    "ES": "es",
    "FR": "fr",
    "IE": "en",
    "IT": "it",
    "MY": "ms",
    "NL": "nl",
    "PH": "en",
    "TH": "th",
    "UK": "en",
    "US": "en",
    "VN": "vi",
}
@dataclass
class SegmentPlan:
    index: int
    target_duration: float | None = None
    audio_text: str = ""


@dataclass
class ScriptItem:
    model: str
    date: str
    product: str
    script_dir: str
    md_path: str | None
    video_paths: list[str]
    output_path: str | None
    status: str
    marker_path: str | None = None
    media_cleaned: bool = False
    cleanup_eligible: bool = False
    cleanup_file_count: int = 0
    cleanup_bytes: int = 0
    caption_mode: str = DEFAULT_CAPTION_MODE
    issues: list[str] = field(default_factory=list)


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def natural_segment_key(path: Path) -> tuple[int, str]:
    match = re.search(r"片段\s*(\d+)", path.name)
    if match:
        return (int(match.group(1)), path.name)
    return (10_000, path.name)


def parse_timecode(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    return float(value)


def parse_segments(md_path: Path) -> list[SegmentPlan]:
    text = md_path.read_text(encoding="utf-8", errors="replace")
    header_re = re.compile(
        r"(?m)^#\s*Segment\s+(\d+)\s*[：:]\s*([0-9:.]+)\s*-\s*([0-9:.]+)\s*$"
    )
    matches = list(header_re.finditer(text))
    segments: list[SegmentPlan] = []
    for pos, match in enumerate(matches):
        start = parse_timecode(match.group(2))
        end = parse_timecode(match.group(3))
        block_end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        block = text[match.end() : block_end]
        audio_text = ""
        audio_match = re.search(r"\*\*\[音频文案\]\*\*\s*([^\n]+)", block)
        if audio_match:
            audio_text = audio_match.group(1).strip().strip('"')
        segments.append(SegmentPlan(index=int(match.group(1)), target_duration=max(0.0, end - start), audio_text=audio_text))
    return segments


def find_md(script_dir: Path) -> tuple[Path | None, list[str]]:
    issues: list[str] = []
    md_files = sorted(p for p in script_dir.glob("*.md") if p.is_file())
    if not md_files:
        return None, ["missing_md"]
    preferred = script_dir / f"{script_dir.name}.md"
    if preferred.exists():
        return preferred, issues
    if len(md_files) > 1:
        issues.append("multiple_md_using_first")
    return md_files[0], issues


def find_videos(script_dir: Path) -> list[Path]:
    videos = [p for p in script_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return sorted(videos, key=natural_segment_key)


def find_export_marker(md_path: Path) -> Path | None:
    preferred = md_path.with_name(f"{md_path.stem}{EXPORT_MARKER_SUFFIX}")
    if preferred.is_file():
        return preferred
    markers = sorted(path for path in md_path.parent.glob(f"*{EXPORT_MARKER_SUFFIX}") if path.is_file())
    return markers[0] if markers else None


def read_json_object(path: Path | None) -> dict:
    if not path or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def is_cleanable_media(path: Path) -> bool:
    return path.suffix.lower() in CLEANABLE_MEDIA_EXTS or path.name.endswith(".product-lock.json")


def cleanup_candidates(script_dir: Path, md_path: Path | None, marker_path: Path | None = None) -> list[Path]:
    protected = {path.resolve() for path in (md_path, marker_path) if path}
    candidates = [
        path
        for path in script_dir.iterdir()
        if path.is_file() and path.resolve() not in protected and is_cleanable_media(path)
    ]
    return sorted(candidates, key=lambda path: path.name)


def scan_items(pending_root: Path = PENDING_ROOT, output_root: Path = OUTPUT_ROOT) -> list[ScriptItem]:
    items: list[ScriptItem] = []
    if not pending_root.exists():
        die(f"Pending root does not exist: {pending_root}")
    for model_dir in sorted(p for p in pending_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for date_dir in sorted(p for p in model_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for product_dir in sorted(p for p in date_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
                for script_dir in sorted(p for p in product_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
                    md_path, issues = find_md(script_dir)
                    videos = find_videos(script_dir)
                    marker_path = find_export_marker(md_path) if md_path else None
                    marker = read_json_object(marker_path)
                    media_files = cleanup_candidates(script_dir, md_path, marker_path) if md_path else []
                    output_path = None
                    if md_path:
                        output_path = output_root / product_dir.name / f"{md_path.stem}.mp4"
                        legacy_output_path = (
                            output_root / model_dir.name / date_dir.name / product_dir.name / f"{md_path.stem}.mp4"
                        )
                        if not output_path.exists() and legacy_output_path.exists():
                            output_path = legacy_output_path
                    if output_path and output_path.exists():
                        status = "done"
                    elif md_path and videos:
                        status = "missing"
                    elif md_path and not videos:
                        status = "archived"
                    else:
                        if not videos:
                            issues.append("missing_videos")
                        status = "invalid"
                    items.append(
                        ScriptItem(
                            model=model_dir.name,
                            date=date_dir.name,
                            product=product_dir.name,
                            script_dir=str(script_dir),
                            md_path=str(md_path) if md_path else None,
                            video_paths=[str(p) for p in videos],
                            output_path=str(output_path) if output_path else None,
                            status=status,
                            marker_path=str(marker_path) if marker_path else None,
                            media_cleaned=bool(marker.get("media_cleaned")),
                            cleanup_eligible=status == "done" and bool(media_files),
                            cleanup_file_count=len(media_files),
                            cleanup_bytes=sum(path.stat().st_size for path in media_files),
                            issues=issues,
                        )
                    )
    return items


def report_payload(items: list[ScriptItem]) -> dict:
    by_status: dict[str, int] = {}
    by_model: dict[str, dict[str, int]] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_model.setdefault(item.model, {}).setdefault(item.status, 0)
        by_model[item.model][item.status] += 1
    return {
        "scan_id": uuid.uuid4().hex,
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pending_root": str(PENDING_ROOT),
        "output_root": str(OUTPUT_ROOT),
        "total_scripts": len(items),
        "by_status": by_status,
        "by_model": by_model,
        "items": [asdict(item) for item in items],
    }


def print_report(payload: dict, limit: int = 80) -> None:
    print(f"待拼接根目录: {payload['pending_root']}")
    print(f"成品根目录: {payload['output_root']}")
    print(f"脚本总数: {payload['total_scripts']}")
    print("状态统计:")
    labels = {"done": "已有成品", "missing": "待拼接", "archived": "已归档", "invalid": "异常"}
    for status in ("done", "missing", "archived", "invalid"):
        print(f"  {labels[status]}: {payload['by_status'].get(status, 0)}")
    print("模型统计:")
    for model, stats in sorted(payload["by_model"].items()):
        parts = ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))
        print(f"  {model}: {parts}")
    missing = [item for item in payload["items"] if item["status"] == "missing"]
    archived = [item for item in payload["items"] if item["status"] == "archived"]
    invalid = [item for item in payload["items"] if item["status"] == "invalid"]
    if missing:
        print("\n未拼接清单:")
        for item in missing[:limit]:
            print(f"  - {item['model']}/{item['date']}/{item['product']}/{Path(item['script_dir']).name} ({len(item['video_paths'])} clips)")
        if len(missing) > limit:
            print(f"  ... 还有 {len(missing) - limit} 条")
    if archived:
        print("\n已归档清单:")
        for item in archived[:limit]:
            print(f"  - {item['model']}/{item['date']}/{item['product']}/{Path(item['script_dir']).name}")
        if len(archived) > limit:
            print(f"  ... 还有 {len(archived) - limit} 条")
    if invalid:
        print("\n异常清单:")
        for item in invalid[:limit]:
            print(f"  - {item['model']}/{item['date']}/{item['product']}/{Path(item['script_dir']).name}: {', '.join(item['issues'])}")
        if len(invalid) > limit:
            print(f"  ... 还有 {len(invalid) - limit} 条")


def locate_bin(name: str, extra_paths: Iterable[Path] = ()) -> str | None:
    for path in extra_paths:
        candidate = path / name
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    return found


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = ":".join([str(RUNTIME_ROOT / "bin"), env.get("PATH", "")])
    ffmpeg = RUNTIME_ROOT / "bin" / "ffmpeg"
    ffprobe = RUNTIME_ROOT / "bin" / "ffprobe"
    browser = RUNTIME_ROOT / "chrome" / "chrome-headless-shell"
    if ffmpeg.exists():
        env["HYPERFRAMES_FFMPEG_PATH"] = str(ffmpeg)
    if ffprobe.exists():
        env["HYPERFRAMES_FFPROBE_PATH"] = str(ffprobe)
    if browser.exists():
        env["HYPERFRAMES_BROWSER_PATH"] = str(browser)
    env["HYPERFRAMES_NO_UPDATE_CHECK"] = "1"
    env["HYPERFRAMES_NO_AUTO_INSTALL"] = "1"
    env["HYPERFRAMES_NO_TELEMETRY"] = "1"
    env["DO_NOT_TRACK"] = "1"
    return env


def normalize_caption_mode(value: object) -> str:
    mode = str(value or DEFAULT_CAPTION_MODE)
    if mode not in CAPTION_MODES:
        raise ValueError("字幕模式无效")
    return mode


def caption_has_no_speech(md_path: Path) -> bool:
    audio_texts = []
    source = md_path.read_text(encoding="utf-8")
    for raw_text in re.findall(r"\*\*\[音频文案\]\*\*\s*[:：]?\s*([^\n]+)", source):
        text = raw_text.strip().strip('"')
        text = re.sub(r"^\s*(?:\([^)]*\)|（[^）]*）)\s*[:：]?\s*", "", text)
        text = text.lstrip(":： ").strip()
        if text:
            audio_texts.append(text)
    return bool(audio_texts) and all(
        ("无人物口播" in text or "无口播" in text)
        and "无旁白" in text
        and "无对白" in text
        for text in audio_texts
    )


def caption_language(md_path: Path) -> str:
    country_match = re.search(
        rf"(?:^|-|_)({'|'.join(COUNTRY_LANGUAGE_CODES)})(?:-|_)",
        md_path.stem.upper(),
    )
    return COUNTRY_LANGUAGE_CODES.get(country_match.group(1), "en") if country_match else "en"


def caption_runtime_ready() -> bool:
    return (
        CAPTION_TOOL_PATH.is_file()
        and (CAPTION_TOOL_ROOT / "fonts" / "Roboto-Black.ttf").is_file()
        and (RUNTIME_ROOT / "bin" / "uvx").is_file()
    )


def run_karaoke_captioner(input_path: Path, output_path: Path, md_path: Path, project_dir: Path) -> None:
    if caption_has_no_speech(md_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        verify_finished_output(output_path)
        return
    if not caption_runtime_ready():
        raise RuntimeError("TikTok 卡拉 OK 字幕运行依赖不完整")
    caption_dir = project_dir / "captions"
    caption_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(CAPTION_TOOL_PATH),
        str(input_path),
        "--caption-mode",
        "tiktok",
        "--model",
        os.environ.get("VIDEO_ASSEMBLY_WHISPER_MODEL", "medium"),
        "--language",
        caption_language(md_path),
        "--prefer-local",
        "--out-dir",
        str(caption_dir),
        "--out-name",
        output_path.name,
    ]
    env = runtime_env()
    env.pop("DEEPGRAM_API_KEY", None)
    env["UV_CACHE_DIR"] = str(RUNTIME_ROOT / "cache" / "uv")
    env["HF_HOME"] = str(RUNTIME_ROOT / "cache" / "huggingface")
    env["UV_OFFLINE"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    proc = run(command, cwd=CAPTION_TOOL_ROOT, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"TikTok 卡拉 OK 字幕生成失败\n{proc.stdout}")
    captioned = caption_dir / output_path.name
    if not captioned.is_file() or captioned.stat().st_size <= 0:
        raise RuntimeError(f"字幕工具未生成有效成品：{captioned}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(captioned), str(output_path))
    verify_finished_output(output_path)


def ffmpeg_path() -> str:
    env = runtime_env()
    configured = os.environ.get("VIDEO_ASSEMBLY_FFMPEG", "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffmpeg", path=env["PATH"])
    if found:
        return found
    die(f"Offline FFmpeg not found: {RUNTIME_ROOT / 'bin' / 'ffmpeg'}")


def ffprobe_path() -> str | None:
    env = runtime_env()
    configured = os.environ.get("VIDEO_ASSEMBLY_FFPROBE", "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffprobe", path=env["PATH"])
    if found:
        return found
    return None


def media_duration(path: Path) -> float:
    probe = ffprobe_path()
    if probe:
        proc = run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            env=runtime_env(),
        )
        if proc.returncode == 0:
            try:
                return float(proc.stdout.strip())
            except ValueError:
                pass
    proc = run([ffmpeg_path(), "-i", str(path), "-f", "null", "-"], env=runtime_env())
    match = re.search(r"Duration:\s*(\d+):(\d+):([0-9.]+)", proc.stdout)
    if not match:
        die(f"Could not probe duration: {path}\n{proc.stdout}")
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def verify_finished_output(path: Path) -> dict[str, float | bool]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"成品视频不存在或为空：{path}")
    probe = ffprobe_path()
    if not probe:
        raise RuntimeError("缺少 FFprobe，无法在清理前验证成品")
    proc = run(
        [
            probe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        env=runtime_env(),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"成品视频校验失败：{path}\n{proc.stdout.strip()}")
    try:
        payload = json.loads(proc.stdout)
        duration = float(payload.get("format", {}).get("duration") or 0)
        stream_types = {stream.get("codec_type") for stream in payload.get("streams", [])}
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取成品视频信息：{path}") from exc
    has_video = "video" in stream_types
    has_audio = "audio" in stream_types
    if duration <= 0 or not has_video or not has_audio:
        missing = []
        if duration <= 0:
            missing.append("有效时长")
        if not has_video:
            missing.append("视频轨")
        if not has_audio:
            missing.append("音频轨")
        raise RuntimeError(f"成品视频不完整，缺少{'/'.join(missing)}：{path}")
    return {"duration": duration, "has_video": has_video, "has_audio": has_audio}


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def media_type(path: Path) -> str:
    if path.name.endswith(".product-lock.json"):
        return "storyboard_meta"
    if path.suffix.lower() in VIDEO_EXTS | {".webm"}:
        return "video"
    return "image"


def cleaned_media_records(marker: dict, candidates: list[Path], cleaned_at: float) -> list[dict]:
    candidate_by_name = {path.name: path for path in candidates}
    records: list[dict] = []
    recorded_names: set[str] = set()
    for raw_record in marker.get("media_files") or []:
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        name = str(record.get("name") or Path(str(record.get("path") or "")).name)
        if name in candidate_by_name:
            record.update(
                {
                    "name": name,
                    "path": str(candidate_by_name[name]),
                    "type": record.get("type") or media_type(candidate_by_name[name]),
                    "cleaned": True,
                    "cleaned_at": cleaned_at,
                }
            )
        if name:
            recorded_names.add(name)
        records.append(record)
    for name, path in candidate_by_name.items():
        if name in recorded_names:
            continue
        records.append(
            {
                "name": name,
                "path": str(path),
                "type": media_type(path),
                "exists_at_export": True,
                "cleaned": True,
                "cleaned_at": cleaned_at,
            }
        )
    return records


def cleanup_items(items: list[ScriptItem]) -> dict:
    if not items:
        raise ValueError("请至少选择一个待清理项目")

    plans: list[tuple[ScriptItem, Path, Path, list[Path], dict]] = []
    for item in items:
        if item.status != "done" or not item.md_path or not item.output_path:
            raise ValueError(f"只能清理已有成品的项目：{item.script_dir}")
        script_dir = Path(item.script_dir).resolve()
        md_path = Path(item.md_path).resolve()
        output_path = Path(item.output_path).resolve()
        if md_path.parent != script_dir or not md_path.is_file():
            raise RuntimeError(f"脚本路径已变化，请重新扫描：{item.script_dir}")
        marker_path = Path(item.marker_path).resolve() if item.marker_path else md_path.with_name(f"{md_path.stem}{EXPORT_MARKER_SUFFIX}")
        if marker_path.parent != script_dir:
            raise RuntimeError(f"导出记录不在脚本目录中：{marker_path}")
        marker: dict = {}
        if marker_path.exists():
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"导出记录无法读取，已停止清理：{marker_path}") from exc
            if not isinstance(marker, dict):
                raise RuntimeError(f"导出记录格式无效，已停止清理：{marker_path}")
        verify_finished_output(output_path)
        candidates = [
            path
            for path in cleanup_candidates(script_dir, md_path, marker_path)
            if path.resolve() != output_path
        ]
        if not candidates:
            raise ValueError(f"没有可清理的片段或图片：{item.script_dir}")
        plans.append((item, output_path, marker_path, candidates, marker))

    cleaned: list[dict] = []
    deleted_count = 0
    deleted_bytes = 0
    for item, output_path, marker_path, candidates, marker in plans:
        deleted: list[str] = []
        for path in candidates:
            size = path.stat().st_size
            path.unlink()
            deleted.append(str(path))
            deleted_count += 1
            deleted_bytes += size
        cleaned_at = time.time()
        marker["schema_version"] = max(int(marker.get("schema_version") or 1), 2)
        marker["md_path"] = item.md_path
        marker["export_dir"] = item.script_dir
        marker["upload_status"] = "已清理"
        marker["media_cleaned"] = True
        marker["media_cleaned_at"] = cleaned_at
        marker["media_files"] = cleaned_media_records(marker, candidates, cleaned_at)
        write_json_atomic(marker_path, marker)
        cleaned.append(
            {
                "script_dir": item.script_dir,
                "output_path": str(output_path),
                "marker_path": str(marker_path),
                "deleted": deleted,
            }
        )
    return {
        "cleaned": cleaned,
        "deleted_count": deleted_count,
        "deleted_bytes": deleted_bytes,
    }


def audio_rms(path: Path, start: float, duration: float) -> float:
    if duration <= 0:
        return 0.0
    cmd = [
        ffmpeg_path(),
        "-v",
        "error",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "-",
    ]
    proc = subprocess.run(cmd, env=runtime_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not proc.stdout:
        return 0.0
    samples = memoryview(proc.stdout).cast("h")
    if not samples:
        return 0.0
    step = max(1, len(samples) // 200_000)
    values = samples[::step]
    mean_square = sum(int(x) * int(x) for x in values) / len(values)
    return math.sqrt(mean_square)


def tail_audio_is_active(path: Path, target_duration: float, actual_duration: float) -> bool:
    if actual_duration <= target_duration + 0.25:
        return False
    body_start = min(0.5, max(0.0, target_duration / 4))
    body_duration = max(0.4, min(target_duration - body_start, 2.0))
    tail_duration = min(1.5, actual_duration - target_duration)
    body = audio_rms(path, body_start, body_duration)
    tail = audio_rms(path, target_duration, tail_duration)
    threshold = max(180.0, body * 0.16)
    return tail >= threshold


def safe_name(value: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value).strip("_")[:180]


def build_index_html(
    clips: list[dict],
    total_duration: float,
    transition_duration: float = 0.36,
) -> str:
    media_lines: list[str] = []
    transition_lines: list[str] = []
    timeline_lines: list[str] = []
    current = 0.0
    for i, clip in enumerate(clips, start=1):
        duration = clip["duration"]
        src = f"media/{clip['media_name']}"
        media_lines.append(
            f'      <video id="video-{i}" data-start="{current:.3f}" data-duration="{duration:.3f}" data-track-index="0" src="{src}" muted playsinline></video>'
        )
        media_lines.append(
            f'      <audio id="audio-{i}" data-start="{current:.3f}" data-duration="{duration:.3f}" data-track-index="1" src="{src}" data-volume="1"></audio>'
        )
        if i < len(clips):
            transition_start = max(0.0, current + duration - transition_duration / 2)
            transition_lines.append(
                f'      <div id="transition-{i}" class="clip transition-wash" data-start="{transition_start:.3f}" data-duration="{transition_duration:.3f}" data-track-index="8"></div>'
            )
            timeline_lines.append(
                f'      tl.fromTo("#transition-{i}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.12, ease: "sine.inOut" }}, {transition_start:.3f});'
            )
            timeline_lines.append(
                f'      tl.to("#transition-{i}", {{ opacity: 0, duration: 0.18, ease: "sine.inOut" }}, {transition_start + 0.140:.3f});'
            )
        current += duration
    media_html = "\n".join([*media_lines, *transition_lines])
    timeline_html = "\n".join(timeline_lines)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>video-assembly-hd</title>
    <style>
      @font-face {{
        font-family: "Assembly Sans";
        src: local("PingFang SC");
        font-style: normal;
        font-weight: 400 900;
      }}
      html, body {{
        margin: 0;
        width: 100%;
        height: 100%;
        background: #15110d;
        overflow: hidden;
      }}
      #assembled-video-root {{
        position: relative;
        width: 1080px;
        height: 1920px;
        overflow: hidden;
        background: #15110d;
        font-family: "Assembly Sans", Arial, sans-serif;
      }}
      video {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
        background: #15110d;
        z-index: 1;
      }}
      .transition-wash {{
        position: absolute;
        inset: 0;
        z-index: 15;
        background: rgba(216, 181, 109, 0.26);
        opacity: 0;
        pointer-events: none;
      }}
    </style>
  </head>
  <body>
    <div id="assembled-video-root" data-composition-id="assembled-video" data-start="0" data-width="1080" data-height="1920" data-duration="{total_duration:.3f}">
{media_html}
    </div>
    <script src="vendor/gsap.min.js"></script>
    <script>
      window.__timelines = window.__timelines || {{}};
      var tl = gsap.timeline({{ paused: true }});
{timeline_html}
      window.__timelines["assembled-video"] = tl;
    </script>
  </body>
</html>
"""


def hyperframes_cmd() -> list[str]:
    env = runtime_env()
    configured = os.environ.get("VIDEO_ASSEMBLY_HYPERFRAMES", "").strip()
    if configured and Path(configured).is_file():
        configured_path = Path(configured)
        if configured_path.suffix == ".js":
            node = RUNTIME_ROOT / "bin" / "node"
            if not node.exists():
                die(f"Offline Node.js not found: {node}")
            return [str(node), str(configured_path)]
        return [str(configured_path)]
    local_node = RUNTIME_ROOT / "bin" / "node"
    local_cli = RUNTIME_ROOT / "hyperframes" / "package" / "dist" / "cli.js"
    if local_node.exists() and local_cli.exists():
        return [str(local_node), str(local_cli)]
    direct = shutil.which("hyperframes", path=env["PATH"])
    if direct:
        return [direct]
    die(f"Offline HyperFrames CLI not found: {local_cli}")


def run_hyperframes(project_dir: Path, output_path: Path, skip_inspect: bool = False) -> None:
    cmd = hyperframes_cmd()
    for args in (["lint"], [] if skip_inspect else ["inspect", "--samples", "8"]):
        if not args:
            continue
        proc = run(cmd + args, cwd=project_dir, env=runtime_env())
        if proc.returncode != 0:
            die(f"HyperFrames {' '.join(args)} failed in {project_dir}\n{proc.stdout}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = run(cmd + ["render", "--output", str(output_path), "--quality", "standard", "--fps", "30"], cwd=project_dir, env=runtime_env())
    if proc.returncode != 0:
        die(f"HyperFrames render failed in {project_dir}\n{proc.stdout}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        die(f"Render did not create a valid output: {output_path}")


def project_for_item(item: ScriptItem) -> Path:
    return WORK_ROOT / "runs" / safe_name(f"{item.model}-{item.date}-{item.product}-{Path(item.script_dir).name}")


def prepare_project(item: ScriptItem) -> tuple[Path, list[dict]]:
    if not item.md_path or not item.output_path:
        die(f"Item has no markdown/output path: {item.script_dir}")
    md_path = Path(item.md_path)
    videos = [Path(p) for p in item.video_paths]
    segments = parse_segments(md_path)
    project_dir = project_for_item(item)
    media_dir = project_dir / "media"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    media_dir.mkdir(parents=True)
    shutil.copy2(md_path, project_dir / md_path.name)
    gsap_source = VENDOR_ROOT / "gsap.min.js"
    if not gsap_source.exists():
        die(f"Offline GSAP asset not found: {gsap_source}")
    project_vendor_dir = project_dir / "vendor"
    project_vendor_dir.mkdir()
    shutil.copy2(gsap_source, project_vendor_dir / "gsap.min.js")

    clips: list[dict] = []
    for idx, source in enumerate(videos, start=1):
        segment = segments[idx - 1] if idx - 1 < len(segments) else SegmentPlan(index=idx)
        actual = media_duration(source)
        target = segment.target_duration
        media_name = f"segment_{idx:02d}.mp4"
        dest = media_dir / media_name
        duration = actual
        action = "use_actual"
        speed = 1.0
        if target and target > 0:
            if actual > target * 1.08:
                if segment.audio_text and tail_audio_is_active(source, target, actual):
                    shutil.copy2(source, dest)
                    duration = actual
                    action = "keep_active_tail"
                else:
                    shutil.copy2(source, dest)
                    duration = target
                    action = "trim_tail"
            else:
                shutil.copy2(source, dest)
                duration = min(actual, target) if actual > target else actual
                action = "target_or_actual"
        else:
            shutil.copy2(source, dest)
        clips.append(
            {
                "index": idx,
                "source": str(source),
                "media_name": media_name,
                "actual_duration": actual,
                "target_duration": target,
                "duration": duration,
                "action": action,
                "speed": speed,
            }
        )

    total = sum(clip["duration"] for clip in clips)
    (project_dir / "index.html").write_text(build_index_html(clips, total), encoding="utf-8")
    (project_dir / "assembly-plan.json").write_text(
        json.dumps(
            {
                "clips": clips,
                "total_duration": total,
                "caption_mode": normalize_caption_mode(item.caption_mode),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return project_dir, clips


def assemble_item(item: ScriptItem, skip_existing: bool = True, skip_inspect: bool = False, plan_only: bool = False) -> None:
    if item.status == "invalid":
        print(f"SKIP invalid: {item.script_dir} ({', '.join(item.issues)})")
        return
    output_path = Path(item.output_path or "")
    if skip_existing and output_path.exists():
        print(f"SKIP existing: {output_path}")
        return
    print(f"ASSEMBLE {item.model}/{item.date}/{item.product}/{Path(item.script_dir).name}")
    project_dir, clips = prepare_project(item)
    for clip in clips:
        target = clip["target_duration"]
        target_text = f"{target:.3f}s" if target else "none"
        print(
            f"  clip {clip['index']}: actual={clip['actual_duration']:.3f}s target={target_text} "
            f"duration={clip['duration']:.3f}s action={clip['action']}"
        )
    if plan_only:
        print(f"  plan: {project_dir / 'assembly-plan.json'}")
        return
    caption_mode = normalize_caption_mode(item.caption_mode)
    render_path = project_dir / "uncaptioned.mp4" if caption_mode == "karaoke" else output_path
    run_hyperframes(project_dir, render_path, skip_inspect=skip_inspect)
    if caption_mode == "karaoke":
        run_karaoke_captioner(render_path, output_path, Path(item.md_path or ""), project_dir)
    print(f"  output: {output_path} ({output_path.stat().st_size} bytes)")


def load_report(path: Path = REPORT_PATH) -> dict:
    if not path.exists():
        die(f"Report not found: {path}. Run scan --write-report first.")
    return json.loads(path.read_text(encoding="utf-8"))


def item_from_dict(data: dict) -> ScriptItem:
    return ScriptItem(
        model=data["model"],
        date=data["date"],
        product=data["product"],
        script_dir=data["script_dir"],
        md_path=data.get("md_path"),
        video_paths=data.get("video_paths", []),
        output_path=data.get("output_path"),
        status=data["status"],
        marker_path=data.get("marker_path"),
        media_cleaned=bool(data.get("media_cleaned")),
        cleanup_eligible=bool(data.get("cleanup_eligible")),
        cleanup_file_count=int(data.get("cleanup_file_count") or 0),
        cleanup_bytes=int(data.get("cleanup_bytes") or 0),
        caption_mode=normalize_caption_mode(data.get("caption_mode")),
        issues=data.get("issues", []),
    )


def cmd_scan(args: argparse.Namespace) -> None:
    payload = report_payload(scan_items())
    print_report(payload, limit=args.limit)
    if args.write_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nreport: {REPORT_PATH}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_assemble(args: argparse.Namespace) -> None:
    if args.script_dir:
        script_dir = Path(args.script_dir).resolve()
        items = scan_items()
        matches = [item for item in items if Path(item.script_dir).resolve() == script_dir]
        if not matches:
            die(f"Script dir not found in pending tree: {script_dir}")
        selected = matches
    else:
        payload = load_report(Path(args.report) if args.report else REPORT_PATH)
        selected = [item_from_dict(item) for item in payload["items"] if item["status"] == "missing"]
        if not args.all_missing:
            die("Use --script-dir for one item or --all-missing to assemble all missing items from the report.")
    if not selected:
        print("No items to assemble.")
        return
    for item in selected:
        assemble_item(item, skip_existing=not args.overwrite, skip_inspect=args.skip_inspect, plan_only=args.plan_only)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan and assemble pending product-video clips.")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Scan pending folders and compare with finished MP4s.")
    scan.add_argument("--write-report", action="store_true", help=f"Write JSON report to {REPORT_PATH}.")
    scan.add_argument("--json", action="store_true", help="Also print full JSON payload.")
    scan.add_argument("--limit", type=int, default=80, help="Max missing/invalid rows to print.")
    scan.set_defaults(func=cmd_scan)

    assemble = sub.add_parser("assemble", help="Assemble confirmed missing items.")
    assemble.add_argument("--script-dir", help="Assemble one script folder.")
    assemble.add_argument("--all-missing", action="store_true", help="Assemble all missing items from the scan report.")
    assemble.add_argument("--report", help=f"Scan report path. Defaults to {REPORT_PATH}.")
    assemble.add_argument("--overwrite", action="store_true", help="Overwrite existing output MP4s.")
    assemble.add_argument("--skip-inspect", action="store_true", help="Skip HyperFrames inspect; lint still runs.")
    assemble.add_argument("--plan-only", action="store_true", help="Prepare media and print timing decisions without rendering.")
    assemble.set_defaults(func=cmd_assemble)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
