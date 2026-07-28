from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
ASSEMBLY_RUNTIME = WORKSPACE_ROOT / "Video-Assembly-hd" / "runtime"
ASSEMBLY_VENDOR = WORKSPACE_ROOT / "Video-Assembly-hd" / "vendor"


@dataclass(frozen=True)
class MixerPaths:
    vault_root: Path
    ai_clip_root: Path
    audio_root: Path
    real_root: Path
    work_root: Path
    output_root: Path


def detect_vault_root() -> Path:
    configured = os.environ.get("OPC_VAULT_ROOT", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path("/Volumes/seafer/Obsidian Vault"),
        Path.home() / "Documents/Obsidian Vault",
    ]
    for candidate in candidates:
        if candidate and (candidate / "wiki/视频/AI实拍混剪").is_dir():
            return candidate.resolve()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Documents/Obsidian Vault").resolve()


def mixer_paths() -> MixerPaths:
    vault = detect_vault_root()
    hybrid = vault / "wiki/视频/AI实拍混剪"
    return MixerPaths(
        vault_root=vault,
        ai_clip_root=Path(os.environ.get("HYBRID_AI_CLIP_ROOT", hybrid / "05AI片段")).expanduser().resolve(),
        audio_root=Path(os.environ.get("HYBRID_PRODUCT_AUDIO_ROOT", hybrid / "06音频文件")).expanduser().resolve(),
        real_root=Path(os.environ.get("HYBRID_REAL_FOOTAGE_ROOT", hybrid / "07实拍素材")).expanduser().resolve(),
        work_root=Path(os.environ.get("HYBRID_MIX_WORK_ROOT", hybrid / "08混剪工作区")).expanduser().resolve(),
        output_root=Path(
            os.environ.get("VIDEO_ASSEMBLY_OUTPUT_ROOT", vault / "wiki/视频/成品视频")
        ).expanduser().resolve(),
    )


def ffmpeg_path() -> str:
    configured = os.environ.get("FFMPEG_BIN", "").strip()
    if configured and Path(configured).is_file():
        return configured
    direct = shutil.which("ffmpeg")
    if direct:
        return direct
    bundled = ASSEMBLY_RUNTIME / "bin" / "ffmpeg"
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError("未找到 FFmpeg")


def ffprobe_path() -> str:
    configured = os.environ.get("FFPROBE_BIN", "").strip()
    if configured and Path(configured).is_file():
        return configured
    direct = shutil.which("ffprobe")
    if direct:
        return direct
    bundled = ASSEMBLY_RUNTIME / "bin" / "ffprobe"
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError("未找到 FFprobe")


def hyperframes_cmd() -> list[str]:
    configured = os.environ.get("HYBRID_MIX_HYPERFRAMES", "").strip()
    if configured and Path(configured).is_file():
        return [configured]
    node = ASSEMBLY_RUNTIME / "bin" / "node"
    cli = ASSEMBLY_RUNTIME / "hyperframes" / "package" / "dist" / "cli.js"
    if node.is_file() and cli.is_file():
        return [str(node), str(cli)]
    direct = shutil.which("hyperframes")
    if direct:
        return [direct]
    raise RuntimeError("未找到离线 HyperFrames CLI")


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(detail[-4000:])
    return result


def safe_name(value: str, limit: int = 150) -> str:
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", str(value)).strip("._")
    return (cleaned or "未命名")[:limit]


def media_files(root: Path, extensions: set[str]) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions and not path.name.startswith(".")
    )


def probe_media(path: Path) -> dict:
    result = run(
        [
            ffprobe_path(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    data = json.loads(result.stdout or "{}")
    duration = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    has_audio = any(item.get("codec_type") == "audio" for item in streams)
    return {
        "path": str(path),
        "name": path.name,
        "duration": round(duration, 3),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "has_video": bool(video),
        "has_audio": has_audio,
    }


def relative_record(path: Path, root: Path) -> dict:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return {"name": path.name, "path": str(path), "relative_path": relative}


def scan_library(paths: MixerPaths | None = None) -> dict:
    paths = paths or mixer_paths()
    for folder in (paths.ai_clip_root, paths.audio_root, paths.real_root, paths.work_root, paths.output_root):
        folder.mkdir(parents=True, exist_ok=True)

    products: set[str] = set()
    if paths.real_root.is_dir():
        products.update(path.name for path in paths.real_root.iterdir() if path.is_dir())
    if paths.audio_root.is_dir():
        products.update(path.name for path in paths.audio_root.iterdir() if path.is_dir())
    if paths.ai_clip_root.is_dir():
        for model_dir in paths.ai_clip_root.iterdir():
            if not model_dir.is_dir():
                continue
            for kind in ("混剪-钩子", "混剪-CTA"):
                kind_dir = model_dir / kind
                if kind_dir.is_dir():
                    products.update(path.name for path in kind_dir.iterdir() if path.is_dir())

    records: list[dict] = []
    for product in sorted(products):
        models: dict[str, dict] = {}
        if paths.ai_clip_root.is_dir():
            for model_dir in sorted(path for path in paths.ai_clip_root.iterdir() if path.is_dir()):
                hooks = media_files(model_dir / "混剪-钩子" / product, VIDEO_EXTS)
                ctas = media_files(model_dir / "混剪-CTA" / product, VIDEO_EXTS)
                if hooks or ctas:
                    models[model_dir.name] = {
                        "hooks": [relative_record(path, paths.ai_clip_root) for path in hooks],
                        "ctas": [relative_record(path, paths.ai_clip_root) for path in ctas],
                    }
        audio = media_files(paths.audio_root / product, AUDIO_EXTS)
        display = media_files(paths.real_root / product / "展示", VIDEO_EXTS)
        usage = media_files(paths.real_root / product / "使用", VIDEO_EXTS)
        records.append(
            {
                "name": product,
                "models": models,
                "audio": [relative_record(path, paths.audio_root) for path in audio],
                "display": [relative_record(path, paths.real_root) for path in display],
                "usage": [relative_record(path, paths.real_root) for path in usage],
                "ready": bool(audio and display and usage and any(v["hooks"] and v["ctas"] for v in models.values())),
            }
        )
    return {
        "paths": {key: str(value) for key, value in asdict(paths).items()},
        "products": records,
        "summary": {
            "products": len(records),
            "ready_products": sum(1 for item in records if item["ready"]),
            "audio": sum(len(item["audio"]) for item in records),
            "display": sum(len(item["display"]) for item in records),
            "usage": sum(len(item["usage"]) for item in records),
            "hooks": sum(len(model["hooks"]) for item in records for model in item["models"].values()),
            "ctas": sum(len(model["ctas"]) for item in records for model in item["models"].values()),
        },
    }


def read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_inside(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"文件不在允许的素材目录中：{resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"文件不存在：{resolved}")
    return resolved


def sidecar_content_end(path: Path) -> float | None:
    candidates = [
        path.with_suffix(".metadata.json"),
        path.with_suffix(".json"),
        path.parent / f"{path.stem}.exported.json",
    ]
    keys = ("content_end", "effective_duration", "effective_duration_sec", "source_duration")
    for candidate in candidates:
        payload = read_json(candidate, {})
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key in keys:
                    try:
                        value = float(item.get(key))
                    except (TypeError, ValueError):
                        continue
                    if value > 0:
                        return value
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(value for value in item if isinstance(value, (dict, list)))
    return None


def trailing_black_start(path: Path, duration: float, has_audio: bool) -> float | None:
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-i",
        str(path),
        "-vf",
        "blackdetect=d=0.20:pic_th=0.98",
    ]
    if has_audio:
        command.extend(["-af", "silencedetect=n=-45dB:d=0.20"])
    command.extend(["-f", "null", "-"])
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    text = "\n".join((result.stdout or "", result.stderr or ""))
    black_candidates = []
    for start, end in re.findall(r"black_start:([\d.]+).*?black_end:([\d.]+)", text):
        if float(end) >= duration - 0.25:
            black_candidates.append(float(start))
    if not black_candidates:
        return None
    black_start = min(black_candidates)
    if not has_audio:
        return black_start
    silence_candidates = []
    for start, end in re.findall(r"silence_start:\s*([\d.]+).*?silence_end:\s*([\d.]+)", text, re.S):
        if float(end) >= duration - 0.25:
            silence_candidates.append(float(start))
    if not silence_candidates:
        trailing_start = re.findall(r"silence_start:\s*([\d.]+)", text)
        silence_candidates = [float(trailing_start[-1])] if trailing_start else []
    if silence_candidates and abs(min(silence_candidates) - black_start) <= 0.5:
        return max(0.1, min(black_start, min(silence_candidates)))
    return None


def effective_video_record(path: Path) -> dict:
    record = probe_media(path)
    duration = float(record["duration"])
    content_end = sidecar_content_end(path)
    if content_end is None and duration > 0:
        content_end = trailing_black_start(path, duration, bool(record["has_audio"]))
    if content_end is None or content_end <= 0 or content_end > duration:
        content_end = duration
    record["effective_duration"] = round(content_end, 3)
    record["technical_tail_trimmed"] = content_end < duration - 0.05
    return record


def usage_history_path(paths: MixerPaths) -> Path:
    return paths.work_root / "usage_history.json"


def load_usage_history(paths: MixerPaths) -> dict:
    payload = read_json(usage_history_path(paths), {})
    return {
        "sources": payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
        "routes": payload.get("routes") if isinstance(payload.get("routes"), list) else [],
        "outputs": payload.get("outputs") if isinstance(payload.get("outputs"), list) else [],
    }


def media_pool(records: list[dict]) -> list[dict]:
    pool = []
    for record in records:
        path = Path(record["path"])
        probed = probe_media(path)
        if probed["has_video"] and probed["duration"] >= 0.6:
            pool.append({**record, **probed})
    return pool


def choose_middle_timeline(
    display_pool: list[dict],
    usage_pool: list[dict],
    duration: float,
    *,
    seed: int,
    min_clip: float,
    max_clip: float,
    originality: str,
    history: dict | None = None,
) -> list[dict]:
    if duration <= 0:
        raise ValueError("产品介绍音频时长无效")
    if not display_pool or not usage_pool:
        raise ValueError("展示和使用两个实拍素材池都必须至少有一个可用视频")
    if min_clip <= 0 or max_clip < min_clip:
        raise ValueError("实拍切片时长设置无效")
    rng = random.Random(seed)
    history = history or {"sources": {}}
    pools = {"展示": list(display_pool), "使用": list(usage_pool)}
    for items in pools.values():
        rng.shuffle(items)
        items.sort(key=lambda item: history.get("sources", {}).get(item["path"], 0))

    timeline: list[dict] = []
    remaining = duration
    category = "展示" if seed % 2 == 0 else "使用"
    used_in_route: set[str] = set()
    while remaining > 0.03:
        desired = min(max_clip, remaining)
        if remaining > max_clip and remaining - desired < min_clip:
            desired = remaining / 2
        if remaining <= max_clip:
            desired = remaining
        elif originality == "enhanced":
            desired = min(desired, rng.uniform(min_clip, max_clip))
        desired = max(min_clip if remaining >= min_clip else remaining, desired)

        candidates = [item for item in pools[category] if item["path"] not in used_in_route]
        if not candidates:
            used_in_route.clear()
            candidates = list(pools[category])
        if timeline:
            non_adjacent = [item for item in candidates if item["path"] != timeline[-1]["path"]]
            if non_adjacent:
                candidates = non_adjacent
        candidates.sort(
            key=lambda item: (
                history.get("sources", {}).get(item["path"], 0),
                rng.random(),
            )
        )
        asset = candidates[0]
        source_duration = float(asset["duration"])
        clip_duration = min(desired, source_duration)
        if clip_duration <= 0.03:
            raise ValueError(f"实拍素材时长无效：{asset['name']}")
        max_start = max(0.0, source_duration - clip_duration)
        start = rng.uniform(0, max_start) if originality == "enhanced" and max_start > 0.05 else 0.0
        timeline.append(
            {
                "role": category,
                "path": asset["path"],
                "name": asset["name"],
                "start": round(start, 3),
                "duration": round(min(clip_duration, remaining), 3),
            }
        )
        used_in_route.add(asset["path"])
        remaining -= timeline[-1]["duration"]
        category = "使用" if category == "展示" else "展示"
        if len(timeline) > 200:
            raise RuntimeError("实拍编排片段数量异常")
    drift = duration - sum(item["duration"] for item in timeline)
    if timeline and abs(drift) > 0.001:
        timeline[-1]["duration"] = round(timeline[-1]["duration"] + drift, 3)
    return timeline


def route_signature(segments: list[dict]) -> str:
    raw = " > ".join(f"{item['role']}:{item['path']}:{item.get('start', 0):.2f}" for item in segments)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_plan(payload: dict, paths: MixerPaths | None = None) -> dict:
    paths = paths or mixer_paths()
    product = str(payload.get("product") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not product:
        raise ValueError("请选择产品")
    if not model:
        raise ValueError("请选择AI片段模型")

    hook = assert_inside(Path(str(payload.get("hook_path") or "")), paths.ai_clip_root)
    cta = assert_inside(Path(str(payload.get("cta_path") or "")), paths.ai_clip_root)
    audio = assert_inside(Path(str(payload.get("audio_path") or "")), paths.audio_root)
    expected_hook_root = paths.ai_clip_root / model / "混剪-钩子" / product
    expected_cta_root = paths.ai_clip_root / model / "混剪-CTA" / product
    assert_inside(hook, expected_hook_root)
    assert_inside(cta, expected_cta_root)
    assert_inside(audio, paths.audio_root / product)

    hook_record = effective_video_record(hook)
    cta_record = effective_video_record(cta)
    audio_record = probe_media(audio)
    if audio_record["duration"] <= 0:
        raise ValueError("产品介绍音频时长无效")
    library = scan_library(paths)
    product_record = next((item for item in library["products"] if item["name"] == product), None)
    if not product_record:
        raise ValueError("未找到产品素材目录")
    display_pool = media_pool(product_record["display"])
    usage_pool = media_pool(product_record["usage"])

    count = max(1, min(int(payload.get("count") or 1), 20))
    min_clip = max(0.6, min(float(payload.get("min_clip") or 1.6), 8.0))
    max_clip = max(min_clip, min(float(payload.get("max_clip") or 4.2), 12.0))
    originality = str(payload.get("originality") or "standard")
    if originality not in {"standard", "enhanced"}:
        originality = "standard"
    seed = int(payload.get("seed") or random.SystemRandom().randint(100000, 999999999))
    history = load_usage_history(paths)
    known_routes = set(history["routes"])
    variants = []
    for index in range(count):
        variant_seed = seed + index * 1009
        for attempt in range(12):
            candidate_seed = variant_seed + attempt * 7919
            middle = choose_middle_timeline(
                display_pool,
                usage_pool,
                audio_record["duration"],
                seed=candidate_seed,
                min_clip=min_clip,
                max_clip=max_clip,
                originality=originality,
                history=history,
            )
            full_segments = [
                {
                    "role": "AI钩子",
                    "path": str(hook),
                    "name": hook.name,
                    "start": 0.0,
                    "duration": hook_record["effective_duration"],
                    "preserve_audio": True,
                    "technical_tail_trimmed": hook_record["technical_tail_trimmed"],
                },
                *[{**item, "preserve_audio": False} for item in middle],
                {
                    "role": "AI CTA",
                    "path": str(cta),
                    "name": cta.name,
                    "start": 0.0,
                    "duration": cta_record["effective_duration"],
                    "preserve_audio": True,
                    "technical_tail_trimmed": cta_record["technical_tail_trimmed"],
                },
            ]
            signature = route_signature(full_segments)
            if signature not in known_routes or attempt == 11:
                variant_seed = candidate_seed
                known_routes.add(signature)
                break
        variants.append(
            {
                "index": index + 1,
                "seed": variant_seed,
                "segments": full_segments,
                "middle_audio": str(audio),
                "middle_duration": audio_record["duration"],
                "total_duration": round(
                    hook_record["effective_duration"]
                    + audio_record["duration"]
                    + cta_record["effective_duration"],
                    3,
                ),
                "route_signature": signature,
            }
        )

    created_at = dt.datetime.now().isoformat(timespec="seconds")
    plan_id = f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name(product, 60)}_{seed}"
    plan = {
        "version": 1,
        "plan_id": plan_id,
        "created_at": created_at,
        "product": product,
        "model": model,
        "settings": {
            "count": count,
            "min_clip": min_clip,
            "max_clip": max_clip,
            "originality": originality,
            "seed": seed,
            "canvas": "1080x1920",
            "fps": 30,
            "middle_audio_preserved": True,
        },
        "inputs": {
            "hook": hook_record,
            "audio": audio_record,
            "cta": cta_record,
            "display_count": len(display_pool),
            "usage_count": len(usage_pool),
        },
        "variants": variants,
    }
    plan_path = paths.work_root / product / "plans" / f"{plan_id}.json"
    write_json(plan_path, plan)
    plan["plan_path"] = str(plan_path)
    return plan


def originality_filter(seed: int, level: str) -> str:
    rng = random.Random(seed)
    if level == "enhanced":
        zoom = rng.uniform(1.018, 1.045)
        saturation = rng.uniform(0.97, 1.06)
        contrast = rng.uniform(0.985, 1.035)
        brightness = rng.uniform(-0.012, 0.012)
    else:
        zoom = rng.uniform(1.0, 1.015)
        saturation = rng.uniform(0.99, 1.025)
        contrast = rng.uniform(0.995, 1.018)
        brightness = rng.uniform(-0.006, 0.006)
    width = int(math.ceil(1080 * zoom / 2) * 2)
    height = int(math.ceil(1920 * zoom / 2) * 2)
    max_x = max(0, width - 1080)
    max_y = max(0, height - 1920)
    x = rng.randint(0, max_x) if max_x else 0
    y = rng.randint(0, max_y) if max_y else 0
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,scale={width}:{height},crop=1080:1920:{x}:{y},"
        f"eq=saturation={saturation:.4f}:contrast={contrast:.4f}:brightness={brightness:.4f},"
        "setsar=1,fps=30,format=yuv420p"
    )


def render_video_segment(segment: dict, output: Path, seed: int, level: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{float(segment.get('start') or 0):.3f}",
            "-t",
            f"{float(segment['duration']):.3f}",
            "-i",
            segment["path"],
            "-vf",
            originality_filter(seed, level),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        timeout=1200,
    )


def concat_video(segments: list[Path], output: Path) -> None:
    list_path = output.with_suffix(".concat.txt")
    list_path.write_text("\n".join(f"file '{path.as_posix()}'" for path in segments) + "\n", encoding="utf-8")
    run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-an",
            "-c:v",
            "copy",
            str(output),
        ],
        timeout=1200,
    )


def render_audio_piece(source: Path | None, duration: float, output: Path, start: float = 0.0) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if source and probe_media(source)["has_audio"]:
        run(
            [
                ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{duration:.3f}",
                "-i",
                str(source),
                "-vn",
                "-af",
                f"apad=pad_dur={duration:.3f},atrim=0:{duration:.3f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output),
            ],
            timeout=600,
        )
        return
    run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output),
        ],
        timeout=300,
    )


def concat_audio(pieces: list[Path], output: Path) -> None:
    list_path = output.with_suffix(".concat.txt")
    list_path.write_text("\n".join(f"file '{path.as_posix()}'" for path in pieces) + "\n", encoding="utf-8")
    run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output),
        ],
        timeout=600,
    )


def build_hyperframes_html(total_duration: float, cut_points: list[float]) -> str:
    transitions = []
    timelines = []
    for index, cut in enumerate(cut_points, start=1):
        start = max(0.0, cut - 0.12)
        transitions.append(
            f'<div id="wash-{index}" class="clip wash" data-start="{start:.3f}" '
            'data-duration="0.28" data-track-index="8"></div>'
        )
        timelines.append(
            f'tl.fromTo("#wash-{index}", {{opacity:0}}, {{opacity:0.18,duration:0.10,ease:"sine.inOut"}}, {start:.3f});'
        )
        timelines.append(
            f'tl.to("#wash-{index}", {{opacity:0,duration:0.17,ease:"sine.inOut",overwrite:"auto"}}, {start + 0.11:.3f});'
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <style>
    html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#000}}
    #main{{position:relative;width:1080px;height:1920px;overflow:hidden;background:#000}}
    video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
    .wash{{position:absolute;inset:0;background:#f5d38b;opacity:0;pointer-events:none}}
  </style>
</head>
<body>
  <div id="main" data-composition-id="main" data-start="0" data-width="1080" data-height="1920" data-duration="{total_duration:.3f}">
    <video id="visual-track" class="clip" src="media/visual.mp4" data-start="0" data-duration="{total_duration:.3f}" data-track-index="0" muted playsinline></video>
    <audio id="audio-track" class="clip" src="media/audio.m4a" data-start="0" data-duration="{total_duration:.3f}" data-track-index="1" data-volume="1"></audio>
    {''.join(transitions)}
  </div>
  <script src="vendor/gsap.min.js"></script>
  <script>
    window.__timelines=window.__timelines||{{}};
    var tl=gsap.timeline({{paused:true}});
    {''.join(timelines)}
    window.__timelines.main=tl;
  </script>
</body>
</html>
"""


def prepare_hyperframes_project(
    project_dir: Path,
    visual: Path,
    audio: Path,
    total_duration: float,
    cut_points: list[float],
) -> None:
    media_dir = project_dir / "media"
    vendor_dir = project_dir / "vendor"
    media_dir.mkdir(parents=True, exist_ok=True)
    vendor_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(visual, media_dir / "visual.mp4")
    shutil.copy2(audio, media_dir / "audio.m4a")
    gsap = ASSEMBLY_VENDOR / "gsap.min.js"
    if not gsap.is_file():
        raise RuntimeError(f"缺少离线 GSAP：{gsap}")
    shutil.copy2(gsap, vendor_dir / "gsap.min.js")
    (project_dir / "index.html").write_text(
        build_hyperframes_html(total_duration, cut_points),
        encoding="utf-8",
    )
    write_json(
        project_dir / "hyperframes.json",
        {
            "entry": "index.html",
            "compositions": [{"id": "main", "width": 1080, "height": 1920, "fps": 30}],
        },
    )


def run_hyperframes(project_dir: Path, output: Path) -> None:
    command = hyperframes_cmd()
    runtime_env = os.environ.copy()
    runtime_env["PATH"] = f"{ASSEMBLY_RUNTIME / 'bin'}:{runtime_env.get('PATH', '')}"
    for args in (["lint"], ["inspect", "--samples", "6"]):
        run(command + args, cwd=project_dir, env=runtime_env, timeout=600)
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        command
        + [
            "render",
            "--output",
            str(output),
            "--quality",
            "standard",
            "--fps",
            "30",
        ],
        cwd=project_dir,
        env=runtime_env,
        timeout=3600,
    )


def validate_finished_video(path: Path) -> dict:
    record = probe_media(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("成品文件为空")
    if record["duration"] <= 0 or not record["has_video"] or not record["has_audio"]:
        raise RuntimeError("成品缺少有效视频流或音频流")
    return record


def update_usage_history(paths: MixerPaths, variant: dict, output: Path) -> None:
    history = load_usage_history(paths)
    for segment in variant["segments"]:
        if segment["role"] in {"展示", "使用"}:
            key = segment["path"]
            history["sources"][key] = history["sources"].get(key, 0) + 1
    history["routes"].append(variant["route_signature"])
    history["routes"] = history["routes"][-1000:]
    history["outputs"].append(
        {
            "output": str(output),
            "route_signature": variant["route_signature"],
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    history["outputs"] = history["outputs"][-1000:]
    write_json(usage_history_path(paths), history)


def render_plan(
    plan: dict,
    *,
    paths: MixerPaths | None = None,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    paths = paths or mixer_paths()
    log = log or (lambda _message: None)
    outputs = []
    for variant in plan.get("variants") or []:
        index = int(variant["index"])
        variant_id = f"{plan['plan_id']}_V{index:02d}"
        work_dir = paths.work_root / plan["product"] / "renders" / variant_id
        if work_dir.exists():
            shutil.rmtree(work_dir)
        normalized_dir = work_dir / "normalized"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        level = plan["settings"]["originality"]
        video_parts = []
        cut_points = []
        elapsed = 0.0
        for position, segment in enumerate(variant["segments"], start=1):
            log(f"变体 {index}：处理片段 {position}/{len(variant['segments'])} · {segment['role']}")
            output = normalized_dir / f"{position:03d}.mp4"
            render_video_segment(segment, output, variant["seed"] + position * 37, level)
            video_parts.append(output)
            elapsed += float(segment["duration"])
            if position < len(variant["segments"]):
                cut_points.append(elapsed)
        visual = work_dir / "visual.mp4"
        concat_video(video_parts, visual)

        hook = variant["segments"][0]
        cta = variant["segments"][-1]
        hook_audio = work_dir / "hook.m4a"
        middle_audio = work_dir / "middle.m4a"
        cta_audio = work_dir / "cta.m4a"
        render_audio_piece(Path(hook["path"]), float(hook["duration"]), hook_audio)
        render_audio_piece(Path(variant["middle_audio"]), float(variant["middle_duration"]), middle_audio)
        render_audio_piece(Path(cta["path"]), float(cta["duration"]), cta_audio)
        audio = work_dir / "audio.m4a"
        concat_audio([hook_audio, middle_audio, cta_audio], audio)

        project_dir = work_dir / "hyperframes"
        prepare_hyperframes_project(
            project_dir,
            visual,
            audio,
            float(variant["total_duration"]),
            cut_points,
        )
        output_name = (
            f"AI实拍混剪-{safe_name(plan['product'], 70)}-"
            f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}-V{index:02d}.mp4"
        )
        output_path = paths.output_root / plan["product"] / output_name
        log(f"变体 {index}：HyperFrames渲染成片")
        run_hyperframes(project_dir, output_path)
        verified = validate_finished_video(output_path)
        metadata = {
            "agent": "Hybrid-Video-Mixer",
            "plan_id": plan["plan_id"],
            "product": plan["product"],
            "model": plan["model"],
            "settings": plan["settings"],
            "variant": variant,
            "verified": verified,
            "output": str(output_path),
        }
        write_json(output_path.with_suffix(".metadata.json"), metadata)
        update_usage_history(paths, variant, output_path)
        outputs.append({"path": str(output_path), "metadata": str(output_path.with_suffix(".metadata.json")), **verified})
        log(f"变体 {index}：完成 · {output_path.name}")
    return outputs


def list_outputs(paths: MixerPaths | None = None) -> list[dict]:
    paths = paths or mixer_paths()
    outputs = []
    for path in media_files(paths.output_root, {".mp4"}):
        if not path.name.startswith("AI实拍混剪-"):
            continue
        stat = path.stat()
        outputs.append(
            {
                "name": path.name,
                "path": str(path),
                "product": path.parent.name,
                "size": stat.st_size,
                "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    outputs.sort(key=lambda item: item["modified"], reverse=True)
    return outputs[:200]
