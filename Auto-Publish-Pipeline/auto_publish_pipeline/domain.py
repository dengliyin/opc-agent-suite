from __future__ import annotations

import random
import re
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


COUNTRY_DEFAULT_LANGUAGES = {
    "US": "英语",
    "UK": "英语",
    "IE": "英语",
    "CA": "英语",
    "AU": "英语",
    "FR": "法语",
    "ES": "西班牙语",
    "MX": "西班牙语",
    "DE": "德语",
    "IT": "意大利语",
    "VN": "越南语",
    "PH": "菲律宾语",
    "BR": "葡萄牙语",
    "TH": "泰语",
    "MY": "马来语",
    "BD": "孟加拉语",
    "NP": "尼泊尔语",
    "ID": "印尼语",
}
COUNTRY_ALIASES = {"GB": "UK"}


def infer_script_country(path: Path) -> str:
    if not path.name.startswith("复刻-"):
        return ""
    for token in path.stem.split("-")[2:]:
        country = COUNTRY_ALIASES.get(token.upper(), token.upper())
        if country in COUNTRY_DEFAULT_LANGUAGES:
            return country
    return ""


def infer_product_name(path: Path) -> str:
    tokens = path.stem.split("-")
    for index, token in enumerate(tokens[2:], start=2):
        country = COUNTRY_ALIASES.get(token.upper(), token.upper())
        if country in COUNTRY_DEFAULT_LANGUAGES:
            return "-".join(tokens[1:index])
    return path.parent.name


def normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def match_product_code(product_name: str, libraries: list[dict[str, Any]]) -> str:
    needle = normalize(product_name)
    matches = []
    for library in libraries:
        candidates = (library.get("code"), library.get("name"), library.get("key"))
        if any(needle and (needle in normalize(value) or normalize(value) in needle) for value in candidates):
            matches.append(str(library.get("code") or library.get("key") or ""))
    return matches[0] if len(set(matches)) == 1 else ""


def build_task_spec(
    payload: dict[str, Any],
    catalog: dict[str, Any],
    mapping_resolver: Callable[[str, str, str], dict[str, Any]],
    *,
    chooser: random.Random | None = None,
) -> dict[str, Any]:
    chooser = chooser or random.SystemRandom()
    clone_path = Path(str(payload.get("clone_path") or "")).expanduser().resolve()
    if not clone_path.is_file() or not clone_path.name.startswith("复刻-") or clone_path.suffix.lower() != ".md":
        raise ValueError("请选择有效的复刻-*.md脚本")
    if not clone_path.read_text(encoding="utf-8", errors="ignore").strip():
        raise ValueError("选择的复刻脚本为空")
    country = infer_script_country(clone_path)
    if not country:
        raise ValueError("无法从复刻脚本文件名识别国家，请确认文件名包含国家代码")
    submitted_country = str(payload.get("country") or "").strip().upper()
    submitted_country = COUNTRY_ALIASES.get(submitted_country, submitted_country)
    if submitted_country and submitted_country != country:
        raise ValueError("任务国家必须与复刻脚本文件名中的国家一致")
    language = str(payload.get("target_language") or "").strip() or COUNTRY_DEFAULT_LANGUAGES[country]
    model = str(payload.get("video_model") or "").strip().lower()
    if model not in {"omni", "grok"}:
        raise ValueError("视频模型只支持 Omni 或 Grok")
    reference_image = Path(str(payload.get("reference_image") or "")).expanduser().resolve()
    if not reference_image.is_file() or reference_image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("请选择有效的产品参考图")
    concurrency = int(payload.get("concurrency") or 0)
    if not 1 <= concurrency <= 20:
        raise ValueError("片段生成并发数必须在1到20之间")
    caption_mode = str(payload.get("caption_mode") or "")
    if caption_mode not in {"none", "karaoke"}:
        raise ValueError("请选择字幕模式")
    profile_ids = [str(value) for value in payload.get("profile_ids") or [] if str(value)]
    if not profile_ids or len(profile_ids) != len(set(profile_ids)):
        raise ValueError("请按顺序选择至少一个且不重复的发布账号")

    profiles_by_id = {str(item.get("id")): item for item in catalog.get("profiles") or []}
    selected_profiles = []
    for profile_id in profile_ids:
        profile = profiles_by_id.get(profile_id)
        if not profile:
            raise ValueError(f"发布账号不存在：{profile_id}")
        if str(profile.get("country") or "").upper() != country:
            raise ValueError(f"账号国家与任务国家不一致：{profile.get('name', profile_id)}")
        selected_profiles.append(profile)

    product_code = str(payload.get("product_code") or "").strip()
    product_name = infer_product_name(clone_path)
    if not product_code:
        product_code = match_product_code(product_name, catalog.get("libraries") or [])
    library = next(
        (
            item for item in catalog.get("libraries") or []
            if product_code in {str(item.get("code") or ""), str(item.get("key") or "")}
        ),
        None,
    )
    if not library:
        raise ValueError("无法从脚本识别产品标题库，请确认产品脚本和标题库命名一致")
    country_library = (library.get("by_country") or {}).get(country) or {}
    valid_captions = [
        str(item.get("full_text") or "").strip()
        for item in country_library.get("items") or []
        if str(item.get("full_text") or "").strip() and len(item.get("tags") or []) == 5
    ]
    publish_count = len(selected_profiles) * 3
    candidate_budget = math.ceil(publish_count * 1.5)
    if len(valid_captions) < publish_count:
        raise ValueError(f"标题库不足：需要{publish_count}条有效文案，当前只有{len(valid_captions)}条")
    captions = chooser.sample(valid_captions, publish_count)

    videos_by_path = {str(item.get("path") or ""): item for item in catalog.get("videos") or []}
    existing_videos = []
    for raw_path in payload.get("existing_video_paths") or []:
        path = str(Path(str(raw_path)).expanduser().resolve())
        video = videos_by_path.get(path)
        if not video or video.get("published"):
            raise ValueError(f"已有成品不可用：{Path(path).name}")
        if str(video.get("product_code") or "") != product_code or country not in (video.get("countries") or []):
            raise ValueError(f"已有成品与当前产品或国家不匹配：{Path(path).name}")
        if path not in existing_videos:
            existing_videos.append(path)
    if len(existing_videos) > candidate_budget:
        existing_videos = existing_videos[:candidate_budget]
    generation_count = max(0, candidate_budget - len(existing_videos))

    assignments = []
    for account_index, profile in enumerate(selected_profiles):
        resolved = mapping_resolver(str(profile["id"]), product_code, country)
        for local_index in range(3):
            variant_index = account_index * 3 + local_index
            assignments.append(
                {
                    "variant_index": variant_index + 1,
                    "profile_id": str(profile["id"]),
                    "profile_name": str(profile.get("name") or profile["id"]),
                    "product_id": str(resolved["product_id"]),
                    "product_short_name": str(resolved["product_short_name"]),
                    "caption": captions[variant_index],
                    "status": "pending",
                }
            )

    auto_publish = bool(payload.get("auto_publish"))
    start_mode = str(payload.get("start_mode") or "immediate")
    scheduled_at = 0.0
    if auto_publish and start_mode == "scheduled":
        raw = str(payload.get("scheduled_at") or "").strip()
        try:
            scheduled_at = datetime.fromisoformat(raw).astimezone().timestamp()
        except ValueError as exc:
            raise ValueError("首次发布时间格式无效") from exc
        if scheduled_at <= datetime.now().astimezone().timestamp():
            raise ValueError("首次发布时间必须晚于当前时间")
    elif auto_publish and start_mode != "immediate":
        raise ValueError("请选择立即开始或定时开始")

    return {
        "clone_path": str(clone_path),
        "product_name": product_name,
        "product_code": product_code,
        "country": country,
        "target_language": language,
        "video_model": model,
        "reference_image": str(reference_image),
        "concurrency": concurrency,
        "caption_mode": caption_mode,
        "profile_ids": profile_ids,
        "publish_count": publish_count,
        "candidate_budget": candidate_budget,
        "generation_count": generation_count,
        "variant_count": generation_count,
        "existing_videos": existing_videos,
        "interval_seconds": 10,
        "auto_publish": auto_publish,
        "start_mode": start_mode if auto_publish else "manual",
        "scheduled_at": scheduled_at,
        "assignments": assignments,
    }
