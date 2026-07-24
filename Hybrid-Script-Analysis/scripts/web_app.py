#!/usr/bin/env python3
import cgi
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT", str(Path.home() / "Documents" / "Obsidian Vault"))
).expanduser()
WEB_ROOT = SKILL_ROOT / "web"
CONFIG_DIR = SKILL_ROOT / "config"
INPUTS_DIR = SKILL_ROOT / "inputs"
OUTPUTS_DIR = SKILL_ROOT / "outputs"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
SECRETS_PATH = CONFIG_DIR / "settings.local.json"
PATHS_PATH = CONFIG_DIR / "paths.local.json"
ANALYZE_SCRIPT = SKILL_ROOT / "scripts" / "analyze_video.py"
DEFAULT_VIDEO_SCAN_DIR = VAULT_ROOT / "wiki" / "视频" / "AI实拍混剪" / "01参考视频"
DEFAULT_SCRIPT_CHECK_DIR = VAULT_ROOT / "wiki" / "视频" / "AI实拍混剪" / "02解析脚本"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
HYBRID_MATERIAL_TYPES = {"混剪-钩子", "混剪-CTA"}
COUNTRY_MARKERS = [
    ("MX", ("mexico", "méxico", "tiktokshopmx", "tiktokshopmexico", "tik tok shop mexico", "墨西哥")),
    ("MY", ("tiktokshopmalaysia", "malaysia", "malaysian", "bahasa melayu", "malay", "penang", "syampu", "pewarna", "uban", "kwn", "马来西亚", "马来语")),
    ("DE", ("germany", "german", "deutschland", "deutsch", "tiktokshopdeutschland", "德国", "德语")),
    ("PH", ("philippines", "philippine", "filipino", "tagalog", "菲律宾", "他加禄")),
    ("TH", ("thailand", "thai", "泰国", "泰语")),
    ("VN", ("vietnam", "vietnamese", "越南", "越南语")),
    ("ID", ("tiktokshopindonesia", "indonesia", "indonesian", "bahasa indonesia", "ketombe", "cocok", "perawatanrambut", "印尼", "印度尼西亚")),
    ("SG", ("singapore", "singaporean", "新加坡")),
    ("BD", ("bangladesh", "bangladeshi", "bengali", "bangla", "孟加拉")),
    ("PK", ("pakistan", "pakistani", "urdu", "巴基斯坦", "乌尔都")),
    ("US", ("united states", "usa", "u.s.", "american english", "美国")),
    ("GB", ("united kingdom", "uk", "british english", "英国")),
    ("ES", ("spain", "spanish", "español", "西班牙")),
]
COUNTRY_CODE_RE = re.compile(
    r"^\s*<!--\s*(?:COUNTRY_CODE|MARKET_COUNTRY)\s*:\s*([A-Z]{2,3}|UNK)\s*-->\s*$",
    re.IGNORECASE | re.MULTILINE,
)

CONFIG_FILES = {
    "prompt": CONFIG_DIR / "video_teardown_prompt.md",
}

JOBS = {}
JOBS_LOCK = threading.Lock()
SCANS = {}
LATEST_SCAN_ID = ""
LATEST_JOB_ID = ""


def ensure_dirs():
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if path.name in {"settings.local.json", "paths.local.json"}:
        path.chmod(0o600)


def local_paths():
    data = read_json(PATHS_PATH)
    video_dir = Path(
        os.path.expandvars(
            str(os.environ.get("HYBRID_VIDEO_TEARDOWN_INPUT_ROOT") or data.get("video_dir") or DEFAULT_VIDEO_SCAN_DIR)
        )
    ).expanduser()
    script_dir = Path(
        os.path.expandvars(
            str(os.environ.get("HYBRID_VIDEO_TEARDOWN_OUTPUT_ROOT") or data.get("script_dir") or DEFAULT_SCRIPT_CHECK_DIR)
        )
    ).expanduser()
    if not video_dir.is_absolute():
        video_dir = SKILL_ROOT / video_dir
    if not script_dir.is_absolute():
        script_dir = SKILL_ROOT / script_dir
    return video_dir.resolve(), script_dir.resolve()


def rel_path(path):
    return str(path.resolve().relative_to(SKILL_ROOT))


def path_in_skill(path):
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(SKILL_ROOT)
    except ValueError:
        return None
    return resolved


def path_in_web(path):
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(WEB_ROOT)
    except ValueError:
        return None
    return resolved


def resolve_input_path(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少输入视频路径")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = SKILL_ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise ValueError(f"输入路径不存在: {candidate}")
    return candidate


def copy_file_into_inputs(path):
    target = INPUTS_DIR / f"{now_stamp()}_{safe_filename(path.name)}"
    if target.resolve() == path.resolve():
        return target
    shutil.copy2(path, target)
    return target


def copy_directory_videos_into_inputs(path):
    run_dir = INPUTS_DIR / f"{now_stamp()}_{safe_filename(path.name)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for source in sorted(path.rglob("*")):
        if source.is_file() and source.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            relative_name = "__".join(source.relative_to(path).parts)
            shutil.copy2(source, run_dir / safe_filename(relative_name))
            count += 1
    if count == 0:
        run_dir.rmdir()
        raise ValueError(f"文件夹中没有 MP4/MOV/M4V 视频: {path}")
    return run_dir


def import_input_to_skill(value):
    source = resolve_input_path(value)
    if path_in_skill(source):
        return source
    ensure_dirs()
    if source.is_file():
        if source.suffix.lower() not in {".mp4", ".mov", ".m4v"}:
            raise ValueError("只支持 MP4/MOV/M4V 视频文件")
        return copy_file_into_inputs(source)
    if source.is_dir():
        return copy_directory_videos_into_inputs(source)
    raise ValueError(f"输入路径不是文件或文件夹: {source}")


def resolve_skill_file(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少文件路径")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = SKILL_ROOT / candidate
    resolved = candidate.resolve()
    allowed = path_in_skill(resolved)
    if not allowed:
        try:
            _, script_dir = local_paths()
            resolved.relative_to(script_dir)
            allowed = resolved
        except ValueError:
            allowed = None
    if not allowed:
        raise ValueError("只能访问智能体文件夹或脚本目录内的文件")
    if not resolved.exists():
        raise ValueError(f"文件不存在: {resolved}")
    return resolved


def resolve_skill_path_for_open(value):
    text = str(value or "outputs").strip() or "outputs"
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = SKILL_ROOT / candidate
    resolved = candidate.resolve()
    allowed = path_in_skill(resolved)
    if not allowed:
        try:
            _, script_dir = local_paths()
            resolved.relative_to(script_dir)
            allowed = resolved
        except ValueError:
            allowed = None
    if not allowed:
        raise ValueError("只能打开智能体文件夹或脚本目录内的路径")
    if not resolved.exists():
        raise ValueError(f"路径不存在: {resolved}")
    return resolved


def safe_filename(value):
    name = Path(value or "video.mp4").name
    cleaned = "".join(ch if ch.isalnum() or ch in (".", "-", "_") else "_" for ch in name)
    cleaned = cleaned.strip("._") or "video.mp4"
    return cleaned[:160]


def resolve_existing_path(value, default_path, label):
    text = str(value or "").strip()
    path = Path(text).expanduser() if text else default_path
    path = path.resolve()
    if not path.exists():
        raise ValueError(f"{label}不存在: {path}")
    if not path.is_dir():
        raise ValueError(f"{label}必须是文件夹: {path}")
    return path


def extract_video_id(value):
    text = Path(str(value)).stem
    matches = re.findall(r"\d{6,}", text)
    if not matches:
        return ""
    long_matches = [item for item in matches if len(item) >= 10]
    return (long_matches or matches)[-1]


def extract_country_code(text):
    raw = str(text or "")
    tag_match = COUNTRY_CODE_RE.search(raw)
    if tag_match:
        return normalize_country_code(tag_match.group(1))
    normalized = raw.lower()
    for code, markers in COUNTRY_MARKERS:
        if any(country_marker_matches(normalized, marker) for marker in markers):
            return code
    country_line = re.search(r"(?:market|country|国家|市场)\s*[/：:|-]?\s*([^\n\r]+)", normalized)
    if country_line:
        line = country_line.group(1)
        for code, markers in COUNTRY_MARKERS:
            if any(country_marker_matches(line, marker) for marker in markers):
                return code
    return "UNK"


def country_marker_matches(text, marker):
    marker_text = str(marker or "").lower()
    if re.fullmatch(r"[a-z0-9]{1,3}", marker_text):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(marker_text)}(?![a-z0-9])", text))
    return marker_text in text


def normalize_country_code(value):
    code = re.sub(r"[^A-Z]", "", str(value or "").upper())
    return code if 2 <= len(code) <= 3 else "UNK"


def strip_country_code_tag(text):
    return COUNTRY_CODE_RE.sub("", str(text or ""), count=1).lstrip("\r\n")


def split_country_prefix(filename):
    match = re.match(r"^([A-Z]{2,3}|UNK)-(.+)$", str(filename or ""))
    if not match:
        return "", str(filename or "")
    return match.group(1), match.group(2)


def infer_script_country(file_path):
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")[:8000]
    except OSError:
        content = ""
    prefix, stem_without_prefix = split_country_prefix(file_path.name)
    country_code = extract_country_code(f"{stem_without_prefix}\n{content}")
    suggested_name = file_path.name
    needs_update = bool(country_code and country_code != "UNK" and country_code != prefix)
    if needs_update:
        suggested_name = f"{country_code}-{stem_without_prefix}"
    return {
        "current_country_code": prefix or "NONE",
        "country_code": country_code,
        "suggested_name": suggested_name,
        "needs_country_prefix_update": needs_update,
    }


def relative_or_absolute(path, base):
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def hybrid_classification(path, base):
    try:
        relative = path.relative_to(base)
    except ValueError:
        return {"material_type": "", "product": "", "relative_dir": "", "group_label": "未分类"}
    parents = relative.parent.parts
    material_type = parents[0] if parents else ""
    product = parents[1] if len(parents) > 1 else ""
    if material_type not in HYBRID_MATERIAL_TYPES or not product:
        return {"material_type": "", "product": "", "relative_dir": "", "group_label": "未分类"}
    relative_dir = str(Path(material_type) / product)
    return {
        "material_type": material_type,
        "product": product,
        "relative_dir": relative_dir,
        "group_label": f"{material_type} / {product}",
    }


def product_name_for(path, base):
    return hybrid_classification(path, base)["product"]


def collect_script_ids(script_dir):
    scoped_ids = {}
    for path in sorted(script_dir.rglob("*.md")):
        video_id = extract_video_id(path.name)
        if video_id and video_id.lower() != "unknown":
            classification = hybrid_classification(path, script_dir)
            relative_dir = classification["relative_dir"]
            if relative_dir:
                scoped_ids.setdefault((relative_dir, video_id), path)
    return scoped_ids


def script_target_path(script_dir, item):
    relative_dir = str(item.get("relative_dir") or "").strip()
    target_dir = script_dir / relative_dir if relative_dir else script_dir
    source_name = Path(str(item.get("path") or item.get("name") or "video.mp4")).with_suffix(".md").name
    return target_dir / source_name


def country_script_target_path(script_dir, item, country_code):
    relative_dir = str(item.get("relative_dir") or "").strip()
    target_dir = script_dir / relative_dir if relative_dir else script_dir
    source_name = Path(str(item.get("path") or item.get("name") or "video.mp4")).with_suffix(".md").name
    prefix = re.sub(r"[^A-Z0-9]", "", str(country_code or "UNK").upper()) or "UNK"
    return target_dir / f"{prefix}-{source_name}"


def scan_teardown_queue(video_dir, script_dir):
    script_ids = collect_script_ids(script_dir)
    videos = []
    pending = []
    skipped = []
    missing_id = []
    for path in sorted(video_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        stat = path.stat()
        video_id = extract_video_id(path.name)
        classification = hybrid_classification(path, video_dir)
        product = classification["product"]
        duplicate_path = None
        if video_id and classification["relative_dir"]:
            duplicate_path = script_ids.get((classification["relative_dir"], video_id))
        item = {
            "path": str(path),
            "name": path.name,
            "relative_path": relative_or_absolute(path, video_dir),
            "product": product,
            **classification,
            "video_id": video_id,
            "target_path": str(
                country_script_target_path(
                    script_dir,
                    {"path": str(path), "product": product, **classification},
                    "UNK",
                )
            ),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "duplicate": bool(duplicate_path),
            "duplicate_script": str(duplicate_path) if duplicate_path else "",
        }
        videos.append(item)
        if not classification["relative_dir"]:
            item["classification_error"] = "视频必须位于 混剪-钩子|混剪-CTA/<产品名>/ 目录下"
            missing_id.append(item)
        elif duplicate_path:
            skipped.append(item)
        elif video_id:
            pending.append(item)
        else:
            missing_id.append(item)
    scan_id = uuid.uuid4().hex[:12]
    scan = {
        "id": scan_id,
        "video_dir": str(video_dir),
        "script_dir": str(script_dir),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total": len(videos),
            "pending": len(pending),
            "skipped": len(skipped),
            "missing_id": len(missing_id),
            "script_ids": len(script_ids),
        },
        "pending": pending,
        "skipped": skipped,
        "missing_id": missing_id,
    }
    SCANS[scan_id] = scan
    return scan


def file_info(path):
    if not path.exists():
        return {"exists": False, "path": rel_path(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": rel_path(path),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def list_uploads():
    ensure_dirs()
    items = []
    for path in sorted(INPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            info = file_info(path)
            info["name"] = path.name
            items.append(info)
    return items[:80]


def read_summary(path):
    markdown_count = len([item for item in path.glob("*.md") if item.is_file()])
    return {"markdown_count": markdown_count} if markdown_count else {}


def list_outputs():
    ensure_dirs()
    runs = []
    for path in sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        files = []
        for file_path in sorted(path.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() == ".md":
                info = file_info(file_path)
                info["name"] = file_path.name
                files.append(info)
        runs.append(
            {
                "name": path.name,
                "path": rel_path(path),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "summary": read_summary(path),
                "files": files,
            }
        )
    return runs[:40]


def list_scripts_by_product(script_dir=None):
    if script_dir is None:
        _, script_dir = local_paths()
    script_dir = script_dir.resolve()
    if not script_dir.exists():
        return []
    groups = {}
    for file_path in sorted(script_dir.rglob("*.md")):
        if not file_path.is_file():
            continue
        classification = hybrid_classification(file_path, script_dir)
        product = classification["group_label"]
        group = groups.setdefault(
            product,
            {
                "product": product,
                "path": str(script_dir / classification["relative_dir"]) if classification["relative_dir"] else str(script_dir),
                "count": 0,
                "files": [],
            },
        )
        stat = file_path.stat()
        country_meta = infer_script_country(file_path)
        group["count"] += 1
        group["files"].append(
            {
                "name": file_path.name,
                "path": str(file_path),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size": stat.st_size,
                **country_meta,
            }
        )
    return sorted(groups.values(), key=lambda item: (-item["count"], item["product"]))


def cleanup_non_markdown_outputs(output_dir):
    for file_path in output_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() != ".md":
            file_path.unlink(missing_ok=True)


def masked_settings():
    settings = read_json(SETTINGS_PATH)
    api_key = str(read_json(SECRETS_PATH).get("api_key") or "")
    return {
        "base_url": settings.get("base_url", ""),
        "model": settings.get("model", ""),
        "max_output_tokens": settings.get("max_output_tokens", ""),
        "timeout_seconds": settings.get("timeout_seconds", ""),
        "temperature": settings.get("temperature", ""),
        "output_dir": settings.get("output_dir", "outputs"),
        "api_key_set": bool(api_key),
        "api_key_hint": f"已设置，尾号 {api_key[-4:]}" if api_key else "未设置",
    }


def update_settings(payload):
    settings = read_json(SETTINGS_PATH)
    allowed_text = {"base_url", "model", "output_dir", "prompt_file"}
    allowed_int = {"max_output_tokens", "timeout_seconds"}
    allowed_float = {"temperature"}
    for key in allowed_text:
        if key in payload:
            settings[key] = str(payload.get(key) or "").strip()
    for key in allowed_int:
        if key in payload and str(payload.get(key)).strip():
            settings[key] = int(payload[key])
    for key in allowed_float:
        if key in payload and str(payload.get(key)).strip():
            settings[key] = float(payload[key])
    settings.pop("api_key", None)
    write_json(SETTINGS_PATH, settings)

    api_key = str(payload.get("api_key") or "").strip()
    if api_key:
        secrets = read_json(SECRETS_PATH)
        secrets["api_key"] = api_key
        write_json(SECRETS_PATH, secrets)


def set_job(job_id, **values):
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(values)
        return dict(job)


def append_job_log(job_id, line):
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        logs = job.setdefault("logs", [])
        logs.append(line)
        if len(logs) > 1200:
            del logs[: len(logs) - 1200]


def get_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def get_active_job():
    with JOBS_LOCK:
        latest = None
        for job in JOBS.values():
            if job.get("status") in {"queued", "running"}:
                latest = dict(job)
        return latest or {}


def summarize_markdown_outputs(output_dir):
    cleanup_non_markdown_outputs(output_dir)
    markdown_outputs = sorted(output_dir.glob("*.md"), key=lambda path: path.stat().st_mtime)
    return [rel_path(path) for path in markdown_outputs]


def run_job(job_id, input_path, output_dir):
    cmd = [sys.executable, str(ANALYZE_SCRIPT), str(input_path), "--output-dir", str(output_dir)]
    set_job(
        job_id,
        status="running",
        command=[sys.executable, rel_path(ANALYZE_SCRIPT), str(input_path), "--output-dir", rel_path(output_dir)],
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(SKILL_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        set_job(job_id, pid=process.pid)
        assert process.stdout is not None
        for line in process.stdout:
            append_job_log(job_id, line.rstrip("\n"))
        return_code = process.wait()
        set_job(
            job_id,
            status="completed" if return_code == 0 else "failed",
            return_code=return_code,
            ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            output_dir=rel_path(output_dir),
            markdown_outputs=summarize_markdown_outputs(output_dir),
        )
    except Exception as exc:
        append_job_log(job_id, f"Web 任务失败: {exc}")
        set_job(
            job_id,
            status="failed",
            error=str(exc),
            ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            output_dir=rel_path(output_dir),
        )


def run_queue_job(job_id, items, output_dir, script_dir):
    set_job(
        job_id,
        status="running",
        total=len(items),
        completed=0,
        failed=0,
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        output_dir=rel_path(output_dir),
        items=[
            {
                "path": item["path"],
                "name": item["name"],
                "product": item.get("product", ""),
                "video_id": item.get("video_id", ""),
                "relative_path": item.get("relative_path", ""),
                "target_path": item.get("target_path", ""),
                "status": "queued",
            }
            for item in items
        ],
    )
    failures = 0
    completed = 0
    final_outputs = []
    try:
        for index, item in enumerate(items, start=1):
            video_path = Path(item["path"])
            item_output_dir = output_dir / f"{index:03d}_{safe_filename(video_path.stem)}"
            item_output_dir.mkdir(parents=True, exist_ok=True)
            target_path = Path(item.get("target_path") or script_target_path(script_dir, item))
            append_job_log(job_id, f"[{index}/{len(items)}] 开始拆解: {item.get('relative_path') or video_path.name}")
            with JOBS_LOCK:
                job = JOBS.setdefault(job_id, {})
                queue_items = job.setdefault("items", [])
                if index - 1 < len(queue_items):
                    queue_items[index - 1]["status"] = "running"

            cmd = [sys.executable, str(ANALYZE_SCRIPT), str(video_path), "--output-dir", str(item_output_dir)]
            process = subprocess.Popen(
                cmd,
                cwd=str(SKILL_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                append_job_log(job_id, line.rstrip("\n"))
            return_code = process.wait()
            if return_code == 0:
                markdown_outputs = sorted(item_output_dir.glob("*.md"), key=lambda path: path.stat().st_mtime)
                if not markdown_outputs:
                    raise RuntimeError(f"拆解完成但没有生成 Markdown: {video_path.name}")
                generated_path = markdown_outputs[-1]
                generated_content = generated_path.read_text(encoding="utf-8", errors="ignore")
                country_code = extract_country_code(f"{generated_content}\n{video_path.name}")
                generated_path.write_text(strip_country_code_tag(generated_content), encoding="utf-8")
                target_path = country_script_target_path(script_dir, item, country_code)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if target_path.exists():
                    target_path.unlink()
                shutil.move(str(generated_path), str(target_path))
                final_outputs.append(str(target_path))
                completed += 1
                item_status = "completed"
                append_job_log(job_id, f"[{index}/{len(items)}] 完成: {video_path.name}")
                append_job_log(job_id, f"[{index}/{len(items)}] 国家代码: {country_code}")
                append_job_log(job_id, f"[{index}/{len(items)}] 已保存到: {target_path}")
            else:
                failures += 1
                item_status = "failed"
                append_job_log(job_id, f"[{index}/{len(items)}] 失败: {video_path.name}")

            with JOBS_LOCK:
                job = JOBS.setdefault(job_id, {})
                queue_items = job.setdefault("items", [])
                if index - 1 < len(queue_items):
                    queue_items[index - 1]["status"] = item_status
                    if item_status == "completed":
                        queue_items[index - 1]["target_path"] = str(target_path)
                job.update(
                    completed=completed,
                    failed=failures,
                    markdown_outputs=final_outputs,
                    final_outputs=final_outputs,
                )

        set_job(
            job_id,
            status="completed" if failures == 0 else "failed",
            return_code=0 if failures == 0 else 1,
            ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            completed=completed,
            failed=failures,
            markdown_outputs=final_outputs,
            final_outputs=final_outputs,
        )
    except Exception as exc:
        append_job_log(job_id, f"队列任务失败: {exc}")
        set_job(
            job_id,
            status="failed",
            error=str(exc),
            ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            completed=completed,
            failed=failures + 1,
            markdown_outputs=final_outputs,
            final_outputs=final_outputs,
        )


class AgentHandler(SimpleHTTPRequestHandler):
    server_version = "ScriptAnalysis/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200, content_type="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/status":
                default_video_dir, default_script_dir = local_paths()
                self.send_json(
                    {
                        "skill_root": str(SKILL_ROOT),
                        "settings": masked_settings(),
                        "files": {
                            "prompt": file_info(CONFIG_FILES["prompt"]),
                            "settings": file_info(SETTINGS_PATH),
                        },
                        "uploads": list_uploads(),
                        "scripts_by_product": list_scripts_by_product(),
                        "queue_defaults": {
                            "video_dir": str(default_video_dir),
                            "script_dir": str(default_script_dir),
                        },
                        "latest_scan": SCANS.get(LATEST_SCAN_ID, {}),
                        "active_job": get_active_job(),
                    }
                )
                return
            if path.startswith("/api/scans/"):
                scan_id = path.rsplit("/", 1)[-1]
                scan = SCANS.get(scan_id)
                if not scan:
                    self.send_json({"error": "扫描结果不存在"}, 404)
                    return
                self.send_json(scan)
                return
            if path == "/api/config-file":
                name = (query.get("name") or [""])[0]
                target = CONFIG_FILES.get(name)
                if not target:
                    self.send_json({"error": "未知配置文件"}, 404)
                    return
                self.send_json({"name": name, "path": rel_path(target), "content": target.read_text(encoding="utf-8")})
                return
            if path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = get_job(job_id)
                if not job:
                    self.send_json({"error": "任务不存在"}, 404)
                    return
                job["scripts_by_product"] = list_scripts_by_product()
                self.send_json(job)
                return
            if path == "/api/file":
                target = resolve_skill_file((query.get("path") or [""])[0])
                if target == SECRETS_PATH:
                    self.send_json({"error": "私有配置文件不允许预览"}, 403)
                    return
                content_type = mimetypes.guess_type(str(target))[0] or "text/plain"
                self.send_text(target.read_text(encoding="utf-8", errors="ignore"), content_type=f"{content_type}; charset=utf-8")
                return
            self.serve_static(path)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self):
        global LATEST_SCAN_ID, LATEST_JOB_ID
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/settings":
                update_settings(self.read_json_body())
                self.send_json({"ok": True, "settings": masked_settings()})
                return
            if path == "/api/config-file":
                payload = self.read_json_body()
                name = str(payload.get("name") or "")
                target = CONFIG_FILES.get(name)
                if not target:
                    self.send_json({"error": "未知配置文件"}, 404)
                    return
                target.write_text(str(payload.get("content") or ""), encoding="utf-8")
                self.send_json({"ok": True, "file": file_info(target)})
                return
            if path == "/api/upload":
                self.handle_upload()
                return
            if path == "/api/scan-queue":
                payload = self.read_json_body()
                default_video_dir, default_script_dir = local_paths()
                video_dir = resolve_existing_path(payload.get("video_dir"), default_video_dir, "视频目录")
                script_dir = resolve_existing_path(payload.get("script_dir"), default_script_dir, "脚本目录")
                scan = scan_teardown_queue(video_dir, script_dir)
                LATEST_SCAN_ID = scan["id"]
                self.send_json(scan)
                return
            if path == "/api/run":
                payload = self.read_json_body()
                input_path = import_input_to_skill(payload.get("input"))
                output_dir = OUTPUTS_DIR / f"{now_stamp()}_{uuid.uuid4().hex[:6]}"
                output_dir.mkdir(parents=True, exist_ok=True)
                job_id = uuid.uuid4().hex[:12]
                LATEST_JOB_ID = job_id
                set_job(
                    job_id,
                    id=job_id,
                    status="queued",
                    input=rel_path(input_path),
                    output_dir=rel_path(output_dir),
                    logs=[],
                )
                thread = threading.Thread(target=run_job, args=(job_id, input_path, output_dir), daemon=True)
                thread.start()
                self.send_json(get_job(job_id), 202)
                return
            if path == "/api/run-queue":
                payload = self.read_json_body()
                scan_id = str(payload.get("scan_id") or LATEST_SCAN_ID or "")
                scan = SCANS.get(scan_id)
                if not scan:
                    raise ValueError("请先扫描待拆解队列")
                selected_paths = payload.get("paths")
                pending_items = scan.get("pending", [])
                if isinstance(selected_paths, list) and selected_paths:
                    selected = set(str(item) for item in selected_paths)
                    pending_items = [item for item in pending_items if item.get("path") in selected]
                limit = int(payload.get("limit") or 0)
                if limit > 0:
                    pending_items = pending_items[:limit]
                if not pending_items:
                    raise ValueError("没有待拆解视频")
                output_dir = OUTPUTS_DIR / f"{now_stamp()}_queue_{uuid.uuid4().hex[:6]}"
                output_dir.mkdir(parents=True, exist_ok=True)
                job_id = uuid.uuid4().hex[:12]
                LATEST_JOB_ID = job_id
                set_job(
                    job_id,
                    id=job_id,
                    status="queued",
                    type="queue",
                    scan_id=scan_id,
                    total=len(pending_items),
                    completed=0,
                    failed=0,
                    output_dir=rel_path(output_dir),
                    items=[
                        {
                            "path": item["path"],
                            "name": item["name"],
                            "product": item.get("product", ""),
                            "video_id": item.get("video_id", ""),
                            "relative_path": item.get("relative_path", ""),
                            "target_path": item.get("target_path", ""),
                            "status": "queued",
                        }
                        for item in pending_items
                    ],
                    logs=[],
                )
                script_dir = Path(scan["script_dir"]).resolve()
                thread = threading.Thread(target=run_queue_job, args=(job_id, pending_items, output_dir, script_dir), daemon=True)
                thread.start()
                self.send_json(get_job(job_id), 202)
                return
            if path == "/api/open":
                payload = self.read_json_body()
                target = resolve_skill_path_for_open(payload.get("path") or "outputs")
                result = subprocess.run(["open", str(target)], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    self.send_json({"error": (result.stderr or result.stdout or "打开目录失败").strip()}, 500)
                    return
                self.send_json({"ok": True, "path": rel_path(target)})
                return
            self.send_json({"error": "未知接口"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def handle_upload(self):
        ensure_dirs()
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        field = form["video"] if "video" in form else None
        if field is None or not getattr(field, "filename", ""):
            self.send_json({"error": "没有收到视频文件"}, 400)
            return
        filename = f"{now_stamp()}_{safe_filename(field.filename)}"
        target = INPUTS_DIR / filename
        with target.open("wb") as output:
            while True:
                chunk = field.file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        info = file_info(target)
        info["name"] = target.name
        self.send_json({"ok": True, "file": info})

    def serve_static(self, path):
        if path in {"/", "/analyze"}:
            target = WEB_ROOT / "index.html"
        else:
            target = WEB_ROOT / path.lstrip("/")
        resolved = path_in_web(target)
        if not resolved or not resolved.exists() or not resolved.is_file():
            self.send_json({"error": "页面不存在"}, 404)
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="Run the hybrid reference video analysis agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10002)
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_dirs()
    httpd = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    print(f"混剪参考视频解析智能体 Web 界面: http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
