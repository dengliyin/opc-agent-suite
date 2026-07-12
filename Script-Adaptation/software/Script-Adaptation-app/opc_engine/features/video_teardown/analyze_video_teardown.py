#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from opc_engine.core.config_store import load_app_config
from opc_engine.core.project_assets import ensure_project_dirs, infer_source_id, require_product_project, source_stage_dir


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROMPT_PATH = ROOT / "workflow_configs" / "video_teardown" / "config" / "video_teardown_prompt.md"
DEFAULT_PROMPT_CONFIG_PATH = "workflow_configs/video_teardown/config/video_teardown_prompt.md"
DEFAULT_KNOWLEDGE_BASE_PATH = ROOT / "knowledge_base" / "hot_content_knowledge_base.md"
LEGACY_KNOWLEDGE_BASE_PATH = ROOT / "knowledge_base" / "video_teardown_knowledge_base.md"
DEFAULT_KNOWLEDGE_BASE_CONFIG_PATH = "knowledge_base/hot_content_knowledge_base.md"
LEGACY_KNOWLEDGE_BASE_CONFIG_PATH = "knowledge_base/video_teardown_knowledge_base.md"
WORKFLOW_CONFIG_DIR = ROOT / "workflow_configs"
WORKFLOW_INPUT_FILES = {
    "product_info": WORKFLOW_CONFIG_DIR / "product_info" / "config" / "inputs.json",
    "hot_collection": WORKFLOW_CONFIG_DIR / "hot_collection" / "config" / "inputs.json",
    "video_teardown": WORKFLOW_CONFIG_DIR / "video_teardown" / "config" / "inputs.json",
    "script_generation": WORKFLOW_CONFIG_DIR / "script_generation" / "config" / "inputs.json",
    "script_adaptation": WORKFLOW_CONFIG_DIR / "script_adaptation" / "config" / "inputs.json",
    "video_generation": WORKFLOW_CONFIG_DIR / "video_generation" / "config" / "inputs.json",
    "video_publish": WORKFLOW_CONFIG_DIR / "video_publish" / "config" / "inputs.json",
    "data_attribution": WORKFLOW_CONFIG_DIR / "data_attribution" / "config" / "inputs.json",
    "script_optimization": WORKFLOW_CONFIG_DIR / "script_optimization" / "config" / "inputs.json",
}
WORKFLOW_INPUT_METADATA_FIELDS = {"workflow", "updated_at", "product_project_root"}

DEFAULT_MODEL = "google/gemini-3-flash"
DEFAULT_BASE_URL = "https://router.shengsuanyun.com/api"
DEFAULT_PROMPT = """请用中文简要分析这个短视频，确认你能看到视频内容。
输出三部分：
1. 视频里出现了什么画面
2. 是否有人声/字幕/产品展示
3. 适合做爆款拆解的关键信息
"""


def log(message):
    print(message, flush=True)


def read_workflow_inputs(stage):
    path = WORKFLOW_INPUT_FILES.get(stage)
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def merge_workflow_inputs(config, *stages):
    for stage in stages:
        for field, value in read_workflow_inputs(stage).items():
            if field in WORKFLOW_INPUT_METADATA_FIELDS:
                continue
            config[field] = value
    return config


def load_config(*workflow_stages):
    config = load_app_config()
    if workflow_stages:
        merge_workflow_inputs(config, *workflow_stages)
    return config


def get_api_key(config):
    return (
        os.environ.get("MODELMESH_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or config.get("modelmesh_api_key")
        or config.get("gemini_api_key")
        or ""
    )


def resolve_project_path(value):
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def read_text(path):
    if path and path.exists() and path.is_file():
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    return ""


def normalize_knowledge_base_path(value):
    text = str(value or "").strip()
    if not text or text == LEGACY_KNOWLEDGE_BASE_CONFIG_PATH:
        return DEFAULT_KNOWLEDGE_BASE_CONFIG_PATH
    return text


def normalize_prompt_path(value):
    text = str(value or "").strip()
    return text or DEFAULT_PROMPT_CONFIG_PATH


def get_base_prompt(args, config):
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    if os.environ.get("VIDEO_TEARDOWN_PROMPT"):
        return os.environ["VIDEO_TEARDOWN_PROMPT"]
    if config.get("video_analysis_prompt"):
        return config["video_analysis_prompt"]
    configured_path = normalize_prompt_path(
        os.environ.get("VIDEO_TEARDOWN_PROMPT_FILE")
        or config.get("video_analysis_prompt_path")
        or DEFAULT_PROMPT_CONFIG_PATH
    )
    prompt_text = read_text(resolve_project_path(configured_path))
    if prompt_text:
        return prompt_text
    return DEFAULT_PROMPT


def get_knowledge_base_text(args, config):
    configured_path = normalize_knowledge_base_path(
        getattr(args, "knowledge_file", "")
        or os.environ.get("VIDEO_TEARDOWN_KNOWLEDGE_BASE")
        or config.get("content_knowledge_base_path")
        or config.get("video_teardown_knowledge_base_path")
        or DEFAULT_KNOWLEDGE_BASE_CONFIG_PATH
    )
    if not configured_path:
        return ""

    knowledge_path = resolve_project_path(configured_path)
    candidates = [knowledge_path]
    if knowledge_path != DEFAULT_KNOWLEDGE_BASE_PATH:
        candidates.append(DEFAULT_KNOWLEDGE_BASE_PATH)
    if LEGACY_KNOWLEDGE_BASE_PATH not in candidates:
        candidates.append(LEGACY_KNOWLEDGE_BASE_PATH)
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    return ""


def get_prompt(args, config):
    prompt = get_base_prompt(args, config).strip()
    knowledge = get_knowledge_base_text(args, config)
    if not knowledge:
        return prompt

    return f"""以下是本项目本地保存的【爆款内容知识库】，它是你分析视频时必须参考的长期知识，也会用于后续脚本改写，但不能替代对当前视频画面的逐帧观察。

{knowledge}

---

以下是本次任务的【爆款视频拆解提示词】，请严格执行：

{prompt}
"""


def guess_mime_type(video_path):
    mime_type, _ = mimetypes.guess_type(str(video_path))
    return mime_type or "video/mp4"


def extract_text(response):
    texts = []
    for candidate in response.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                texts.append(text)
    if texts:
        return "\n".join(texts)
    if "text" in response:
        return str(response["text"])
    return json.dumps(response, ensure_ascii=False, indent=2)


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


def build_payload(prompt, video_path, field_style, max_output_tokens):
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
            "temperature": 0.2,
            "maxOutputTokens": max_output_tokens,
        },
    }


def endpoint_variants(base_url, model):
    base_url = base_url.rstrip("/")
    encoded_model = urllib.parse.quote(model, safe="")
    raw_model = model.strip("/")
    return [
        (f"{base_url}/v1beta/models/{encoded_model}:generateContent", "encoded-model"),
        (f"{base_url}/v1beta/models/{raw_model}:generateContent", "raw-model"),
    ]


def analyze_video(video_path, config, args):
    api_key = get_api_key(config)
    if not api_key:
        raise SystemExit("缺少 API Key：请设置 MODELMESH_API_KEY，或在 app_config.json 写入 modelmesh_api_key")

    model = args.model or config.get("video_analysis_model") or DEFAULT_MODEL
    base_url = args.base_url or config.get("modelmesh_base_url") or DEFAULT_BASE_URL
    prompt = get_prompt(args, config)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    log("开始 Gemini 视频拆解请求")
    log(f"视频文件: {video_path.name}")
    log(f"视频大小: {video_path.stat().st_size / 1024 / 1024:.2f} MB")
    log(f"模型: {model}")
    log(f"接口: {base_url.rstrip('/')}/v1beta/models/...:generateContent")

    last_error = None
    for url, endpoint_style in endpoint_variants(base_url, model):
        for field_style in ("snake", "camel"):
            log(f"尝试接口格式: {endpoint_style}, 字段格式: {field_style}")
            payload = build_payload(prompt, video_path, field_style, args.max_output_tokens)
            status, response = post_json(url, headers, payload, args.timeout)
            if 200 <= status < 300:
                return extract_text(response), response, endpoint_style, field_style
            last_error = {"status": status, "response": response, "endpoint_style": endpoint_style, "field_style": field_style}
            message = response.get("error") if isinstance(response, dict) else response
            log(f"  未成功，HTTP {status}: {str(message)[:220]}")
            time.sleep(0.5)

    raise RuntimeError(f"所有 Gemini 原生接口尝试均失败: {json.dumps(last_error, ensure_ascii=False)[:1200]}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run a minimal Gemini video teardown test on one local MP4.")
    parser.add_argument("video", help="本地 MP4 文件路径")
    parser.add_argument("--model", default="", help=f"模型名，默认 {DEFAULT_MODEL}")
    parser.add_argument("--base-url", default="", help=f"中转 API base，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--prompt", default="", help="直接传入测试提示词")
    parser.add_argument("--prompt-file", default="", help="从本地文件读取提示词")
    parser.add_argument("--knowledge-file", default="", help="从本地文件读取爆款内容知识库，默认读取 app_config.json 中的路径")
    parser.add_argument("--output-dir", default="", help="分析结果输出目录；留空时写入当前产品项目 / hot_sources / 视频ID / teardown")
    parser.add_argument("--timeout", type=int, default=180, help="单次请求超时时间，秒")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    return parser.parse_args()


def main():
    args = parse_args()
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"视频不存在: {video_path}")
    if video_path.suffix.lower() != ".mp4":
        log("提示: 文件不是 .mp4 后缀，将继续按 MIME 自动识别")

    config = load_config("video_teardown")
    require_product_project(config, "拆解视频")
    text, raw_response, endpoint_style, field_style = analyze_video(video_path, config, args)

    source_id = infer_source_id(video_path)
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        ensure_project_dirs(config)
        output_dir = source_stage_dir(source_id, "teardown", config)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source_id}_gemini_teardown_test.md"
    raw_path = output_dir / f"{source_id}_gemini_teardown_test.raw.json"
    output_path.write_text(text.strip() + "\n", encoding="utf-8")
    raw_path.write_text(json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log(f"测试成功: endpoint={endpoint_style}, field={field_style}")
    log(f"拆解结果: {output_path}")
    log(f"原始响应: {raw_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"测试失败: {exc}")
        sys.exit(1)
