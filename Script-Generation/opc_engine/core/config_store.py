#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "app_config.json"
LEGACY_CONFIG_PATH = ROOT / "fastmoss_config.json"
CONFIG_SCHEMA_VERSION = 2


CONFIG_SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "product_project",
        "产品项目与产品资料。所有功能都会先确认这里的产品项目，再把结果写入对应项目目录。",
        [
            "product_project_slug",
            "product_project_root",
            "product_profile_path",
            "product_profile",
            "product_reference_markdown",
            "product_reference_source",
        ],
    ),
    (
        "hot_collection",
        "爆款采集配置。包含采集账号、搜索条件、筛选条件、采集数量和浏览器显示方式。",
        [
            "phone",
            "password",
            "keyword",
            "country",
            "category_path",
            "shop_type",
            "product_types",
            "product_status",
            "creator_conversion_rate_filter",
            "total_sales_filter",
            "total_gmv_filter",
            "sales_7d_filter",
            "gmv_7d_filter",
            "creator_count_filter",
            "commission_rate_filter",
            "shipping_method_filter",
            "product_limit",
            "videos_per_product",
            "show_browser",
        ],
    ),
    (
        "ai_model",
        "模型调用配置。视频拆解、脚本产出和脚本适配会共用这些模型连接参数。",
        [
            "modelmesh_api_key",
            "modelmesh_base_url",
            "video_analysis_model",
            "video_analysis_max_output_tokens",
        ],
    ),
    (
        "video_teardown",
        "视频拆解配置。包含待拆解视频路径、拆解提示词路径和爆款内容知识库路径。",
        [
            "analysis_input_path",
            "video_analysis_prompt",
            "video_analysis_prompt_path",
            "video_teardown_knowledge_base_path",
        ],
    ),
    (
        "script_generation",
        "脚本产出配置。把爆款拆解结果或竞品脚本、产品信息和模块内知识库合成自家产品带货脚本。",
        [
            "script_generation_prompt_path",
            "script_generation_backend",
            "script_obsidian_cli_command",
            "script_obsidian_vault_path",
            "script_content_knowledge_base_path",
            "script_reference_analysis_path",
            "script_reference_script_path",
            "script_product_document_path",
            "script_country",
            "script_audio_emotion",
            "script_target_language",
            "script_total_duration",
        ],
    ),
    (
        "script_adaptation",
        "脚本适配配置。把成品脚本适配成视频生成模型可用的图片提示词和分镜视频提示词。",
        [
            "script_adaptation_input_path",
            "script_adaptation_prompt_path",
            "script_adaptation_target_model",
            "script_adaptation_segment_seconds",
            "script_adaptation_notes",
        ],
    ),
    (
        "video_generation",
        "视频生成配置。当前是视频片段组合和生成流程的本地框架入口。",
        [
            "clip_assembly_input_dir",
            "clip_assembly_output_name",
            "clip_assembly_notes",
        ],
    ),
    (
        "video_publish",
        "视频发布配置。当前是发布计划和发布记录的本地框架入口。",
        [
            "video_publish_input_path",
            "video_publish_account",
            "video_publish_caption",
            "video_publish_tags",
            "video_publish_mode",
        ],
    ),
    (
        "data_attribution",
        "数据归因配置。包含自然流数据、投放数据下载和整理分析所需的本地参数。",
        [
            "data_attribution_download_script_path",
            "data_attribution_ads_download_script_path",
            "data_attribution_download_output_dir",
            "data_attribution_download_notes",
            "natural_flow_management_url",
            "natural_flow_login_url",
            "natural_flow_account_group",
            "natural_flow_export_button_text_re",
            "data_recovery_input_path",
            "data_recovery_natural_input_path",
            "data_recovery_ads_input_path",
            "data_recovery_manual_metrics",
        ],
    ),
    (
        "script_optimization",
        "脚本优化配置。根据归因结果和原脚本生成下一轮优化建议。",
        [
            "script_optimization_input_path",
            "script_optimization_metrics_path",
            "script_optimization_notes",
        ],
    ),
]


SECTION_NAMES = {section_name for section_name, _comment, _fields in CONFIG_SECTIONS}
GROUPED_SECTION_NAMES = SECTION_NAMES | {"other"}
KNOWN_FIELDS = {field for _section_name, _comment, fields in CONFIG_SECTIONS for field in fields}
COMMENT_KEYS = {"_说明", "_字段说明", "_comment", "_comments", "_note", "_notes"}


def active_config_path() -> Path:
    override = os.environ.get("OPC_APP_CONFIG_PATH") or os.environ.get("KESAI_APP_CONFIG_PATH")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return path
    return CONFIG_PATH if CONFIG_PATH.exists() else LEGACY_CONFIG_PATH


def _read_raw_config() -> dict[str, Any]:
    config_path = active_config_path()
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def flatten_config(data: dict[str, Any] | None) -> dict[str, Any]:
    """Return the runtime flat config, accepting both old flat and new grouped JSON."""
    if not isinstance(data, dict):
        return {}

    flat: dict[str, Any] = {}

    for section_name, section in data.items():
        if section_name not in GROUPED_SECTION_NAMES:
            continue
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if key in COMMENT_KEYS or key.startswith("_"):
                continue
            flat[key] = value

    for key, value in data.items():
        if key in GROUPED_SECTION_NAMES or key in COMMENT_KEYS or key.startswith("_"):
            continue
        if key in {"config_schema_version", "schema_version"}:
            continue
        flat[key] = value

    return flat


def group_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Build the annotated on-disk config grouped by workflow/function."""
    flat = flatten_config(config or {})
    grouped: dict[str, Any] = {
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "_说明": "本文件只保存在本机，已按 OPC 内容量化增长引擎的功能分组。程序读取时会自动展开为运行所需字段；请勿提交真实账号、密钥或产品资料。",
    }
    consumed: set[str] = set()

    for section_name, comment, fields in CONFIG_SECTIONS:
        section_payload: dict[str, Any] = {"_说明": comment}
        for field in fields:
            if field in flat:
                section_payload[field] = flat[field]
                consumed.add(field)
        grouped[section_name] = section_payload

    extra = {key: value for key, value in flat.items() if key not in consumed}
    if extra:
        grouped["other"] = {
            "_说明": "暂未归入固定功能分组的兼容字段。确认无用后可以清理。",
            **extra,
        }

    return grouped


def load_app_config(defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = flatten_config(_read_raw_config())
    if defaults:
        return {**defaults, **loaded}
    return loaded


def save_app_config(config: dict[str, Any]) -> dict[str, Any]:
    flat = flatten_config(config)
    config_path = active_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(group_config(flat), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return flat
