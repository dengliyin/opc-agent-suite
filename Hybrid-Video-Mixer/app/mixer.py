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
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
DELIVERY_SIDECAR_SUFFIX = ".delivery.json"
MAX_REAL_FOOTAGE_USES = 5
DEDUPLICATION_OPTIONS = (
    "transform",
    "color",
    "tone",
    "detail",
    "frame_drop",
    "mirror",
    "speed",
    "border",
    "effect",
    "encoding",
)
MARKET_NAMES = {
    "BR": "巴西",
    "ES": "西班牙",
    "IE": "爱尔兰",
    "IT": "意大利",
    "MY": "马来西亚",
    "PH": "菲律宾",
    "TH": "泰国",
    "VN": "越南",
}
UNSPECIFIED_MARKET = "未标注"
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
ASSEMBLY_RUNTIME = WORKSPACE_ROOT / "Video-Assembly-hd" / "runtime"
CAPTION_TOOL_ROOT = ROOT / "vendor" / "tiktok-karaoke-captions"
CAPTION_TOOL_PATH = CAPTION_TOOL_ROOT / "caption.py"
GSAP_SOURCE = WORKSPACE_ROOT / "Video-Assembly-hd" / "vendor" / "gsap.min.js"
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


@dataclass(frozen=True)
class MixerPaths:
    vault_root: Path
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


def caption_language(market: str) -> str:
    return COUNTRY_LANGUAGE_CODES.get(str(market).upper(), "en")


def caption_runtime_ready() -> bool:
    return (
        CAPTION_TOOL_PATH.is_file()
        and (CAPTION_TOOL_ROOT / "fonts" / "Roboto-Black.ttf").is_file()
        and (ASSEMBLY_RUNTIME / "bin" / "uvx").is_file()
    )


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


def caption_runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{ASSEMBLY_RUNTIME / 'bin'}:{env.get('PATH', '')}"
    env.pop("DEEPGRAM_API_KEY", None)
    env["UV_CACHE_DIR"] = str(ASSEMBLY_RUNTIME / "cache" / "uv")
    env["HF_HOME"] = str(ASSEMBLY_RUNTIME / "cache" / "huggingface")
    env["UV_OFFLINE"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    return env


def audio_subtitle_paths(audio_path: Path) -> dict[str, Path]:
    return {
        "ass": audio_path.with_suffix(".ass"),
        "srt": audio_path.with_suffix(".srt"),
        "caption_json": audio_path.with_name(f"{audio_path.stem}.caption.json"),
    }


def valid_ass_subtitles(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        return bool(re.search(r"(?m)^Dialogue:", path.read_text(encoding="utf-8")))
    except OSError:
        return False


def audio_library_record(path: Path, root: Path) -> dict:
    record = relative_record(path, root)
    subtitles = audio_subtitle_paths(path)
    record["subtitle_ready"] = valid_ass_subtitles(subtitles["ass"])
    record["subtitle_paths"] = {key: str(value) for key, value in subtitles.items()}
    return record


def ensure_audio_subtitles(
    audio_path: Path,
    duration: float,
    market: str,
    project_dir: Path,
) -> dict[str, Path]:
    sidecars = audio_subtitle_paths(audio_path)
    if valid_ass_subtitles(sidecars["ass"]):
        return sidecars
    if not caption_runtime_ready():
        raise RuntimeError("TikTok 卡拉 OK 字幕运行依赖不完整")
    caption_dir = project_dir / "caption-generation" / safe_name(audio_path.stem)
    caption_dir.mkdir(parents=True, exist_ok=True)
    reference_video = caption_dir / f"{audio_path.stem}.mp4"
    run(
        [
            ffmpeg_path(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=1080x1920:rate=30",
            "-i",
            str(audio_path),
            "-t",
            f"{duration:.3f}",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(reference_video),
        ],
        timeout=900,
    )
    command = [
        sys.executable,
        str(CAPTION_TOOL_PATH),
        str(reference_video),
        "--caption-mode",
        "tiktok",
        "--model",
        os.environ.get("VIDEO_ASSEMBLY_WHISPER_MODEL", "medium"),
        "--language",
        caption_language(market),
        "--prefer-local",
        "--out-dir",
        str(caption_dir),
        "--srt-only",
    ]
    run(command, cwd=CAPTION_TOOL_ROOT, env=caption_runtime_env(), timeout=3600)
    generated = {
        "ass": caption_dir / f"{reference_video.stem}.ass",
        "srt": caption_dir / f"{reference_video.stem}.srt",
        "caption_json": caption_dir / f"{reference_video.stem}-whisper.json",
    }
    if not valid_ass_subtitles(generated["ass"]):
        raise RuntimeError("本地 Whisper 未识别到可生成字幕的语音内容")
    for key, path in generated.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"字幕工具未生成有效文件：{path}")
        sidecars[key].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, sidecars[key])
    return sidecars


def parse_ass_time(value: str) -> float:
    hours, minutes, seconds = value.strip().split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_ass_time(value: float) -> str:
    centiseconds = max(0, int(round(value * 100)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def shift_ass_subtitles(
    source_path: Path,
    output_path: Path,
    *,
    offset: float,
    duration: float,
) -> None:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    shifted = []
    dialogue_count = 0
    for line in lines:
        if not line.startswith("Dialogue:"):
            shifted.append(line)
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            continue
        start = parse_ass_time(fields[1])
        end = min(parse_ass_time(fields[2]), duration)
        if start >= duration or end <= 0 or end <= start:
            continue
        fields[1] = format_ass_time(offset + max(0, start))
        fields[2] = format_ass_time(offset + end)
        shifted.append(",".join(fields))
        dialogue_count += 1
    if not dialogue_count:
        raise RuntimeError("本地字幕文件没有落在混剪音频时长内的有效字幕")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(shifted) + "\n", encoding="utf-8")


def burn_ass_subtitles(input_path: Path, subtitle_path: Path, output_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="hybrid-caption-") as temporary:
        temp = Path(temporary)
        local_video = temp / "input.mp4"
        local_ass = temp / "sub.ass"
        local_fonts = temp / "fonts"
        shutil.copy2(input_path, local_video)
        shutil.copy2(subtitle_path, local_ass)
        shutil.copytree(CAPTION_TOOL_ROOT / "fonts", local_fonts)
        local_output = temp / "output.mp4"
        run(
            [
                ffmpeg_path(),
                "-y",
                "-i",
                local_video.name,
                "-vf",
                "subtitles=sub.ass:fontsdir=fonts",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-c:a",
                "copy",
                local_output.name,
            ],
            cwd=temp,
            timeout=3600,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_output, output_path)


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


def media_market(path: Path) -> str:
    for token in path.stem.split("-"):
        if re.fullmatch(r"[A-Z]{2}", token):
            return token
    return UNSPECIFIED_MARKET


def market_label(market: str) -> str:
    name = MARKET_NAMES.get(market)
    return f"{market} · {name}" if name else market


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
    format_duration = 0.0
    try:
        format_duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        format_duration = 0.0
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    duration = format_duration
    if video:
        try:
            video_duration = float(video.get("duration") or 0)
        except (TypeError, ValueError):
            video_duration = 0.0
        if video_duration > 0:
            duration = video_duration
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


def usage_record(path: Path, root: Path, history: dict) -> dict:
    record = relative_record(path, root)
    record["used_count"] = int(history.get("sources", {}).get(str(path), 0))
    return record


def delivery_archive_root(paths: MixerPaths) -> Path:
    return paths.work_root / "片段产出归档"


def ai_clip_collections(paths: MixerPaths) -> dict[tuple[str, str, str], list[Path]]:
    collections: dict[tuple[str, str, str], list[Path]] = {}
    archive_root = delivery_archive_root(paths)
    if archive_root.is_dir():
        for sidecar_path in archive_root.rglob(f"*{DELIVERY_SIDECAR_SUFFIX}"):
            payload = read_json(sidecar_path, {})
            video_path = Path(str(payload.get("video_path") or "")).expanduser().resolve()
            try:
                video_path.relative_to(archive_root.resolve())
            except ValueError:
                continue
            model = str(payload.get("model") or "").strip()
            script_type = str(payload.get("script_type") or "").strip()
            product = str(payload.get("product_name") or "").strip()
            if (
                model
                and script_type in {"混剪-钩子", "混剪-CTA"}
                and product
                and video_path.is_file()
                and video_path.suffix.lower() in VIDEO_EXTS
            ):
                collections.setdefault((model, script_type, product), []).append(video_path)
    return {
        key: sorted(set(items))
        for key, items in collections.items()
    }


def ai_clip_usage_record(path: Path, paths: MixerPaths, history: dict) -> dict:
    return usage_record(path, delivery_archive_root(paths), history)


def scan_library(paths: MixerPaths | None = None) -> dict:
    paths = paths or mixer_paths()
    for folder in (paths.audio_root, paths.real_root, paths.work_root, paths.output_root):
        folder.mkdir(parents=True, exist_ok=True)
    history = load_usage_history(paths)
    ai_clips = ai_clip_collections(paths)

    products: set[str] = set()
    if paths.real_root.is_dir():
        products.update(path.name for path in paths.real_root.iterdir() if path.is_dir())
    if paths.audio_root.is_dir():
        products.update(path.name for path in paths.audio_root.iterdir() if path.is_dir())
    products.update(product for _, _, product in ai_clips)

    records: list[dict] = []
    for product in sorted(products):
        models: dict[str, dict] = {}
        market_models: dict[str, dict[str, dict]] = {}
        for model in sorted({model for model, _, item_product in ai_clips if item_product == product}):
            hooks = ai_clips.get((model, "混剪-钩子", product), [])
            ctas = ai_clips.get((model, "混剪-CTA", product), [])
            models[model] = {
                "hooks": [ai_clip_usage_record(path, paths, history) for path in hooks],
                "ctas": [ai_clip_usage_record(path, paths, history) for path in ctas],
            }
            for key, items in (("hooks", hooks), ("ctas", ctas)):
                for path in items:
                    market = media_market(path)
                    model_record = market_models.setdefault(market, {}).setdefault(
                        model,
                        {"hooks": [], "ctas": []},
                    )
                    model_record[key].append(ai_clip_usage_record(path, paths, history))
        audio = media_files(paths.audio_root / product, AUDIO_EXTS)
        market_audio: dict[str, list[dict]] = {}
        for path in audio:
            market_audio.setdefault(media_market(path), []).append(audio_library_record(path, paths.audio_root))
        markets = {}
        for market in sorted(set(market_models) | set(market_audio)):
            market_record = {
                "code": market,
                "label": market_label(market),
                "models": market_models.get(market, {}),
                "audio": market_audio.get(market, []),
            }
            market_record["subtitle_count"] = sum(
                1 for item in market_record["audio"] if item["subtitle_ready"]
            )
            market_record["missing_subtitle_count"] = (
                len(market_record["audio"]) - market_record["subtitle_count"]
            )
            market_record["ready"] = bool(
                market_record["audio"]
                and any(
                    any(not hook["used_count"] for hook in model["hooks"])
                    for model in market_record["models"].values()
                )
            )
            markets[market] = market_record
        display = [
            usage_record(path, paths.real_root, history)
            for path in media_files(paths.real_root / product / "展示", VIDEO_EXTS)
        ]
        usage = [
            usage_record(path, paths.real_root, history)
            for path in media_files(paths.real_root / product / "使用", VIDEO_EXTS)
        ]
        available_display = [item for item in display if item["used_count"] < MAX_REAL_FOOTAGE_USES]
        available_usage = [item for item in usage if item["used_count"] < MAX_REAL_FOOTAGE_USES]
        records.append(
            {
                "name": product,
                "models": models,
                "audio": [audio_library_record(path, paths.audio_root) for path in audio],
                "display": display,
                "usage": usage,
                "markets": markets,
                "ready": bool(
                    available_display
                    and available_usage
                    and any(item["ready"] for item in markets.values())
                ),
            }
        )
    return {
        "paths": {
            **{key: str(value) for key, value in asdict(paths).items()},
            "delivery_archive_root": str(delivery_archive_root(paths)),
        },
        "products": records,
        "summary": {
            "products": len(records),
            "ready_products": sum(1 for item in records if item["ready"]),
            "markets": sum(len(item["markets"]) for item in records),
            "ready_markets": sum(
                1
                for item in records
                for market in item["markets"].values()
                if market["ready"]
                and any(asset["used_count"] < MAX_REAL_FOOTAGE_USES for asset in item["display"])
                and any(asset["used_count"] < MAX_REAL_FOOTAGE_USES for asset in item["usage"])
            ),
            "audio": sum(len(item["audio"]) for item in records),
            "subtitles": sum(
                market["subtitle_count"]
                for item in records
                for market in item["markets"].values()
            ),
            "missing_subtitles": sum(
                market["missing_subtitle_count"]
                for item in records
                for market in item["markets"].values()
            ),
            "display": sum(len(item["display"]) for item in records),
            "usage": sum(len(item["usage"]) for item in records),
            "available_display": sum(
                1
                for item in records
                for asset in item["display"]
                if asset["used_count"] < MAX_REAL_FOOTAGE_USES
            ),
            "available_usage": sum(
                1
                for item in records
                for asset in item["usage"]
                if asset["used_count"] < MAX_REAL_FOOTAGE_USES
            ),
            "hooks": sum(len(model["hooks"]) for item in records for model in item["models"].values()),
            "available_hooks": sum(
                1
                for item in records
                for model in item["models"].values()
                for hook in model["hooks"]
                if not hook["used_count"]
            ),
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


def delivery_sidecar_path(video_path: Path) -> Path:
    return video_path.with_suffix(video_path.suffix + DELIVERY_SIDECAR_SUFFIX)


def update_delivery_marker(
    video_path: Path,
    *,
    used_output: Path | None = None,
    cleaned: bool = False,
) -> bool:
    sidecar = read_json(delivery_sidecar_path(video_path), {})
    marker_path = Path(str(sidecar.get("marker_path") or "")).expanduser()
    if not marker_path.is_file():
        return False
    marker = read_json(marker_path, {})
    if not isinstance(marker, dict):
        return False
    now = dt.datetime.now().isoformat(timespec="seconds")
    if used_output is not None:
        marker["upload_status"] = "已用于混剪"
        marker["consumed_at"] = now
        outputs = [str(path) for path in marker.get("used_outputs") or [] if str(path).strip()]
        output = str(used_output)
        if output not in outputs:
            outputs.append(output)
        marker["used_outputs"] = outputs
    if cleaned:
        for item in marker.get("media_files") or []:
            if str(item.get("path") or "") == str(video_path):
                item["cleaned"] = True
                item["cleaned_at"] = now
        media_files = marker.get("media_files") or []
        marker["media_cleaned"] = bool(media_files) and all(
            bool(item.get("cleaned")) or not Path(str(item.get("path") or "")).exists()
            for item in media_files
        )
        marker["media_cleaned_at"] = now if marker["media_cleaned"] else None
    try:
        write_json(marker_path, marker)
    except OSError:
        return False
    return True


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
        "middle_routes": payload.get("middle_routes") if isinstance(payload.get("middle_routes"), list) else [],
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
    history: dict | None = None,
) -> list[dict]:
    if duration <= 0:
        raise ValueError("产品介绍音频时长无效")
    if not display_pool or not usage_pool:
        raise ValueError("展示和使用两个实拍素材池都必须至少有一个可用视频")
    rng = random.Random(seed)
    history = history or {"sources": {}}
    pools = {"展示": list(display_pool), "使用": list(usage_pool)}
    for items in pools.values():
        rng.shuffle(items)
        items.sort(key=lambda item: history.get("sources", {}).get(item["path"], 0))

    timeline: list[dict] = []
    remaining = duration
    display_target = duration / 2
    display_phase = True
    used_in_route: set[str] = set()
    while remaining > 0.03:
        category = "展示" if display_phase else "使用"
        candidates = [
            item
            for item in pools[category]
            if item["path"] not in used_in_route
            and history.get("sources", {}).get(item["path"], 0) < MAX_REAL_FOOTAGE_USES
        ]
        if not candidates:
            raise ValueError(f"{category}实拍素材不足：没有未在本片使用且使用次数少于5次的片段")
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
        clip_duration = min(source_duration, remaining)
        if clip_duration <= 0.03:
            raise ValueError(f"实拍素材时长无效：{asset['name']}")
        clip_duration = min(clip_duration, remaining)
        elapsed = duration - remaining
        if (
            display_phase
            and timeline
            and abs(display_target - elapsed)
            <= abs(display_target - (elapsed + clip_duration))
        ):
            display_phase = False
            continue
        timeline.append(
            {
                "role": category,
                "path": asset["path"],
                "name": asset["name"],
                "start": 0.0,
                "duration": round(clip_duration, 3),
            }
        )
        used_in_route.add(asset["path"])
        remaining -= timeline[-1]["duration"]
        if display_phase and duration - remaining >= display_target:
            display_phase = False
        if len(timeline) > 200:
            raise RuntimeError("实拍编排片段数量异常")
    drift = duration - sum(item["duration"] for item in timeline)
    if timeline and abs(drift) > 0.001:
        timeline[-1]["duration"] = round(timeline[-1]["duration"] + drift, 3)
    return timeline


def route_signature(segments: list[dict]) -> str:
    raw = " > ".join(f"{item['role']}:{item['path']}:{item.get('start', 0):.2f}" for item in segments)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def middle_route_signature(audio: Path | str, segments: list[dict]) -> str:
    real_paths = [
        f"{item['role']}:{item['path']}"
        for item in segments
        if item["role"] in {"展示", "使用"}
    ]
    raw = f"audio:{audio}|" + ">".join(real_paths)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_plan(payload: dict, paths: MixerPaths | None = None) -> dict:
    paths = paths or mixer_paths()
    product = str(payload.get("product") or "").strip()
    market = str(payload.get("market") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not product:
        raise ValueError("请选择产品")
    if not market:
        raise ValueError("请选择国家")
    if not model:
        raise ValueError("请选择AI片段模型")

    include_cta = bool(payload.get("include_cta"))
    library = scan_library(paths)
    product_record = next((item for item in library["products"] if item["name"] == product), None)
    if not product_record:
        raise ValueError("未找到产品素材目录")
    market_record = product_record["markets"].get(market)
    model_record = market_record["models"].get(model) if market_record else None
    available_hook_items = [
        item
        for item in (model_record["hooks"] if model_record else [])
        if not item.get("used_count")
    ]
    if not available_hook_items:
        raise ValueError("所选国家没有尚未使用的钩子素材")

    expected_hook_root = delivery_archive_root(paths)
    hook_paths = []
    for item in available_hook_items:
        hook = assert_inside(Path(item["path"]), expected_hook_root)
        if media_market(hook) != market:
            raise ValueError("钩子视频国家与所选国家不一致")
        hook_paths.append(hook)
    if not market_record["audio"]:
        raise ValueError("所选国家没有可用的混剪音频")
    audio_paths = []
    for item in market_record["audio"]:
        audio = assert_inside(Path(item["path"]), paths.audio_root / product)
        if media_market(audio) != market:
            raise ValueError("混剪音频国家与所选国家不一致")
        audio_paths.append(audio)
    cta_paths = []
    if include_cta:
        if not model_record["ctas"]:
            raise ValueError("所选国家没有可用的 CTA 素材")
        expected_cta_root = delivery_archive_root(paths)
        for item in model_record["ctas"]:
            cta = assert_inside(Path(item["path"]), expected_cta_root)
            if media_market(cta) != market:
                raise ValueError("CTA视频国家与所选国家不一致")
            cta_paths.append(cta)

    display_pool = media_pool(product_record["display"])
    usage_pool = media_pool(product_record["usage"])

    count = len(hook_paths)
    use_subtitles = bool(payload.get("use_subtitles"))
    if (
        use_subtitles
        and any(not item.get("subtitle_ready") for item in market_record["audio"])
        and not caption_runtime_ready()
    ):
        raise ValueError("TikTok 卡拉 OK 字幕运行依赖不完整")
    random_deduplication = bool(payload.get("random_deduplication"))
    requested_deduplication = payload.get("deduplication_options") or []
    if isinstance(requested_deduplication, str):
        requested_deduplication = [requested_deduplication]
    deduplication_options = list(
        dict.fromkeys(
            str(item)
            for item in requested_deduplication
            if str(item) in DEDUPLICATION_OPTIONS
        )
    )
    if not random_deduplication and not deduplication_options:
        raise ValueError("请至少选择一项去重处理，或选择随机去重")
    seed = int(payload.get("seed") or random.SystemRandom().randint(100000, 999999999))
    history = load_usage_history(paths)
    known_routes = set(history["routes"])
    known_middle_routes = set(history["middle_routes"])
    hook_record_cache: dict[str, dict] = {}
    audio_record_cache: dict[str, dict] = {}
    cta_record_cache: dict[str, dict] = {}
    planned_audio_counts: dict[str, int] = {}
    planned_cta_counts: dict[str, int] = {}
    planned_real_counts: dict[str, int] = {}
    variants = []
    hook_order = list(hook_paths)
    random.Random(seed).shuffle(hook_order)
    for index, hook in enumerate(hook_order):
        variant_seed = seed + index * 1009
        variant_deduplication = (
            random_deduplication_options(variant_seed)
            if random_deduplication
            else list(deduplication_options)
        )
        if str(hook) not in hook_record_cache:
            hook_record_cache[str(hook)] = effective_video_record(hook)
        hook_record = hook_record_cache[str(hook)]
        audio_rng = random.Random(variant_seed + 31337)
        audio = min(
            audio_paths,
            key=lambda path: (
                history["sources"].get(str(path), 0) + planned_audio_counts.get(str(path), 0),
                audio_rng.random(),
            ),
        )
        planned_audio_counts[str(audio)] = planned_audio_counts.get(str(audio), 0) + 1
        if str(audio) not in audio_record_cache:
            audio_record_cache[str(audio)] = probe_media(audio)
        audio_record = audio_record_cache[str(audio)]
        if audio_record["duration"] <= 0:
            raise ValueError(f"混剪音频时长无效：{audio.name}")
        cta = None
        cta_record = None
        if include_cta:
            cta_rng = random.Random(variant_seed + 62749)
            cta = min(
                cta_paths,
                key=lambda path: (
                    history["sources"].get(str(path), 0) + planned_cta_counts.get(str(path), 0),
                    cta_rng.random(),
                ),
            )
            planned_cta_counts[str(cta)] = planned_cta_counts.get(str(cta), 0) + 1
            if str(cta) not in cta_record_cache:
                cta_record_cache[str(cta)] = effective_video_record(cta)
            cta_record = cta_record_cache[str(cta)]
        attempt_sources = dict(history["sources"])
        for path, planned_count in planned_real_counts.items():
            attempt_sources[path] = attempt_sources.get(path, 0) + planned_count
        attempt_history = {**history, "sources": attempt_sources}
        accepted = False
        for attempt in range(50):
            candidate_seed = variant_seed + attempt * 7919
            middle = choose_middle_timeline(
                display_pool,
                usage_pool,
                audio_record["duration"],
                seed=candidate_seed,
                history=attempt_history,
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
            ]
            if cta and cta_record:
                full_segments.append(
                    {
                        "role": "AI CTA",
                        "path": str(cta),
                        "name": cta.name,
                        "start": 0.0,
                        "duration": cta_record["effective_duration"],
                        "preserve_audio": True,
                        "technical_tail_trimmed": cta_record["technical_tail_trimmed"],
                    }
                )
            signature = route_signature(full_segments)
            middle_signature = middle_route_signature(audio, middle)
            if signature not in known_routes and middle_signature not in known_middle_routes:
                variant_seed = candidate_seed
                accepted = True
                break
        if not accepted:
            raise ValueError("无法生成新的“混剪音频＋实拍素材顺序”组合，请补充实拍素材或混剪音频")
        known_routes.add(signature)
        known_middle_routes.add(middle_signature)
        for segment in middle:
            path = segment["path"]
            planned_real_counts[path] = planned_real_counts.get(path, 0) + 1
        variants.append(
            {
                "index": index + 1,
                "seed": variant_seed,
                "segments": full_segments,
                "middle_audio": str(audio),
                "middle_duration": audio_record["duration"],
                "deduplication_options": variant_deduplication,
                "total_duration": round(
                    hook_record["effective_duration"]
                    + audio_record["duration"]
                    + (cta_record["effective_duration"] if cta_record else 0),
                    3,
                ),
                "route_signature": signature,
                "middle_route_signature": middle_signature,
            }
        )

    created_at = dt.datetime.now().isoformat(timespec="seconds")
    plan_id = (
        f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{safe_name(product, 60)}_{safe_name(market, 10)}_{seed}"
    )
    plan = {
        "version": 1,
        "plan_id": plan_id,
        "created_at": created_at,
        "product": product,
        "market": market,
        "model": model,
        "settings": {
            "count": count,
            "random_deduplication": random_deduplication,
            "deduplication_options": deduplication_options,
            "audio_deduplication": False,
            "seed": seed,
            "canvas": "1080x1920",
            "fps": 30,
            "middle_audio_preserved": True,
            "include_cta": include_cta,
            "use_subtitles": use_subtitles,
        },
        "inputs": {
            "hook_count": len(hook_paths),
            "hook_pool": [relative_record(path, delivery_archive_root(paths)) for path in hook_paths],
            "audio_count": len(audio_paths),
            "audio_pool": [audio_library_record(path, paths.audio_root) for path in audio_paths],
            "subtitle_count": market_record["subtitle_count"],
            "missing_subtitle_count": market_record["missing_subtitle_count"],
            "cta_count": len(model_record["ctas"]),
            "cta_pool": model_record["ctas"],
            "include_cta": include_cta,
            "display_count": len(display_pool),
            "usage_count": len(usage_pool),
        },
        "variants": variants,
    }
    plan_path = paths.work_root / product / "plans" / f"{plan_id}.json"
    write_json(plan_path, plan)
    plan["plan_path"] = str(plan_path)
    return plan


def random_deduplication_options(seed: int) -> list[str]:
    rng = random.Random(seed)
    subtle = ["transform", "color", "tone", "detail", "encoding"]
    visible = ["frame_drop", "mirror", "speed", "border", "effect"]
    selected = rng.sample(subtle, rng.randint(2, 4))
    selected.extend(rng.sample(visible, rng.randint(1, 2)))
    return [item for item in DEDUPLICATION_OPTIONS if item in selected]


def normalize_deduplication_options(value) -> list[str]:
    if isinstance(value, str) and value in {"standard", "enhanced"}:
        return ["transform", "color"]
    if not isinstance(value, list):
        return []
    return [item for item in DEDUPLICATION_OPTIONS if item in value]


def deduplication_filter(
    seed: int,
    options: list[str] | str,
    *,
    duration: float = 10.0,
) -> str:
    selected = set(normalize_deduplication_options(options))
    rng = random.Random(seed)
    frame_count = max(2, int(round(max(0.05, duration) * 30)))
    zoom = rng.uniform(1.006, 1.025) if "transform" in selected else 1.0
    width = int(math.ceil(1080 * zoom / 2) * 2)
    height = int(math.ceil(1920 * zoom / 2) * 2)
    max_x = max(0, width - 1080)
    max_y = max(0, height - 1920)
    x = rng.randint(0, max_x) if max_x else 0
    y = rng.randint(0, max_y) if max_y else 0
    filters = [
        "scale=1080:1920:force_original_aspect_ratio=increase",
        f"crop=1080:1920,scale={width}:{height},crop=1080:1920:{x}:{y}"
    ]
    if "color" in selected:
        filters.append(
            "eq="
            f"saturation={rng.uniform(0.95, 1.05):.4f}:"
            f"contrast={rng.uniform(0.95, 1.05):.4f}:"
            f"brightness={rng.uniform(-0.03, 0.03):.4f}"
        )
    if "tone" in selected:
        filters.append(
            "colorbalance="
            f"rs={rng.uniform(-0.025, 0.025):.4f}:"
            f"bs={rng.uniform(-0.025, 0.025):.4f}"
        )
        filters.append(f"eq=gamma={rng.uniform(0.97, 1.03):.4f}")
    if "detail" in selected:
        filters.extend(
            [
                f"hqdn3d={rng.uniform(0.5, 1.2):.3f}:"
                f"{rng.uniform(0.4, 1.0):.3f}:"
                f"{rng.uniform(1.5, 3.0):.3f}:"
                f"{rng.uniform(1.0, 2.4):.3f}",
                f"unsharp=5:5:{rng.uniform(0.12, 0.35):.3f}:3:3:0",
            ]
        )
    filters.append("tpad=stop_mode=clone:stop_duration=0.5")
    if "frame_drop" in selected:
        every = rng.randint(10, 18)
        filters.append(f"select='not(eq(mod(n\\,{every})\\,0))'")
    if "mirror" in selected:
        filters.append("hflip")
    if "speed" in selected:
        speed = rng.uniform(0.985, 1.015)
        filters.append(f"setpts=PTS/{speed:.5f}")
    if "border" in selected:
        filters.append("drawbox=x=4:y=4:w=iw-8:h=ih-8:color=white@0.16:t=3")
    if "effect" in selected:
        if rng.random() < 0.5:
            filters.append(f"vignette=PI/{rng.uniform(5.5, 7.0):.3f}")
        else:
            filters.append(f"noise=alls={rng.uniform(1.5, 3.0):.3f}:allf=t")
    filters.extend(
        [
            "fps=30",
            f"trim=end_frame={frame_count}",
            "setpts=PTS-STARTPTS",
            "setsar=1",
            "format=yuv420p",
        ]
    )
    return ",".join(filters)


def render_video_segment(segment: dict, output: Path, seed: int, options: list[str] | str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    selected = normalize_deduplication_options(options)
    encoding_rng = random.Random(seed + 9983)
    crf = str(encoding_rng.randint(19, 23) if "encoding" in selected else 21)
    gop = str(encoding_rng.choice([48, 60, 72, 90]) if "encoding" in selected else 60)
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
            deduplication_filter(
                seed,
                selected,
                duration=float(segment["duration"]),
            ),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            crf,
            "-g",
            gop,
            "-keyint_min",
            gop,
            "-r",
            "30",
            "-fps_mode",
            "cfr",
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


def build_hyperframes_html(total_duration: float) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <style>
    html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#000}}
    #main{{position:relative;width:1080px;height:1920px;overflow:hidden;background:#000}}
    video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
  </style>
</head>
<body>
  <div id="main" data-composition-id="main" data-start="0" data-width="1080" data-height="1920" data-duration="{total_duration:.3f}">
    <video id="visual-track" class="clip" src="media/visual.mp4" data-start="0" data-duration="{total_duration:.3f}" data-track-index="0" muted playsinline></video>
    <audio id="audio-track" class="clip" src="media/audio.m4a" data-start="0" data-duration="{total_duration:.3f}" data-track-index="1" data-volume="1"></audio>
  </div>
  <script src="vendor/gsap.min.js"></script>
  <script>
    window.__timelines = window.__timelines || {{}};
    window.__timelines["main"] = gsap.timeline({{ paused: true }});
  </script>
</body>
</html>
"""


def prepare_hyperframes_project(
    project_dir: Path,
    visual: Path,
    audio: Path,
    total_duration: float,
) -> None:
    media_dir = project_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    vendor_dir = project_dir / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(visual, media_dir / "visual.mp4")
    shutil.copy2(audio, media_dir / "audio.m4a")
    shutil.copy2(GSAP_SOURCE, vendor_dir / "gsap.min.js")
    (project_dir / "index.html").write_text(
        build_hyperframes_html(total_duration),
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
    audio_path = variant.get("middle_audio")
    if audio_path:
        history["sources"][audio_path] = history["sources"].get(audio_path, 0) + 1
    for segment in variant["segments"]:
        if segment["role"] in {"AI钩子", "展示", "使用", "AI CTA"}:
            key = segment["path"]
            history["sources"][key] = history["sources"].get(key, 0) + 1
            if segment["role"] in {"AI钩子", "AI CTA"}:
                update_delivery_marker(Path(key), used_output=output)
    history["routes"].append(variant["route_signature"])
    history["routes"] = history["routes"][-1000:]
    middle_signature = variant.get("middle_route_signature")
    if middle_signature:
        history["middle_routes"].append(middle_signature)
        history["middle_routes"] = history["middle_routes"][-5000:]
    history["outputs"].append(
        {
            "output": str(output),
            "route_signature": variant["route_signature"],
            "middle_route_signature": middle_signature,
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
        legacy_deduplication = plan["settings"].get(
            "deduplication",
            plan["settings"].get("originality", "standard"),
        )
        options = variant.get(
            "deduplication_options",
            plan["settings"].get("deduplication_options", legacy_deduplication),
        )
        video_parts = []
        for position, segment in enumerate(variant["segments"], start=1):
            log(f"变体 {index}：处理片段 {position}/{len(variant['segments'])} · {segment['role']}")
            output = normalized_dir / f"{position:03d}.mp4"
            render_video_segment(segment, output, variant["seed"] + position * 37, options)
            video_parts.append(output)
        visual = work_dir / "visual.mp4"
        concat_video(video_parts, visual)

        hook = variant["segments"][0]
        cta = next((segment for segment in variant["segments"] if segment["role"] == "AI CTA"), None)
        hook_audio = work_dir / "hook.m4a"
        middle_audio = work_dir / "middle.m4a"
        render_audio_piece(Path(hook["path"]), float(hook["duration"]), hook_audio)
        render_audio_piece(Path(variant["middle_audio"]), float(variant["middle_duration"]), middle_audio)
        audio_pieces = [hook_audio, middle_audio]
        if cta:
            cta_audio = work_dir / "cta.m4a"
            render_audio_piece(Path(cta["path"]), float(cta["duration"]), cta_audio)
            audio_pieces.append(cta_audio)
        audio = work_dir / "audio.m4a"
        concat_audio(audio_pieces, audio)

        project_dir = work_dir / "hyperframes"
        prepare_hyperframes_project(
            project_dir,
            visual,
            audio,
            float(variant["total_duration"]),
        )
        output_name = (
            f"AI实拍混剪-{safe_name(plan['product'], 70)}-{safe_name(plan['market'], 10)}-"
            f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}-V{index:02d}.mp4"
        )
        output_path = paths.output_root / plan["product"] / output_name
        use_subtitles = bool(plan["settings"].get("use_subtitles"))
        render_path = work_dir / "uncaptioned.mp4" if use_subtitles else output_path
        log(f"变体 {index}：HyperFrames渲染成片")
        run_hyperframes(project_dir, render_path)
        if use_subtitles:
            middle_audio_path = Path(variant["middle_audio"])
            sidecars = audio_subtitle_paths(middle_audio_path)
            if valid_ass_subtitles(sidecars["ass"]):
                log(f"变体 {index}：复用混剪音频同名本地字幕")
            else:
                log(f"变体 {index}：混剪音频缺少字幕，本地 Whisper 生成并保存")
            sidecars = ensure_audio_subtitles(
                middle_audio_path,
                float(variant["middle_duration"]),
                plan["market"],
                work_dir,
            )
            shifted_ass = work_dir / "captions" / "middle-offset.ass"
            shift_ass_subtitles(
                sidecars["ass"],
                shifted_ass,
                offset=float(hook["duration"]),
                duration=float(variant["middle_duration"]),
            )
            log(f"变体 {index}：字幕偏移到钩子之后并烧录，仅覆盖混剪中段")
            burn_ass_subtitles(render_path, shifted_ass, output_path)
        verified = validate_finished_video(output_path)
        metadata = {
            "agent": "Hybrid-Video-Mixer",
            "plan_id": plan["plan_id"],
            "product": plan["product"],
            "market": plan["market"],
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
