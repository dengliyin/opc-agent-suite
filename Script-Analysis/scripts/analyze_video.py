#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = SKILL_ROOT / "config" / "settings.json"
DEFAULT_SECRETS_PATH = SKILL_ROOT / "config" / "settings.local.json"


def log(message):
    print(message, flush=True)


def load_settings(path):
    if not path.exists():
        raise SystemExit(f"缺少配置文件: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"配置文件 JSON 格式错误: {path}\n{exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"配置文件必须是 JSON object: {path}")
    if path == DEFAULT_SETTINGS_PATH and DEFAULT_SECRETS_PATH.exists():
        try:
            local_settings = json.loads(DEFAULT_SECRETS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"配置文件 JSON 格式错误: {DEFAULT_SECRETS_PATH}\n{exc}") from exc
        if isinstance(local_settings, dict) and local_settings.get("api_key"):
            data["api_key"] = local_settings["api_key"]
    return data


def resolve_skill_path(value, label, must_exist=True):
    text = str(value or "").strip()
    if not text:
        raise SystemExit(f"配置缺少 {label}")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = SKILL_ROOT / path
    path = path.resolve()
    try:
        path.relative_to(SKILL_ROOT)
    except ValueError as exc:
        raise SystemExit(f"{label} 必须在智能体文件夹内: {path}") from exc
    if must_exist and not path.exists():
        raise SystemExit(f"{label} 不存在: {path}")
    return path


def read_text(path):
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def get_api_key(settings, cli_api_key):
    return (
        cli_api_key
        or os.environ.get("VIDEO_TEARDOWN_AGENT_API_KEY")
        or str(settings.get("api_key") or "").strip()
    )


def guess_mime_type(video_path):
    mime_type, _ = mimetypes.guess_type(str(video_path))
    return mime_type or "video/mp4"


def safe_stem(value):
    stem = Path(value).stem
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return cleaned.strip("_") or "video"


def output_stem(value):
    stem = safe_stem(value)
    parts = [part for part in stem.split("_") if part]
    if parts and parts[-1].isdigit() and len(parts[-1]) >= 10:
        return parts[-1]
    if len(stem) <= 64:
        return stem
    matches = re.findall(r"\d{10,24}", stem)
    video_id = matches[-1] if matches else ""
    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:8]
    identity = f"-{video_id}" if video_id else ""
    prefix_length = max(8, 64 - len(identity) - len(digest) - 1)
    return f"{stem[:prefix_length].rstrip('_-')}{identity}-{digest}"[:64]


def find_videos(input_path):
    if input_path.is_file():
        return [input_path]
    return sorted(
        path
        for path in input_path.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v"}
    )


def find_existing_output_stems(output_root):
    if not output_root.exists():
        return set()
    stems = set()
    for path in output_root.rglob("*_teardown.md"):
        if path.is_file():
            stems.add(path.name[: -len("_teardown.md")])
    return stems


def endpoint_variants(base_url, model):
    base_url = base_url.rstrip("/")
    encoded_model = urllib.parse.quote(model, safe="")
    raw_model = model.strip("/")
    return [
        (f"{base_url}/v1beta/models/{encoded_model}:generateContent", "encoded-model"),
        (f"{base_url}/v1beta/models/{raw_model}:generateContent", "raw-model"),
    ]


def build_prompt(settings):
    prompt_path = resolve_skill_path(settings.get("prompt_file"), "prompt_file")
    return read_text(prompt_path)


def build_payload(prompt, video_path, field_style, max_output_tokens, temperature):
    video_data = base64.b64encode(video_path.read_bytes()).decode("ascii")
    mime_type = guess_mime_type(video_path)
    if field_style == "snake":
        video_part = {"inline_data": {"mime_type": mime_type, "data": video_data}}
    else:
        video_part = {"inlineData": {"mimeType": mime_type, "data": video_data}}

    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    video_part,
                ],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }


def post_json(url, headers, payload, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"error": body}
        return exc.code, parsed


def extract_text(response):
    texts = []
    finish_reasons = []
    for candidate in response.get("candidates", []):
        finish_reason = candidate.get("finishReason")
        if finish_reason:
            finish_reasons.append(str(finish_reason))
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                texts.append(text)
    if texts:
        return "\n".join(texts)
    if "text" in response:
        return str(response["text"])
    reason_text = ", ".join(finish_reasons) if finish_reasons else "EMPTY_RESPONSE"
    raise RuntimeError(
        "模型没有返回可保存的 Markdown 正文"
        f"；finishReason={reason_text}"
        f"；response={json.dumps(response, ensure_ascii=False)[:1200]}"
    )


def analyze_one_video(video_path, settings, args, prompt, output_dir):
    api_key = get_api_key(settings, args.api_key)
    if not api_key:
        raise SystemExit("缺少 api_key：请在 config/settings.local.json 中填写，或设置 VIDEO_TEARDOWN_AGENT_API_KEY。")

    model = args.model or str(settings.get("model") or "gemini-3.5-flash")
    base_url = args.base_url or str(settings.get("base_url") or "https://zexapi.com")
    timeout = int(args.timeout or settings.get("timeout_seconds") or 240)
    max_output_tokens = int(args.max_output_tokens or settings.get("max_output_tokens") or 32768)
    temperature = float(args.temperature if args.temperature is not None else settings.get("temperature", 0.2))
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    log(f"开始拆解: {video_path.name}")
    log(f"视频大小: {video_path.stat().st_size / 1024 / 1024:.2f} MB")
    log(f"模型: {model}")

    last_error = None
    for url, endpoint_style in endpoint_variants(base_url, model):
        for field_style in ("snake", "camel"):
            log(f"尝试接口格式: {endpoint_style}, 字段格式: {field_style}")
            payload = build_payload(prompt, video_path, field_style, max_output_tokens, temperature)
            status, response = post_json(url, headers, payload, timeout)
            if 200 <= status < 300:
                text = extract_text(response)
                stem = output_stem(video_path.name)
                markdown_path = output_dir / f"{stem}_teardown.md"
                markdown_path.write_text(text.strip() + "\n", encoding="utf-8")
                log(f"拆解完成: {markdown_path}")
                return markdown_path

            last_error = {
                "status": status,
                "response": response,
                "endpoint_style": endpoint_style,
                "field_style": field_style,
            }
            message = response.get("error") if isinstance(response, dict) else response
            log(f"  未成功，HTTP {status}: {str(message)[:220]}")
            time.sleep(0.5)

    raise RuntimeError(f"所有接口尝试均失败: {json.dumps(last_error, ensure_ascii=False)[:1200]}")


def parse_args():
    parser = argparse.ArgumentParser(description="Use Script-Analysis local config to analyze MP4/MOV videos.")
    parser.add_argument("input", help="本地视频文件，或包含 MP4/MOV/M4V 的文件夹")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH), help="智能体共享配置文件")
    parser.add_argument("--output-dir", default="", help="输出目录；留空则使用 settings.output_dir 下的本次运行目录")
    parser.add_argument("--api-key", default="", help="临时覆盖 api_key，不建议写入命令历史")
    parser.add_argument("--base-url", default="", help="临时覆盖 base_url")
    parser.add_argument("--model", default="", help="临时覆盖模型名")
    parser.add_argument("--timeout", type=int, default=0, help="临时覆盖请求超时时间")
    parser.add_argument("--max-output-tokens", type=int, default=0, help="临时覆盖最大输出 token")
    parser.add_argument("--temperature", type=float, default=None, help="临时覆盖 temperature")
    parser.add_argument("--skip-existing", action="store_true", help="扫描 outputs 后跳过已拆解视频，只处理未拆解项")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描并输出视频统计，不发起拆解")
    return parser.parse_args()


def main():
    args = parse_args()
    settings_path = Path(args.settings).expanduser().resolve()
    settings = load_settings(settings_path)

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"输入路径不存在: {input_path}")

    videos = find_videos(input_path)
    if not videos:
        raise SystemExit(f"没有找到可拆解的视频: {input_path}")

    base_output_dir = resolve_skill_path(settings.get("output_dir", "outputs"), "output_dir", must_exist=False)
    existing_output_stems = find_existing_output_stems(base_output_dir)
    pending_videos = [video for video in videos if output_stem(video.name) not in existing_output_stems]

    log(f"扫描目录: {input_path}")
    log(f"视频总数: {len(videos)}")
    log(f"已拆解: {len(videos) - len(pending_videos)}")
    log(f"未拆解: {len(pending_videos)}")

    if args.scan_only:
        return 0

    if args.skip_existing:
        videos = pending_videos
        if not videos:
            log("没有未拆解视频，跳过本次任务。")
            return 0

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = base_output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(settings)
    log(f"智能体目录: {SKILL_ROOT}")
    log(f"本次输出目录: {output_dir}")
    log(f"视频数量: {len(videos)}")

    success = 0
    failures = []
    for video_path in videos:
        try:
            analyze_one_video(video_path, settings, args, prompt, output_dir)
            success += 1
        except Exception as exc:
            failures.append((video_path, exc))
            log(f"拆解失败: {video_path.name}: {exc}")

    log(f"任务完成: 成功 {success}/{len(videos)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
