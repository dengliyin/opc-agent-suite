from __future__ import annotations

import json
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


KOLSPRITE_API_URL = "https://www.kolsprite.com/api/v2/video/fetch_video_data_by_url"
TIKTOK_URL_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/[^\s,，)）]+", re.IGNORECASE)


def normalize_tiktok_url(url):
    return str(url or "").strip().split("?", 1)[0].rstrip("。.;；")


def extract_tiktok_urls(text):
    urls = []
    for match in TIKTOK_URL_RE.findall(str(text or "")):
        url = normalize_tiktok_url(match)
        if url and url not in urls:
            urls.append(url)
    return urls


def parse_tiktok_identity(url):
    normalized = normalize_tiktok_url(url)
    match = re.search(r"tiktok\.com/@([^/?#]+)/video/(\d+)", normalized, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"无法识别 TikTok 视频 URL: {url}")
    return match.group(1), match.group(2)


def safe_component(value, fallback, max_length):
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._-")
    return (text or fallback)[:max_length]


def fetch_video_data(url):
    api_url = KOLSPRITE_API_URL + "?" + urllib.parse.urlencode({"url": url})
    request = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not payload.get("success"):
        message = payload.get("message") if isinstance(payload, dict) else "返回格式错误"
        raise RuntimeError(f"Kolsprite 解析失败: {message}")
    if not (data.get("hdUrls") or data.get("urls")):
        raise RuntimeError("Kolsprite 没有返回可下载的视频地址")
    return data


def save_video(url, target):
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
        if partial.stat().st_size <= 100000:
            raise RuntimeError("Kolsprite 返回的视频文件过小")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def existing_video(output_dir, video_id):
    candidates = list(output_dir.glob(f"*-{video_id}-*.mp4")) + list(output_dir.glob(f"{video_id}.mp4"))
    for candidate in sorted(set(candidates)):
        if candidate.is_file() and candidate.stat().st_size > 100000:
            return candidate
    return None


def write_metadata(path, url, video_id, title=""):
    path.write_text(
        json.dumps(
            {
                "tiktok_video_url": url,
                "video_id": video_id,
                "video_title": title,
                "collected_at": datetime.now().astimezone().date().isoformat(),
                "source": "9992_url_download",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def download_one(url, output_dir, fetcher=fetch_video_data, saver=save_video):
    normalized = normalize_tiktok_url(url)
    username, video_id = parse_tiktok_identity(normalized)
    output_dir.mkdir(parents=True, exist_ok=True)
    found = existing_video(output_dir, video_id)
    if found:
        write_metadata(found.with_suffix(".json"), normalized, video_id)
        return "skipped", found, video_id

    data = fetcher(normalized)
    video_urls = data.get("hdUrls") or data.get("urls") or []
    title = str(data.get("desc") or "").strip()
    filename = "-".join(
        [
            safe_component(username, "unknown_user", 40),
            video_id,
            safe_component(title, "untitled", 96),
        ]
    )
    target = output_dir / f"{filename}.mp4"
    saver(str(video_urls[0]), target)
    write_metadata(target.with_suffix(".json"), normalized, video_id, title)
    return "downloaded", target, video_id
