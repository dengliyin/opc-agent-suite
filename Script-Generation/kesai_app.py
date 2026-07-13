#!/usr/bin/env python3
import json
import html
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import urllib.request

from opc_engine.core.config_store import load_app_config, save_app_config
from opc_engine.core.project_assets import (
    collection_run_dir,
    ensure_project_dirs,
    infer_source_id,
    product_project_root,
    product_project_slug,
    product_profile_path as project_product_profile_path,
    product_report_dir,
    project_relative,
    raw_data_dir,
    safe_name,
    source_stage_dir,
)


ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parent
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT", str(Path.home() / "Documents" / "Obsidian Vault"))
).expanduser()
LATEST_HOT_VIDEO_AGENT_DIR = WORKSPACE_ROOT / "Video-Collection"
LATEST_HOT_VIDEO_AGENT_URL = os.environ.get("OPC_HOT_VIDEO_AGENT_URL", "http://127.0.0.1:9991")
LATEST_VIDEO_TEARDOWN_AGENT_DIR = WORKSPACE_ROOT / "Script-Analysis"
LATEST_VIDEO_TEARDOWN_AGENT_URL = os.environ.get("OPC_VIDEO_TEARDOWN_AGENT_URL", "http://127.0.0.1:9992/")
LATEST_SCRIPT_PRODUCTION_AGENT_URL = os.environ.get("OPC_SCRIPT_PRODUCTION_AGENT_URL", "http://127.0.0.1:9993/")
LATEST_SCRIPT_ADAPTATION_AGENT_DIR = WORKSPACE_ROOT / "Script-Adaptation"
LATEST_SCRIPT_ADAPTATION_AGENT_URL = os.environ.get("OPC_SCRIPT_ADAPTATION_AGENT_URL", "http://127.0.0.1:9994/")
LATEST_SCRIPT_ADAPTATION_APP_DIR = LATEST_SCRIPT_ADAPTATION_AGENT_DIR / "software" / "Script-Adaptation-app"
LATEST_VIDEO_OUTPUT_AGENT_DIR = WORKSPACE_ROOT / "Video-Generation"
LATEST_VIDEO_OUTPUT_AGENT_URL = os.environ.get("OPC_VIDEO_OUTPUT_AGENT_URL", "http://127.0.0.1:9995/")
LATEST_FINISHED_VIDEO_MANAGER_DIR = WORKSPACE_ROOT / "Finished-Video-Manager"
LATEST_FINISHED_VIDEO_MANAGER_URL = os.environ.get("OPC_FINISHED_VIDEO_MANAGER_URL", "http://127.0.0.1:9996/")
LATEST_PRODUCT_SCRIPT_REWRITE_DIR = WORKSPACE_ROOT / "Product-Script-Rewrite"
LATEST_PRODUCT_SCRIPT_REWRITE_URL = os.environ.get("OPC_PRODUCT_SCRIPT_REWRITE_URL", "http://127.0.0.1:9997/")
LATEST_VIDEO_ASSEMBLY_AGENT_DIR = WORKSPACE_ROOT / "Video-Assembly-hd"
LATEST_VIDEO_ASSEMBLY_AGENT_URL = os.environ.get("OPC_VIDEO_ASSEMBLY_AGENT_URL", "http://127.0.0.1:9998/")
KNOWLEDGE_BASE_DIR = ROOT / "knowledge_base"
WORKFLOW_CONFIG_DIR = ROOT / "workflow_configs"
VIDEO_TEARDOWN_CONFIG_DIR = WORKFLOW_CONFIG_DIR / "video_teardown" / "config"
SCRIPT_GENERATION_CONFIG_DIR = ROOT / "opc_engine" / "features" / "script_generation" / "config"
SCRIPT_ADAPTATION_CONFIG_DIR = WORKFLOW_CONFIG_DIR / "script_adaptation" / "config"
DEFAULT_VIDEO_ANALYSIS_PROMPT_PATH = VIDEO_TEARDOWN_CONFIG_DIR / "video_teardown_prompt.md"
DEFAULT_VIDEO_ANALYSIS_PROMPT_CONFIG_PATH = "workflow_configs/video_teardown/config/video_teardown_prompt.md"
DEFAULT_TEARDOWN_KNOWLEDGE_BASE_PATH = KNOWLEDGE_BASE_DIR / "hot_content_knowledge_base.md"
LEGACY_TEARDOWN_KNOWLEDGE_BASE_PATH = KNOWLEDGE_BASE_DIR / "video_teardown_knowledge_base.md"
DEFAULT_TEARDOWN_KNOWLEDGE_BASE_CONFIG_PATH = "knowledge_base/hot_content_knowledge_base.md"
LEGACY_TEARDOWN_KNOWLEDGE_BASE_CONFIG_PATH = "knowledge_base/video_teardown_knowledge_base.md"
LEGACY_SCRIPT_ADAPTATION_PROMPT_PATH = KNOWLEDGE_BASE_DIR / "script_adaptation_prompt.md"
LEGACY_SCRIPT_ADAPTATION_PROMPT_CONFIG_PATH = "knowledge_base/script_adaptation_prompt.md"
DEFAULT_SCRIPT_GENERATION_PROMPT_PATH = SCRIPT_GENERATION_CONFIG_DIR / "script_generation_rewrite_prompt.md"
DEFAULT_SCRIPT_GENERATION_PROMPT_CONFIG_PATH = "opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md"
DEFAULT_SCRIPT_MUTATION_PROMPT_PATH = SCRIPT_GENERATION_CONFIG_DIR / "script_generation_mutation_prompt.md"
DEFAULT_SCRIPT_MUTATION_PROMPT_CONFIG_PATH = "opc_engine/features/script_generation/config/script_generation_mutation_prompt.md"
LEGACY_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH = "opc_engine/features/script_generation/config/cross_border_ecommerce_knowledge_base.md"
DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_PATH = VAULT_ROOT / "wiki" / "视频" / "07错题本"
DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH = DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_PATH.as_posix()
SCRIPT_PRESERVE_ORIGINAL_VALUE = "不改变原脚本"
COUNTRY_DEFAULT_LANGUAGE = {
    "法国": "法语",
    "france": "法语",
    "fr": "法语",
    "西班牙": "西班牙语",
    "spain": "西班牙语",
    "es": "西班牙语",
    "德国": "德语",
    "germany": "德语",
    "de": "德语",
    "马来西亚": "马来语",
    "malaysia": "马来语",
    "my": "马来语",
    "孟加拉": "孟加拉语",
    "孟加拉国": "孟加拉语",
    "bangladesh": "孟加拉语",
    "bd": "孟加拉语",
    "尼泊尔": "尼泊尔语",
    "nepal": "尼泊尔语",
    "np": "尼泊尔语",
}
DEFAULT_SCRIPT_ADAPTATION_PROMPT_PATH = SCRIPT_ADAPTATION_CONFIG_DIR / "script_adaptation_prompt.md"
DEFAULT_SCRIPT_ADAPTATION_PROMPT_CONFIG_PATH = "workflow_configs/script_adaptation/config/script_adaptation_prompt.md"
DEFAULT_PRODUCT_PROFILE_CONFIG_PATH = ""
PRODUCT_INFO_SOURCE_DIR = VAULT_ROOT / "wiki" / "产品" / "产品信息"
HOT_VIDEO_SOURCE_ROOT = VAULT_ROOT / "wiki" / "视频" / "03爆款视频"
HOT_SCRIPT_SOURCE_ROOT = VAULT_ROOT / "wiki" / "视频" / "04爆款视频脚本"
SCRIPT_OUTPUT_SOURCE_ROOT = VAULT_ROOT / "wiki" / "视频" / "05产品视频脚本"
SCRIPT_ADAPTED_SOURCE_ROOT = VAULT_ROOT / "wiki" / "视频" / "06产品适配后的脚本"
VIDEO_CLIP_SOURCE_ROOTS = {
    "omni": VAULT_ROOT / "wiki" / "视频" / "10omni视频片段",
    "grok": VAULT_ROOT / "wiki" / "视频" / "10grok视频片段",
    "sora": VAULT_ROOT / "wiki" / "视频" / "10sora视频片段",
}
SCRIPT_MISTAKE_BOOK_SOURCE_ROOT = DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_PATH
CATEGORY_TREE_PATH = ROOT / "data" / "fastmoss_category_tree.json"
HOST = os.environ.get("KESAI_APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("KESAI_APP_PORT", "8888"))
NATURAL_FLOW_DOWNLOAD_ENTRYPOINT = "opc_engine.features.data_attribution.download_natural_flow_data"
ADS_DOWNLOAD_ENTRYPOINT = "opc_engine.features.data_attribution.download_ad_performance_data"
UNIFIED_CONSOLE_INPUT_PATH = ROOT / "workflow_configs" / "unified_console" / "config" / "inputs.json"
UNIFIED_RUNTIME_DIR = ROOT / "runtime" / "unified_console"

PRODUCT_PROFILE_FIELDS = [
    "market",
    "collection_date",
    "product_name",
    "english_name",
    "category",
    "spec",
    "colors",
    "action_time",
    "regular_price",
    "promo_price",
    "top_selling_points",
    "audience_pain_matrix",
    "pain_conversion_talk_tracks",
    "tiktok_marketing_angles",
    "market_keywords",
    "material_type_suggestions",
    "notes",
]
DEFAULT_PRODUCT_PROFILE = {field: "" for field in PRODUCT_PROFILE_FIELDS}
PRODUCT_IDENTITY_FIELDS = ("product_name", "english_name")
PRODUCT_PROFILE_FIELD_LABELS = {
    "market": "市场 / 地区",
    "collection_date": "收集日期",
    "product_name": "产品名",
    "english_name": "英文名",
    "category": "类目",
    "spec": "规格",
    "colors": "色号",
    "action_time": "作用时间",
    "regular_price": "日常价",
    "promo_price": "活动价",
    "top_selling_points": "TOP 3 核心卖点",
    "audience_pain_matrix": "目标人群 x 痛点矩阵",
    "pain_conversion_talk_tracks": "核心痛点与转化话术",
    "tiktok_marketing_angles": "TikTok 营销推广切入点",
    "market_keywords": "市场关键词参考",
    "material_type_suggestions": "适配素材类型建议",
    "notes": "补充备注",
}
PRODUCT_PROFILE_LABEL_TO_FIELD = {label: field for field, label in PRODUCT_PROFILE_FIELD_LABELS.items()}
LEGACY_PRODUCT_PROFILE_ALIASES = {
    "product_name": "name",
    "top_selling_points": "selling_points",
    "audience_pain_matrix": "target_audience",
    "pain_conversion_talk_tracks": "pain_points",
    "tiktok_marketing_angles": "usage_scenarios",
    "promo_price": "price_offer",
    "material_type_suggestions": "tone",
}

DEFAULT_CONFIG = {
    "product_project_slug": "",
    "phone": "",
    "password": "",
    "keyword": "",
    "country": "马来西亚",
    "category_path": ["美妆个护", "头部护理与造型", "染发用品"],
    "shop_type": "全部",
    "product_types": [],
    "product_status": "在售",
    "creator_conversion_rate_filter": "全部",
    "total_sales_filter": "全部",
    "total_gmv_filter": "全部",
    "sales_7d_filter": "全部",
    "gmv_7d_filter": "全部",
    "creator_count_filter": "全部",
    "commission_rate_filter": "全部",
    "shipping_method_filter": "全部",
    "product_limit": 3,
    "videos_per_product": 20,
    "show_browser": False,
    "modelmesh_api_key": "",
    "modelmesh_base_url": "https://router.shengsuanyun.com/api",
    "video_analysis_model": "google/gemini-3-flash",
    "video_analysis_prompt": "",
    "video_analysis_prompt_path": DEFAULT_VIDEO_ANALYSIS_PROMPT_CONFIG_PATH,
    "video_teardown_knowledge_base_path": DEFAULT_TEARDOWN_KNOWLEDGE_BASE_CONFIG_PATH,
    "video_analysis_max_output_tokens": 32768,
    "analysis_input_path": "",
    "script_generation_prompt_path": DEFAULT_SCRIPT_GENERATION_PROMPT_CONFIG_PATH,
    "script_generation_mutation_prompt_path": DEFAULT_SCRIPT_MUTATION_PROMPT_CONFIG_PATH,
    "script_generation_backend": "api",
    "script_obsidian_cli_command": "",
    "script_obsidian_vault_path": "",
    "script_use_generation_prompt": True,
    "script_enable_mutation_rewrite": False,
    "script_mutation_mode": "standard",
    "script_mutation_variants": 3,
    "script_mutation_source": "复刻稿",
    "script_content_knowledge_base_path": DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH,
    "script_reference_analysis_path": "",
    "script_reference_script_path": "",
    "script_product_document_path": "",
    "script_country": SCRIPT_PRESERVE_ORIGINAL_VALUE,
    "script_target_language": SCRIPT_PRESERVE_ORIGINAL_VALUE,
    "script_total_duration": SCRIPT_PRESERVE_ORIGINAL_VALUE,
    "script_adaptation_input_path": "",
    "script_adaptation_prompt_path": DEFAULT_SCRIPT_ADAPTATION_PROMPT_CONFIG_PATH,
    "script_adaptation_target_model": "omni",
    "script_adaptation_segment_seconds": 8,
    "script_adaptation_notes": "",
    "clip_assembly_input_dir": "",
    "clip_assembly_output_name": "",
    "clip_assembly_notes": "",
    "video_publish_input_path": "",
    "video_publish_account": "",
    "video_publish_caption": "",
    "video_publish_tags": "",
    "video_publish_mode": "manual_record",
    "data_attribution_download_script_path": NATURAL_FLOW_DOWNLOAD_ENTRYPOINT,
    "data_attribution_ads_download_script_path": ADS_DOWNLOAD_ENTRYPOINT,
    "data_attribution_download_output_dir": "",
    "data_attribution_download_notes": "",
    "natural_flow_management_url": "",
    "natural_flow_login_url": "",
    "natural_flow_account_group": "",
    "natural_flow_export_button_text_re": "导出|下载|Export|Download",
    "data_recovery_input_path": "",
    "data_recovery_natural_input_path": "",
    "data_recovery_ads_input_path": "",
    "data_recovery_manual_metrics": "",
    "script_optimization_input_path": "",
    "script_optimization_metrics_path": "",
    "script_optimization_notes": "",
    "product_profile_path": DEFAULT_PRODUCT_PROFILE_CONFIG_PATH,
    "product_profile": DEFAULT_PRODUCT_PROFILE.copy(),
}

PATH_DISPLAY_FIELDS = [
    "product_profile_path",
    "product_project_root",
    "video_analysis_prompt_path",
    "video_teardown_knowledge_base_path",
    "analysis_input_path",
    "script_generation_prompt_path",
    "script_generation_mutation_prompt_path",
    "script_content_knowledge_base_path",
    "script_reference_analysis_path",
    "script_reference_script_path",
    "script_product_document_path",
    "script_adaptation_input_path",
    "script_adaptation_prompt_path",
    "clip_assembly_input_dir",
    "video_publish_input_path",
    "data_attribution_download_output_dir",
    "data_recovery_input_path",
    "data_recovery_natural_input_path",
    "data_recovery_ads_input_path",
    "script_optimization_input_path",
    "script_optimization_metrics_path",
]
PROJECT_SCOPED_PATH_FIELDS = [
    "analysis_input_path",
    "script_reference_analysis_path",
    "script_adaptation_input_path",
    "clip_assembly_input_dir",
    "video_publish_input_path",
    "data_recovery_input_path",
    "data_recovery_natural_input_path",
    "data_recovery_ads_input_path",
    "script_optimization_input_path",
    "script_optimization_metrics_path",
]

WORKFLOW_INPUT_FILES = {
    "product_info": "workflow_configs/product_info/config/inputs.json",
    "hot_collection": "workflow_configs/hot_collection/config/inputs.json",
    "video_teardown": "workflow_configs/video_teardown/config/inputs.json",
    "script_generation": "opc_engine/features/script_generation/config/inputs.json",
    "script_adaptation": "workflow_configs/script_adaptation/config/inputs.json",
    "video_generation": "workflow_configs/video_generation/config/inputs.json",
    "video_publish": "workflow_configs/video_publish/config/inputs.json",
    "data_attribution": "workflow_configs/data_attribution/config/inputs.json",
    "script_optimization": "workflow_configs/script_optimization/config/inputs.json",
}
WORKFLOW_INPUT_FIELDS = {
    "product_info": [
        "product_project_slug",
        "product_project_root",
        "product_profile_path",
        "product_profile",
    ],
    "hot_collection": [
        "product_project_slug",
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
    "video_teardown": [
        "product_project_slug",
        "modelmesh_api_key",
        "modelmesh_base_url",
        "video_analysis_model",
        "video_analysis_prompt_path",
        "video_teardown_knowledge_base_path",
        "video_analysis_max_output_tokens",
        "analysis_input_path",
    ],
    "script_generation": [
        "product_project_slug",
        "modelmesh_api_key",
        "modelmesh_base_url",
        "video_analysis_model",
        "script_generation_backend",
        "script_obsidian_cli_command",
        "script_obsidian_vault_path",
        "script_generation_prompt_path",
        "script_generation_mutation_prompt_path",
        "script_mutation_mode",
        "script_enable_mutation_rewrite",
        "script_mutation_variants",
        "script_mutation_source",
        "script_content_knowledge_base_path",
        "script_reference_analysis_path",
        "script_reference_script_path",
        "script_product_document_path",
        "script_country",
        "script_target_language",
        "script_total_duration",
    ],
    "script_adaptation": [
        "product_project_slug",
        "modelmesh_api_key",
        "modelmesh_base_url",
        "video_analysis_model",
        "video_analysis_max_output_tokens",
        "script_adaptation_input_path",
        "script_adaptation_prompt_path",
        "script_adaptation_target_model",
        "script_adaptation_segment_seconds",
        "script_adaptation_notes",
        "video_teardown_knowledge_base_path",
    ],
    "video_generation": [
        "product_project_slug",
        "clip_assembly_input_dir",
        "clip_assembly_output_name",
        "clip_assembly_notes",
    ],
    "video_publish": [
        "product_project_slug",
        "video_publish_input_path",
        "video_publish_account",
        "video_publish_caption",
        "video_publish_tags",
        "video_publish_mode",
    ],
    "data_attribution": [
        "product_project_slug",
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
    "script_optimization": [
        "product_project_slug",
        "script_optimization_input_path",
        "script_optimization_metrics_path",
        "script_optimization_notes",
    ],
}
WORKFLOW_INPUT_LOAD_EXCLUDED_FIELDS = {
    "product_project_slug",
    "product_project_root",
    "product_profile",
    "product_profile_path",
    "script_product_document_path",
}

UNIFIED_CONSOLE_FIELDS = [
    "product_project_slug",
    "product_project_root",
    "product_profile_path",
    "product_profile",
    "script_product_document_path",
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
    "modelmesh_api_key",
    "modelmesh_base_url",
    "video_analysis_model",
    "video_analysis_prompt_path",
    "video_teardown_knowledge_base_path",
    "video_analysis_max_output_tokens",
    "analysis_input_path",
    "video_analysis_prompt",
    "script_generation_backend",
    "script_obsidian_cli_command",
    "script_obsidian_vault_path",
    "script_generation_prompt_path",
    "script_generation_mutation_prompt_path",
    "script_mutation_mode",
    "script_enable_mutation_rewrite",
    "script_mutation_variants",
    "script_mutation_source",
    "script_content_knowledge_base_path",
    "script_reference_analysis_path",
    "script_reference_script_path",
    "script_country",
    "script_target_language",
    "script_total_duration",
    "script_generation_prompt",
    "script_adaptation_input_path",
    "script_adaptation_prompt_path",
    "script_adaptation_target_model",
    "script_adaptation_segment_seconds",
    "script_adaptation_notes",
    "script_adaptation_prompt",
    "clip_assembly_input_dir",
    "clip_assembly_output_name",
    "clip_assembly_notes",
    "video_publish_input_path",
    "video_publish_account",
    "video_publish_caption",
    "video_publish_tags",
    "video_publish_mode",
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
    "script_optimization_input_path",
    "script_optimization_metrics_path",
    "script_optimization_notes",
]


def summarize_job_logs(logs):
    summary = {
        "completed": None,
        "total": None,
        "current_batch": 0,
        "completed_batches": 0,
        "output_count": 0,
        "warning_count": 0,
        "last_output": "",
        "last_log": logs[-1] if logs else "",
        "source_path": "",
        "model": "",
    }
    for line in logs:
        if "警告" in line:
            summary["warning_count"] += 1
        if "已启用裂变，输入源为" in line:
            summary["source_path"] = line.split(":", 1)[-1].strip()
        if line.startswith("模型:"):
            summary["model"] = line.split(":", 1)[-1].strip()
        match = re.search(r"裂变第\s+(\d+)\s+批上下文长度", line)
        if match:
            summary["current_batch"] = max(summary["current_batch"], int(match.group(1)))
        match = re.search(r"裂变第\s+(\d+)\s+条上下文长度", line)
        if match:
            summary["current_batch"] = max(summary["current_batch"], int(match.group(1)))
        match = re.search(r"裂变第\s+(\d+)\s+批完成: 收到\s+(\d+)\s+个，累计\s+(\d+)\/(\d+)", line)
        if match:
            summary["completed_batches"] = max(summary["completed_batches"], int(match.group(1)))
            summary["completed"] = int(match.group(3))
            summary["total"] = int(match.group(4))
        match = re.search(r"裂变第\s+(\d+)\s+条完成: 收到\s+(\d+)\s+个，累计\s+(\d+)\/(\d+)", line)
        if match:
            summary["completed_batches"] = max(summary["completed_batches"], int(match.group(1)))
            summary["completed"] = int(match.group(3))
            summary["total"] = int(match.group(4))
        match = re.search(r"裂变变体数:\s+(\d+)（总数\s+(\d+)，已完成\s+(\d+)）", line)
        if match:
            summary["total"] = int(match.group(2))
            if summary["completed"] is None:
                summary["completed"] = int(match.group(3))
        if "脚本结果:" in line:
            summary["output_count"] += 1
            summary["last_output"] = line.split("脚本结果:", 1)[1].strip()
        elif "脚本产出成功" in line and summary["completed"] is None:
            summary["completed"] = summary["total"] or 1
            summary["total"] = summary["total"] or 1
    return summary


class JobManager:
    def __init__(self, max_concurrent=None):
        self.lock = threading.Lock()
        self.jobs = []
        self.next_id = 1
        default_limit = os.environ.get("KESAI_MAX_CONCURRENT_TASK_GROUPS") or os.environ.get("KESAI_MAX_CONCURRENT_JOBS") or "10"
        self.max_concurrent = max_concurrent or int(default_limit or 10)

    def start(self, task, command, env_extra=None, metadata=None, cwd=None):
        with self.lock:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env.setdefault("KESAI_MAX_API_CONCURRENT_REQUESTS", "10")
            if env_extra:
                env.update({str(key): str(value) for key, value in env_extra.items() if value is not None})
            job_id = self.next_id
            self.next_id += 1
            job = {
                "id": job_id,
                "process": None,
                "command": command,
                "cwd": str(cwd or ROOT),
                "env": env,
                "task": task,
                "queued_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "metadata": metadata or {},
                "logs": [f"任务排队: {task} #{job_id}"],
            }
            self.jobs.append(job)
            self.jobs = self.jobs[-80:]
            self._pump_queue_locked()
            return job_id

    def _running_count_locked(self):
        return sum(1 for job in self.jobs if job.get("process") is not None and job["process"].poll() is None)

    def _launch_job_locked(self, job):
        process = subprocess.Popen(
            job["command"],
            cwd=job.get("cwd") or str(ROOT),
            env=job["env"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        job["process"] = process
        job["started_at"] = time.time()
        job["logs"].append(f"任务启动: {job['task']} #{job['id']}")
        threading.Thread(target=self._read_output, args=(job,), daemon=True).start()

    def _pump_queue_locked(self):
        running_count = self._running_count_locked()
        for job in self.jobs:
            if running_count >= self.max_concurrent:
                break
            if job.get("process") is None and job.get("exit_code") is None:
                self._launch_job_locked(job)
                running_count += 1

    def _read_output(self, job):
        process = job["process"]
        if not process or not process.stdout:
            return
        for line in process.stdout:
            with self.lock:
                job["logs"].append(line.rstrip())
                job["logs"] = job["logs"][-1000:]
        exit_code = process.wait()
        with self.lock:
            job["exit_code"] = exit_code
            job["finished_at"] = time.time()
            job["logs"].append(f"任务结束，退出码: {exit_code}")
            self._pump_queue_locked()
        invalidate_file_listing_cache()

    def stop(self):
        with self.lock:
            stopped = 0
            for job in self.jobs:
                if job.get("process") is None and job.get("exit_code") is None:
                    job["exit_code"] = -15
                    job["finished_at"] = time.time()
                    job["logs"].append("已取消排队任务")
                    stopped += 1
                elif job.get("process") is not None and job["process"].poll() is None:
                    job["process"].terminate()
                    job["logs"].append("已请求停止任务")
                    stopped += 1
            return stopped

    def status(self):
        with self.lock:
            jobs = []
            for job in self.jobs:
                process = job.get("process")
                queued = process is None and job.get("exit_code") is None
                running = process is not None and process.poll() is None
                jobs.append(
                    {
                        "id": job["id"],
                        "task": job["task"],
                        "running": running,
                        "queued": queued,
                        "queued_at": job.get("queued_at"),
                        "started_at": job["started_at"],
                        "finished_at": job["finished_at"],
                        "exit_code": job["exit_code"],
                        "metadata": job.get("metadata", {}),
                        "summary": summarize_job_logs(job["logs"]),
                        "logs": job["logs"][-120:],
                    }
                )
            running_jobs = [job for job in jobs if job["running"]]
            queued_jobs = [job for job in jobs if job.get("queued")]
            latest = jobs[-1] if jobs else None
            aggregate_logs = []
            for job in jobs[-6:]:
                state = "排队中" if job.get("queued") else ("运行中" if job["running"] else "已结束")
                aggregate_logs.append(f"===== {job['task']} #{job['id']} {state} =====")
                aggregate_logs.extend(job["logs"][-80:])
            running = bool(running_jobs)
            return {
                "running": running,
                "task": running_jobs[-1]["task"] if len(running_jobs) == 1 else (f"{len(running_jobs)} 个任务运行中" if running_jobs else (latest["task"] if latest else None)),
                "started_at": running_jobs[-1]["started_at"] if running_jobs else (latest["started_at"] if latest else None),
                "finished_at": None if running_jobs else (latest["finished_at"] if latest else None),
                "exit_code": None if running_jobs else (latest["exit_code"] if latest else None),
                "active_count": len(running_jobs),
                "queue_count": len(queued_jobs),
                "max_concurrent": self.max_concurrent,
                "max_api_concurrent": int(os.environ.get("KESAI_MAX_API_CONCURRENT_REQUESTS", "10") or 10),
                "jobs": jobs[-20:],
                "logs": aggregate_logs[-400:],
            }


JOBS = JobManager()
FILE_LISTING_CACHE = {
    "expires_at": 0.0,
    "payload": None,
}
FILE_LISTING_CACHE_LOCK = threading.Lock()
FILE_LISTING_CACHE_SECONDS = 10.0


def _service_port(url, fallback):
    try:
        return int(urlparse(url).port or fallback)
    except (TypeError, ValueError):
        return fallback


def _agent_python(agent_dir):
    candidate = Path(agent_dir) / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _uvicorn_command_for_video_output():
    port = str(_service_port(LATEST_VIDEO_OUTPUT_AGENT_URL, 9995))
    uvicorn_bin = LATEST_VIDEO_OUTPUT_AGENT_DIR / ".venv" / "bin" / "uvicorn"
    if uvicorn_bin.exists():
        return [str(uvicorn_bin), "agent.app:app", "--host", "127.0.0.1", "--port", port]
    return [_agent_python(LATEST_VIDEO_OUTPUT_AGENT_DIR), "-m", "uvicorn", "agent.app:app", "--host", "127.0.0.1", "--port", port]


AGENT_SERVICES = {
    "collect": {
        "label": "视频采集",
        "url": LATEST_HOT_VIDEO_AGENT_URL,
        "cwd": LATEST_HOT_VIDEO_AGENT_DIR,
        "command": [_agent_python(LATEST_HOT_VIDEO_AGENT_DIR), "-m", "hot_video_agent", "web", "--host", "127.0.0.1", "--port", str(_service_port(LATEST_HOT_VIDEO_AGENT_URL, 9991))],
    },
    "analyze": {
        "label": "脚本解析",
        "url": LATEST_VIDEO_TEARDOWN_AGENT_URL,
        "cwd": LATEST_VIDEO_TEARDOWN_AGENT_DIR,
        "command": [_agent_python(LATEST_VIDEO_TEARDOWN_AGENT_DIR), str(LATEST_VIDEO_TEARDOWN_AGENT_DIR / "scripts" / "web_app.py"), "--host", "127.0.0.1", "--port", str(_service_port(LATEST_VIDEO_TEARDOWN_AGENT_URL, 9992))],
    },
    "script": {
        "label": "脚本产出",
        "url": LATEST_SCRIPT_PRODUCTION_AGENT_URL,
        "cwd": ROOT,
        "command": [_agent_python(ROOT), "-m", "opc_engine.features.script_generation.script_generation_agent_web", "--port", str(_service_port(LATEST_SCRIPT_PRODUCTION_AGENT_URL, 9993))],
    },
    "adapt": {
        "label": "脚本适配",
        "url": LATEST_SCRIPT_ADAPTATION_AGENT_URL,
        "cwd": LATEST_SCRIPT_ADAPTATION_AGENT_DIR,
        "command": ["bash", str(LATEST_SCRIPT_ADAPTATION_AGENT_DIR / "scripts" / "start_web.sh"), str(_service_port(LATEST_SCRIPT_ADAPTATION_AGENT_URL, 9994))],
    },
    "assemble": {
        "label": "视频产出",
        "url": LATEST_VIDEO_OUTPUT_AGENT_URL,
        "cwd": LATEST_VIDEO_OUTPUT_AGENT_DIR,
        "command": _uvicorn_command_for_video_output(),
    },
    "finished": {
        "label": "成品管理",
        "url": LATEST_FINISHED_VIDEO_MANAGER_URL,
        "cwd": LATEST_FINISHED_VIDEO_MANAGER_DIR,
        "command": [_agent_python(LATEST_FINISHED_VIDEO_MANAGER_DIR), "-m", "finished_video_manager.web", "web", "--host", "127.0.0.1", "--port", str(_service_port(LATEST_FINISHED_VIDEO_MANAGER_URL, 9996))],
    },
    "rewrite": {
        "label": "产品脚本改写",
        "url": LATEST_PRODUCT_SCRIPT_REWRITE_URL,
        "cwd": LATEST_PRODUCT_SCRIPT_REWRITE_DIR,
        "command": [_agent_python(LATEST_PRODUCT_SCRIPT_REWRITE_DIR), "-m", "product_script_rewrite.web", "--port", str(_service_port(LATEST_PRODUCT_SCRIPT_REWRITE_URL, 9997))],
    },
    "compose": {
        "label": "片段合成",
        "url": LATEST_VIDEO_ASSEMBLY_AGENT_URL,
        "cwd": LATEST_VIDEO_ASSEMBLY_AGENT_DIR,
        "command": [_agent_python(LATEST_VIDEO_ASSEMBLY_AGENT_DIR), str(LATEST_VIDEO_ASSEMBLY_AGENT_DIR / "app" / "server.py"), "--host", "127.0.0.1", "--port", str(_service_port(LATEST_VIDEO_ASSEMBLY_AGENT_URL, 9998))],
    },
}
AGENT_SERVICE_PROCESSES = {}
AGENT_SERVICE_LOCK = threading.Lock()


def agent_service_running(service):
    try:
        request = urllib.request.Request(service["url"], method="GET")
        with urllib.request.urlopen(request, timeout=1.2) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def agent_service_status(service_id):
    service = AGENT_SERVICES[service_id]
    running = agent_service_running(service)
    process = AGENT_SERVICE_PROCESSES.get(service_id)
    process_running = bool(process and process.poll() is None)
    return {
        "id": service_id,
        "label": service["label"],
        "url": service["url"],
        "running": running,
        "process_running": process_running,
    }


def agent_services_payload():
    return {"services": [agent_service_status(service_id) for service_id in AGENT_SERVICES]}


def start_agent_service(service_id):
    if service_id not in AGENT_SERVICES:
        raise ValueError("未知 agent 服务")
    service = AGENT_SERVICES[service_id]
    if agent_service_running(service):
        return agent_service_status(service_id) | {"started": False, "message": "服务已运行"}

    with AGENT_SERVICE_LOCK:
        process = AGENT_SERVICE_PROCESSES.get(service_id)
        if process and process.poll() is None:
            return agent_service_status(service_id) | {"started": False, "message": "服务正在启动"}

        log_dir = ROOT / "runtime" / "portal_services"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{service_id}.log"
        log_file = open(log_path, "a", encoding="utf-8")
        log_file.write(f"\n\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] start {' '.join(service['command'])}\n")
        log_file.flush()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if service_id == "collect" and not env.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") and chrome_path.exists():
            env["PLAYWRIGHT_CHROMIUM_EXECUTABLE"] = str(chrome_path)
        process = subprocess.Popen(
            service["command"],
            cwd=str(service["cwd"]),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        AGENT_SERVICE_PROCESSES[service_id] = process
    return agent_service_status(service_id) | {"started": True, "message": "已发送启动命令"}


def invalidate_file_listing_cache():
    with FILE_LISTING_CACHE_LOCK:
        FILE_LISTING_CACHE["expires_at"] = 0.0
        FILE_LISTING_CACHE["payload"] = None


def load_config():
    config = load_app_config()
    if config:
        merged = DEFAULT_CONFIG | config
        normalize_workflow_config_paths(merged)
        ensure_workflow_config_files(merged)
        apply_workflow_input_files(merged)
        merged["video_teardown_knowledge_base_path"] = normalize_teardown_knowledge_base_path(
            merged.get("video_teardown_knowledge_base_path")
        )
        merged["product_profile"] = normalize_product_profile(merged.get("product_profile", {}))
        configured_slug = str(merged.get("product_project_slug", "") or "").strip()
        if configured_slug and configured_slug != "current_product":
            profile_from_project = product_profile_for_slug(configured_slug)
            profile_path = ROOT / "projects" / product_project_slug({"product_project_slug": configured_slug}) / "product_profile" / "current_product_profile.md"
            if profile_path.exists() or has_product_identity({"product_profile": profile_from_project}):
                merged["product_profile"] = profile_from_project
        normalize_data_attribution_config(merged)
        apply_product_project_fields(merged)
        merged.pop("script_material_framework", None)
        merged.pop("script_reference_case", None)
        return merged
    merged = DEFAULT_CONFIG.copy()
    normalize_workflow_config_paths(merged)
    ensure_workflow_config_files(merged)
    apply_workflow_input_files(merged)
    normalize_data_attribution_config(merged)
    apply_product_project_fields(merged)
    return merged


def workflow_input_path(stage):
    rel_path = WORKFLOW_INPUT_FILES.get(stage)
    if not rel_path:
        raise ValueError(f"未知功能输入配置: {stage}")
    return ROOT / rel_path


def read_workflow_inputs(stage):
    path = workflow_input_path(stage)
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def apply_workflow_input_files(config):
    for stage, fields in WORKFLOW_INPUT_FIELDS.items():
        data = read_workflow_inputs(stage)
        if not data:
            continue
        for field in fields:
            if field in WORKFLOW_INPUT_LOAD_EXCLUDED_FIELDS:
                continue
            if field in data:
                config[field] = data[field]
    return config


def workflow_input_payload(stage, config):
    fields = WORKFLOW_INPUT_FIELDS.get(stage, [])
    payload = {
        "workflow": stage,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    for field in fields:
        if field in config:
            payload[field] = config[field]
    if "product_project_slug" not in payload:
        payload["product_project_slug"] = config.get("product_project_slug", "")
    if config.get("product_project_slug"):
        payload["product_project_root"] = project_relative(product_project_root(config))
    return payload


def write_workflow_inputs(stage, config):
    path = workflow_input_path(stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = workflow_input_payload(stage, config)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_job_workflow_input_snapshot(stage, config):
    snapshot_dir = ROOT / "runtime" / "job_inputs"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = snapshot_dir / f"{stage}-{stamp}-{threading.get_ident()}.json"
    payload = workflow_input_payload(stage, config)
    payload["snapshot_for_job"] = True
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def ensure_workflow_input_files(config):
    for stage in WORKFLOW_INPUT_FILES:
        path = workflow_input_path(stage)
        if not path.exists():
            write_workflow_inputs(stage, config)
    return config


def read_json_file(path):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def read_unified_console_inputs():
    return read_json_file(UNIFIED_CONSOLE_INPUT_PATH)


def unified_console_payload(config):
    payload = {
        "workflow": "unified_console",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "_说明": "统一控制台专用配置。只保存新入口的页面状态和运行参数，不覆盖原 agent 配置。",
    }
    for field in UNIFIED_CONSOLE_FIELDS:
        if field in config:
            payload[field] = config[field]
    return payload


def write_unified_console_inputs(config):
    UNIFIED_CONSOLE_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = unified_console_payload(config)
    UNIFIED_CONSOLE_INPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    invalidate_file_listing_cache()
    return UNIFIED_CONSOLE_INPUT_PATH


def product_name_from_product_doc(path):
    path = Path(path)
    if path.parent != PRODUCT_INFO_SOURCE_DIR and path.parent.name:
        return path.parent.name
    return path.stem.replace("-产品信息", "").strip() or path.stem


def selected_product_doc_path(config):
    raw_path = str(
        (config or {}).get("script_product_document_path")
        or (config or {}).get("product_profile_path")
        or ""
    ).strip()
    if raw_path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if path.exists() and path.is_file():
            resolved = path.resolve()
            try:
                resolved.relative_to(PRODUCT_INFO_SOURCE_DIR.resolve())
                return resolved
            except ValueError:
                pass
    external_path = external_product_info_path_for_config(config or {})
    return external_path.resolve() if external_path and external_path.exists() else None


def apply_unified_product_context(config):
    product_doc = selected_product_doc_path(config)
    if not product_doc:
        config["product_project_ready"] = False
        return config

    product_name = product_name_from_product_doc(product_doc)
    slug = product_project_slug({"product_project_slug": product_name})
    profile = product_profile_from_external_markdown(product_doc)
    config["product_project_slug"] = slug
    config["product_profile"] = profile
    config["product_profile_path"] = product_doc.as_posix()
    config["script_product_document_path"] = product_doc.as_posix()
    config["product_project_root"] = PRODUCT_INFO_SOURCE_DIR.as_posix()
    config["product_project_ready"] = True
    config["unified_product_name"] = product_name
    return config


def product_subdir(root, config):
    product_name = unified_product_name(config)
    return Path(root) / product_name if product_name else Path(root)


def unified_product_name(config):
    product_doc = selected_product_doc_path(config)
    if product_doc:
        return product_name_from_product_doc(product_doc)
    return str((config or {}).get("unified_product_name") or (config or {}).get("product_project_slug") or "").strip()


def apply_unified_agent_paths(config):
    if not selected_product_doc_path(config):
        return config
    target_model = str(config.get("script_adaptation_target_model", "omni") or "omni").strip().lower()
    clip_root = VIDEO_CLIP_SOURCE_ROOTS.get(target_model) or VIDEO_CLIP_SOURCE_ROOTS.get("omni")
    product_name = unified_product_name(config)
    agent_paths = {
        "collect_input_dir": PRODUCT_INFO_SOURCE_DIR.as_posix(),
        "collect_output_dir": product_subdir(HOT_VIDEO_SOURCE_ROOT, config).as_posix(),
        "analyze_input_dir": product_subdir(HOT_VIDEO_SOURCE_ROOT, config).as_posix(),
        "analyze_output_dir": product_subdir(HOT_SCRIPT_SOURCE_ROOT, config).as_posix(),
        "script_input_dir": product_subdir(HOT_SCRIPT_SOURCE_ROOT, config).as_posix(),
        "script_output_dir": product_subdir(SCRIPT_OUTPUT_SOURCE_ROOT, config).as_posix(),
        "adapt_input_dir": product_subdir(SCRIPT_OUTPUT_SOURCE_ROOT, config).as_posix(),
        "adapt_output_dir": (SCRIPT_ADAPTED_SOURCE_ROOT / target_model / product_name).as_posix(),
        "assemble_input_dir": (SCRIPT_ADAPTED_SOURCE_ROOT / target_model / product_name).as_posix(),
        "assemble_output_dir": (clip_root / product_name).as_posix() if clip_root else "",
    }
    config["unified_agent_paths"] = agent_paths
    return config


def normalize_unified_config(config):
    config = DEFAULT_CONFIG | dict(config or {})
    normalize_workflow_config_paths(config)
    config["category_path"] = config.get("category_path") or DEFAULT_CONFIG["category_path"]
    if isinstance(config["category_path"], str):
        config["category_path"] = [part.strip() for part in config["category_path"].split(">") if part.strip()]
    config["product_types"] = config.get("product_types") or []
    if isinstance(config["product_types"], str):
        config["product_types"] = [part.strip() for part in config["product_types"].split(",") if part.strip()]
    config["product_limit"] = int(config.get("product_limit", 3) or 3)
    config["videos_per_product"] = int(config.get("videos_per_product", 20) or 20)
    config["show_browser"] = bool(config.get("show_browser", False))
    config["script_adaptation_segment_seconds"] = int(config.get("script_adaptation_segment_seconds") or 8)
    target_model = str(config.get("script_adaptation_target_model") or "omni").strip().lower()
    if target_model not in {"omni", "sora", "grok"}:
        target_model = "omni"
    config["script_adaptation_target_model"] = target_model
    config["video_analysis_max_output_tokens"] = int(config.get("video_analysis_max_output_tokens", 32768) or 32768)
    config["script_mutation_mode"] = normalize_script_mutation_mode(config.get("script_mutation_mode", "standard"))
    config["script_mutation_source"] = "复刻稿"
    config["script_generation_mutation_prompt_path"] = mutation_prompt_config_path_for_mode(config.get("script_mutation_mode"))
    config["script_target_language"] = normalize_script_target_language(
        config.get("script_country", ""),
        config.get("script_target_language", ""),
    )
    config["video_teardown_knowledge_base_path"] = normalize_teardown_knowledge_base_path(
        config.get("video_teardown_knowledge_base_path", DEFAULT_CONFIG["video_teardown_knowledge_base_path"])
    )
    apply_unified_product_context(config)
    mistake_book_path = product_mistake_book_path_for_config(config)
    config["script_content_knowledge_base_path"] = (
        mistake_book_path.as_posix()
        if mistake_book_path
        else DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH
    )
    apply_unified_agent_paths(config)
    return config


def load_unified_console_config():
    base = DEFAULT_CONFIG | load_app_config()
    unified = read_unified_console_inputs()
    for key, value in unified.items():
        if key.startswith("_") or key in {"workflow", "updated_at"}:
            continue
        base[key] = value
    return normalize_unified_config(base)


def save_unified_console_config(payload):
    config = load_unified_console_config()
    for key, value in (payload or {}).items():
        if key.startswith("_"):
            continue
        config[key] = value
    config = normalize_unified_config(config)
    write_unified_console_inputs(config)
    return config


def write_unified_runtime_config(task, config):
    UNIFIED_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_task = re.sub(r"[^A-Za-z0-9_-]+", "_", str(task or "task")).strip("_") or "task"
    path = UNIFIED_RUNTIME_DIR / f"{safe_task}-{stamp}-{threading.get_ident()}.json"
    payload = unified_console_payload(config)
    payload["snapshot_for_job"] = True
    payload["snapshot_task"] = task
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_latest_hot_video_config(config):
    UNIFIED_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    product_name = unified_product_name(config)
    agent_paths = config.get("unified_agent_paths") or {}
    path = UNIFIED_RUNTIME_DIR / f"tkfastmoss-{time.strftime('%Y%m%d-%H%M%S')}-{threading.get_ident()}.json"
    payload = {
        "product": {
            "slug": config.get("product_project_slug") or product_name,
            "name": product_name,
            "path": str(UNIFIED_RUNTIME_DIR / "tkfastmoss_product_state" / safe_name(product_name, "product")),
        },
        "fastmoss": {
            "phone": config.get("phone", ""),
            "password": config.get("password", ""),
            "keyword": config.get("keyword", ""),
            "country": config.get("country", ""),
            "category_path": config.get("category_path") or ["全部"],
            "shop_type": config.get("shop_type", "全部"),
            "product_types": config.get("product_types") or [],
            "product_status": config.get("product_status", "在售"),
            "creator_conversion_rate_filter": config.get("creator_conversion_rate_filter", "全部"),
            "total_sales_filter": config.get("total_sales_filter", "全部"),
            "total_gmv_filter": config.get("total_gmv_filter", "全部"),
            "sales_7d_filter": config.get("sales_7d_filter", "全部"),
            "gmv_7d_filter": config.get("gmv_7d_filter", "全部"),
            "creator_count_filter": config.get("creator_count_filter", "全部"),
            "commission_rate_filter": config.get("commission_rate_filter", "全部"),
            "shipping_method_filter": config.get("shipping_method_filter", "全部"),
            "product_limit": int(config.get("product_limit") or 3),
            "videos_per_product": int(config.get("videos_per_product") or 5),
            "show_browser": bool(config.get("show_browser", False)),
        },
        "download": {"enabled": True, "source_csv": "", "limit": 0},
        "output": {"result_folder_name": safe_name(product_name, "results")},
        "_unified_console": {
            "product_doc": str(selected_product_doc_path(config) or ""),
            "collect_output_dir": agent_paths.get("collect_output_dir", ""),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def latest_hot_video_command(config):
    config_path = write_latest_hot_video_config(config)
    command = [str(LATEST_HOT_VIDEO_AGENT_DIR / "run_agent.sh"), "--config", str(config_path), "pipeline"]
    metadata = {
        "latest_agent": display_path(LATEST_HOT_VIDEO_AGENT_DIR),
        "latest_config": display_path(config_path),
    }
    return command, {}, metadata, LATEST_HOT_VIDEO_AGENT_DIR


def latest_video_teardown_command(config):
    input_path = Path(str(config.get("analysis_input_path") or "")).expanduser()
    output_dir = Path((config.get("unified_agent_paths") or {}).get("analyze_output_dir") or "")
    if not str(output_dir):
        output_dir = product_subdir(HOT_SCRIPT_SOURCE_ROOT, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        _agent_python(LATEST_VIDEO_TEARDOWN_AGENT_DIR),
        str(LATEST_VIDEO_TEARDOWN_AGENT_DIR / "scripts" / "analyze_video.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--skip-existing",
    ]
    if config.get("modelmesh_api_key"):
        command.extend(["--api-key", str(config.get("modelmesh_api_key"))])
    if config.get("modelmesh_base_url"):
        command.extend(["--base-url", str(config.get("modelmesh_base_url"))])
    if config.get("video_analysis_model"):
        command.extend(["--model", str(config.get("video_analysis_model"))])
    if config.get("video_analysis_max_output_tokens"):
        command.extend(["--max-output-tokens", str(config.get("video_analysis_max_output_tokens"))])
    metadata = {
        "latest_agent": display_path(LATEST_VIDEO_TEARDOWN_AGENT_DIR),
        "output_dir": str(output_dir),
    }
    return command, {}, metadata, LATEST_VIDEO_TEARDOWN_AGENT_DIR


def latest_script_adaptation_command(config):
    script_path = Path(str(config.get("script_adaptation_input_path") or "")).expanduser()
    target_model = str(config.get("script_adaptation_target_model") or "omni").strip().lower()
    command = [
        _agent_python(LATEST_SCRIPT_ADAPTATION_AGENT_DIR),
        "-m",
        "opc_engine.features.script_adaptation.script_adaptation_agent",
        "--stage",
        "adapt",
        "--script-file",
        str(script_path),
        "--execute",
    ]
    env = {
        "PYTHONPATH": str(LATEST_SCRIPT_ADAPTATION_APP_DIR),
        "MODELMESH_API_KEY": config.get("modelmesh_api_key") or os.environ.get("MODELMESH_API_KEY", ""),
    }
    metadata = {
        "latest_agent": display_path(LATEST_SCRIPT_ADAPTATION_AGENT_DIR),
        "target_model": target_model,
    }
    return command, env, metadata, LATEST_SCRIPT_ADAPTATION_APP_DIR


def latest_video_output_command(config):
    target_model = str(config.get("script_adaptation_target_model") or "omni").strip().lower()
    provider = target_model if target_model in {"omni", "grok", "sora"} else "omni"
    script_dir = (config.get("unified_agent_paths") or {}).get("assemble_input_dir") or config.get("clip_assembly_input_dir") or ""
    output_dir = (config.get("unified_agent_paths") or {}).get("assemble_output_dir", "")
    reference_root = (PRODUCT_INFO_SOURCE_DIR / unified_product_name(config)).as_posix()
    paths_url = f"{LATEST_VIDEO_OUTPUT_AGENT_URL.rstrip('/')}/settings/api/paths"
    post_url = f"{LATEST_VIDEO_OUTPUT_AGENT_URL.rstrip('/')}/{provider}/api/run"
    paths_payload = json.dumps(
        {
            "script_root": script_dir,
            "grok_script_root": script_dir,
            "sora_script_root": script_dir,
            "reference_root": reference_root,
            "video_output_root": output_dir,
            "grok_video_output_root": output_dir,
            "sora_video_output_root": output_dir,
        },
        ensure_ascii=False,
    )
    payload = json.dumps({"stage": "smart", "overwrite": False, "script_paths": None}, ensure_ascii=False)
    code = "\n".join(
        [
            "import urllib.request, sys",
            f"paths_url={paths_url!r}",
            f"url={post_url!r}",
            f"paths_payload={paths_payload!r}.encode('utf-8')",
            f"payload={payload!r}.encode('utf-8')",
            "try:",
            "    path_req=urllib.request.Request(paths_url, data=paths_payload, headers={'Content-Type':'application/json'}, method='POST')",
            "    with urllib.request.urlopen(path_req, timeout=10) as r:",
            "        print('路径配置已同步到最新视频产出 Agent')",
            "        print(r.read().decode('utf-8', 'replace')[:1000])",
            "    req=urllib.request.Request(url, data=payload, headers={'Content-Type':'application/json'}, method='POST')",
            "    with urllib.request.urlopen(req, timeout=10) as r:",
            "        print(r.read().decode('utf-8', 'replace'))",
            "except Exception:",
            "    print('无法调用最新视频产出 Agent，请先启动 Video-Generation：cd "
            + str(LATEST_VIDEO_OUTPUT_AGENT_DIR)
            + " && .venv/bin/uvicorn agent.app:app --host 127.0.0.1 --port 9995', file=sys.stderr)",
            "    raise",
        ]
    )
    env = {
        "SCRIPT_ROOT": script_dir,
        "GROK_SCRIPT_ROOT": script_dir,
        "SORA_SCRIPT_ROOT": script_dir,
        "VIDEO_OUTPUT_ROOT": output_dir,
        "GROK_VIDEO_OUTPUT_ROOT": output_dir,
        "SORA_VIDEO_OUTPUT_ROOT": output_dir,
    }
    metadata = {
        "latest_agent": display_path(LATEST_VIDEO_OUTPUT_AGENT_DIR),
        "agent_url": LATEST_VIDEO_OUTPUT_AGENT_URL,
        "provider": provider,
        "script_dir": script_dir,
        "output_dir": output_dir,
        "reference_root": reference_root,
    }
    return [sys.executable, "-c", code], env, metadata, LATEST_VIDEO_OUTPUT_AGENT_DIR


def normalize_prompt_path(value, default_config_path, legacy_config_paths=()):
    text = str(value or "").strip()
    if not text or text in set(legacy_config_paths):
        return default_config_path
    return text


def normalize_script_generation_config_path(value, default_config_path):
    text = str(value or "").strip()
    if not text:
        return default_config_path
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        path.resolve().relative_to(SCRIPT_GENERATION_CONFIG_DIR.resolve())
    except ValueError:
        return default_config_path
    return text


def normalize_script_content_knowledge_base_path(value):
    text = str(value or "").strip()
    if not text or text == LEGACY_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH:
        return DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH
    return text


def normalize_script_mutation_mode(value):
    return "standard"


def mutation_prompt_config_path_for_mode(mode):
    return DEFAULT_SCRIPT_MUTATION_PROMPT_CONFIG_PATH


def normalize_workflow_config_paths(config):
    config["video_analysis_prompt_path"] = normalize_prompt_path(
        config.get("video_analysis_prompt_path"),
        DEFAULT_VIDEO_ANALYSIS_PROMPT_CONFIG_PATH,
    )
    config["script_generation_prompt_path"] = normalize_script_generation_config_path(
        config.get("script_generation_prompt_path"),
        DEFAULT_SCRIPT_GENERATION_PROMPT_CONFIG_PATH,
    )
    configured_mutation_path = str(config.get("script_generation_mutation_prompt_path") or "").strip()
    builtin_mutation_paths = {
        "",
        DEFAULT_SCRIPT_MUTATION_PROMPT_CONFIG_PATH,
        str(DEFAULT_SCRIPT_MUTATION_PROMPT_PATH),
    }
    legacy_mutation_prompt_name = "script_generation_mutation_" + "adv" + "anced_prompt.md"
    if Path(configured_mutation_path).name == legacy_mutation_prompt_name:
        configured_mutation_path = DEFAULT_SCRIPT_MUTATION_PROMPT_CONFIG_PATH
    config["script_mutation_mode"] = normalize_script_mutation_mode(config.get("script_mutation_mode"))
    if configured_mutation_path in builtin_mutation_paths:
        configured_mutation_path = mutation_prompt_config_path_for_mode(config.get("script_mutation_mode"))
    config["script_generation_mutation_prompt_path"] = normalize_script_generation_config_path(
        configured_mutation_path,
        mutation_prompt_config_path_for_mode(config.get("script_mutation_mode")),
    )
    config["script_content_knowledge_base_path"] = normalize_script_content_knowledge_base_path(
        config.get("script_content_knowledge_base_path") or config.get("video_teardown_knowledge_base_path"),
    )
    config["script_adaptation_prompt_path"] = normalize_prompt_path(
        config.get("script_adaptation_prompt_path"),
        DEFAULT_SCRIPT_ADAPTATION_PROMPT_CONFIG_PATH,
        [LEGACY_SCRIPT_ADAPTATION_PROMPT_CONFIG_PATH],
    )
    return config


def ensure_local_text_file(target_path, fallback_paths=(), fallback_text=""):
    target_path = Path(target_path)
    if target_path.exists():
        return target_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    text = str(fallback_text or "").strip()
    if not text:
        for fallback_path in fallback_paths:
            fallback_path = Path(fallback_path)
            if fallback_path.exists() and fallback_path.is_file():
                candidate_text = fallback_path.read_text(encoding="utf-8", errors="ignore").strip()
                if candidate_text:
                    text = candidate_text
                    break
    if text:
        target_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return target_path


def ensure_workflow_config_files(config):
    normalize_workflow_config_paths(config)
    inline_teardown_prompt = str(config.get("video_analysis_prompt", "") or "").strip()
    ensure_local_text_file(
        resolve_project_path(config.get("video_analysis_prompt_path"), DEFAULT_VIDEO_ANALYSIS_PROMPT_PATH),
        fallback_text=inline_teardown_prompt,
    )
    ensure_local_text_file(
        resolve_project_path(config.get("script_generation_prompt_path"), DEFAULT_SCRIPT_GENERATION_PROMPT_PATH),
    )
    ensure_local_text_file(
        resolve_project_path(config.get("script_adaptation_prompt_path"), DEFAULT_SCRIPT_ADAPTATION_PROMPT_PATH),
        fallback_paths=[LEGACY_SCRIPT_ADAPTATION_PROMPT_PATH],
    )
    if inline_teardown_prompt:
        config["video_analysis_prompt"] = ""
    return config


def normalize_teardown_knowledge_base_path(value):
    text = str(value or "").strip()
    if not text or text == LEGACY_TEARDOWN_KNOWLEDGE_BASE_CONFIG_PATH:
        return DEFAULT_TEARDOWN_KNOWLEDGE_BASE_CONFIG_PATH
    return text


def normalize_data_attribution_config(config):
    for key, default_value in [
        ("data_attribution_download_script_path", NATURAL_FLOW_DOWNLOAD_ENTRYPOINT),
        ("data_attribution_ads_download_script_path", ADS_DOWNLOAD_ENTRYPOINT),
    ]:
        value = str(config.get(key) or "").strip()
        legacy_leaf = Path(value).name
        if legacy_leaf == "download_natural_flow_data.py":
            value = NATURAL_FLOW_DOWNLOAD_ENTRYPOINT
        elif legacy_leaf == "download_ad_performance_data.py":
            value = ADS_DOWNLOAD_ENTRYPOINT
        config[key] = value or default_value
    return config


def module_cmd(module_name, *args):
    return [sys.executable, "-m", module_name, *args]


def normalize_product_profile(profile):
    if not isinstance(profile, dict):
        profile = {}
    normalized = {}
    for field in PRODUCT_PROFILE_FIELDS:
        value = profile.get(field, "")
        if not value and field in LEGACY_PRODUCT_PROFILE_ALIASES:
            value = profile.get(LEGACY_PRODUCT_PROFILE_ALIASES[field], "")
        normalized[field] = str(value or "")
    return normalized


def product_profile_from_markdown(text):
    profile = DEFAULT_PRODUCT_PROFILE.copy()
    current_field = ""
    buffer = []

    def flush():
        nonlocal buffer, current_field
        if current_field:
            profile[current_field] = "\n".join(buffer).strip()
        buffer = []

    for line in str(text or "").splitlines():
        if line.startswith("## "):
            flush()
            label = line[3:].strip()
            current_field = PRODUCT_PROFILE_LABEL_TO_FIELD.get(label, "")
            continue
        if current_field:
            buffer.append(line)
    flush()
    return normalize_product_profile(profile)


def markdown_meta_value(text, key):
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", str(text or ""))
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def markdown_title(text):
    match = re.search(r"(?m)^#\s+(.+?)\s*$", str(text or ""))
    return match.group(1).strip() if match else ""


def product_profile_from_external_markdown(path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    profile = product_profile_from_markdown(text)
    if not has_product_identity({"product_profile": profile}):
        profile["product_name"] = (
            markdown_meta_value(text, "project")
            or markdown_title(text).replace("· 产品简报", "").strip()
            or path.stem
        )
    if not profile.get("market"):
        profile["market"] = markdown_meta_value(text, "market")
    if not profile.get("notes"):
        profile["notes"] = f"产品信息来源：{path.as_posix()}"
    return normalize_product_profile(profile)


def external_product_info_files():
    if not PRODUCT_INFO_SOURCE_DIR.exists():
        return []
    direct_files = [path for path in PRODUCT_INFO_SOURCE_DIR.glob("*.md") if path.is_file() and not path.name.startswith("_")]
    nested_files = [path for path in PRODUCT_INFO_SOURCE_DIR.glob("*/*.md") if path.is_file() and not path.name.startswith("_")]
    return sorted(
        direct_files + nested_files,
        key=lambda p: (p.parent.name.lower(), p.name.lower()),
    )


def product_info_slug_from_path(path):
    stem = Path(path).stem.replace("-产品信息", "").strip()
    if Path(path).parent != PRODUCT_INFO_SOURCE_DIR and Path(path).parent.name:
        stem = Path(path).parent.name
    return product_project_slug({"product_project_slug": stem})


def external_product_info_path_for_slug(slug):
    safe_slug = product_project_slug({"product_project_slug": slug}) if slug else ""
    if not safe_slug:
        return None
    for path in external_product_info_files():
        if product_info_slug_from_path(path) == safe_slug:
            return path
    return None


def external_product_info_path_for_config(config):
    return external_product_info_path_for_slug(str((config or {}).get("product_project_slug", "") or "").strip())


def apply_external_product_info_fields(config):
    external_path = external_product_info_path_for_config(config)
    if not external_path:
        return config
    config["script_product_document_path"] = external_path.as_posix()
    config["product_profile_path"] = external_path.as_posix()
    mistake_book_path = product_mistake_book_path_for_config(config)
    config["script_content_knowledge_base_path"] = (
        mistake_book_path.as_posix()
        if mistake_book_path
        else DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH
    )
    return config


def hot_script_dir_for_config(config):
    candidates = []
    external_path = external_product_info_path_for_config(config)
    if external_path and external_path.exists():
        try:
            text = external_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        candidates.extend(
            value
            for value in [
                markdown_meta_value(text, "project"),
                markdown_title(text).split("·", 1)[0].strip(),
                external_path.stem.replace("-产品信息", "").strip(),
            ]
            if value
        )
    profile = normalize_product_profile((config or {}).get("product_profile", {}))
    candidates.extend(
        value
        for value in [
            profile.get("product_name", ""),
            profile.get("english_name", ""),
            str((config or {}).get("product_project_slug", "") or "").replace("-产品信息", "").strip(),
        ]
        if value
    )
    for name in candidates:
        direct = HOT_SCRIPT_SOURCE_ROOT / name
        if direct.is_dir():
            return direct
    normalized_candidates = {product_project_slug({"product_project_slug": name}) for name in candidates}
    if HOT_SCRIPT_SOURCE_ROOT.exists():
        for path in HOT_SCRIPT_SOURCE_ROOT.iterdir():
            if path.is_dir() and product_project_slug({"product_project_slug": path.name}) in normalized_candidates:
                return path
    return None


def product_name_candidates_for_config(config):
    candidates = []
    external_path = external_product_info_path_for_config(config)
    if external_path and external_path.exists():
        try:
            text = external_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        candidates.extend(
            value
            for value in [
                markdown_meta_value(text, "project"),
                markdown_title(text).split("·", 1)[0].strip(),
                external_path.stem.replace("-产品信息", "").strip(),
            ]
            if value
        )
    profile = normalize_product_profile((config or {}).get("product_profile", {}))
    candidates.extend(
        value
        for value in [
            profile.get("product_name", ""),
            profile.get("english_name", ""),
            str((config or {}).get("product_project_slug", "") or "").replace("-产品信息", "").strip(),
        ]
        if value
    )
    deduped = []
    for value in candidates:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def mapped_dir_for_config(config, root):
    candidates = product_name_candidates_for_config(config)
    for name in candidates:
        direct = root / name
        if direct.is_dir():
            return direct
    normalized_candidates = {product_project_slug({"product_project_slug": name}) for name in candidates}
    if root.exists():
        for path in root.iterdir():
            if path.is_dir() and product_project_slug({"product_project_slug": path.name}) in normalized_candidates:
                return path
    return None


def mapped_markdown_file_for_config(config, root):
    candidates = product_name_candidates_for_config(config)
    for name in candidates:
        direct = root / f"{name}.md"
        if direct.is_file():
            return direct
    normalized_candidates = {product_project_slug({"product_project_slug": name}) for name in candidates}
    if root.exists():
        for path in root.glob("*.md"):
            if product_project_slug({"product_project_slug": path.stem}) in normalized_candidates:
                return path
    return None


def product_mistake_book_path_for_config(config):
    return mapped_markdown_file_for_config(config, SCRIPT_MISTAKE_BOOK_SOURCE_ROOT)


def hot_video_dir_for_config(config):
    return mapped_dir_for_config(config, HOT_VIDEO_SOURCE_ROOT)


def product_output_dir_for_config(config):
    mapped = mapped_dir_for_config(config, SCRIPT_OUTPUT_SOURCE_ROOT)
    if mapped:
        return mapped
    candidates = product_name_candidates_for_config(config)
    name = candidates[0] if candidates else product_project_slug(config).replace("-产品信息", "").strip()
    return SCRIPT_OUTPUT_SOURCE_ROOT / (name or "未命名产品")


def product_script_output_name(config):
    product_doc = str((config or {}).get("script_product_document_path", "") or "").strip()
    if product_doc:
        name = Path(product_doc).expanduser().stem.replace("-产品信息", "").strip()
        if name:
            return safe_name(name, "未命名产品", 120)
    candidates = product_name_candidates_for_config(config)
    return safe_name(candidates[0] if candidates else product_project_slug(config).replace("-产品信息", "").strip(), "未命名产品", 120)


def split_country_prefix_from_reference_stem(stem):
    parts = str(stem or "").split("-", 2)
    if len(parts) >= 3 and re.fullmatch(r"[A-Za-z]{2,6}", parts[0] or "") and parts[2]:
        return parts[0].upper(), f"{parts[1]}-{parts[2]}"
    return "", str(stem or "")


def reference_country_author_and_video_id(path):
    path = Path(path)
    country, core_stem = split_country_prefix_from_reference_stem(path.stem)
    parts = core_stem.split("-", 2)
    if len(parts) >= 2 and parts[1].isdigit():
        return country, safe_name(parts[0], "unknown_user", 120), parts[1]
    return country, "unknown_user", infer_source_id(core_stem or path)


def source_key_for_reference(path):
    country, author, video_id = reference_country_author_and_video_id(path)
    return f"{country}-{author}-{video_id}" if country else f"{author}-{video_id}"


def reference_author_and_video_id(path):
    _country, author, video_id = reference_country_author_and_video_id(path)
    return author, video_id


def parse_script_output_stem(stem):
    raw_stem = re.sub(r"_\d{3}$", "", str(stem or ""))
    stage = ""
    rest = raw_stem
    for prefix in ("复刻-", "裂变-"):
        if rest.startswith(prefix):
            stage = prefix[:-1]
            rest = rest[len(prefix):]
            break
    parts = rest.split("-")
    video_index = None
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].isdigit():
            video_index = index
            break
    if video_index is None or video_index < 1:
        return {
            "stage": stage or "脚本",
            "product_name": "",
            "source_country": "",
            "source_author": "",
            "source_video_id": "",
            "source_key": raw_stem,
        }

    video_id = parts[video_index]
    author = safe_name(parts[video_index - 1], "unknown_user", 120)
    country = ""
    product_parts = parts[: video_index - 1]
    if product_parts and re.fullmatch(r"[A-Za-z]{2,6}", product_parts[-1] or ""):
        country = product_parts[-1].upper()
        product_parts = product_parts[:-1]
    source_key = f"{country}-{author}-{video_id}" if country else f"{author}-{video_id}"
    return {
        "stage": stage or "脚本",
        "product_name": "-".join(product_parts),
        "source_country": country,
        "source_author": author,
        "source_video_id": video_id,
        "source_key": source_key,
    }


def clone_output_paths_for_reference(config, reference_path, output_dir=None):
    output_dir = output_dir or product_output_dir_for_config(config)
    country, author, video_id = reference_country_author_and_video_id(reference_path)
    product_name = product_script_output_name(config)
    source_part = f"{country}-{author}-{video_id}" if country else f"{author}-{video_id}"
    stem = f"复刻-{product_name}-{source_part}"
    return output_dir / f"{stem}.md", output_dir / f"{stem}.raw.json"


def mutation_enabled(config):
    value = config.get("script_enable_mutation_rewrite")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def clone_path_for_current_reference(config):
    raw_path = str(config.get("script_reference_analysis_path", "") or "").strip()
    if not raw_path:
        return None
    reference_path = resolve_ui_path(raw_path)
    clone_path, _ = clone_output_paths_for_reference(config, reference_path, product_output_dir_for_config(config))
    return clone_path


def product_mistake_book_cache_path(config):
    slug = product_project_slug(config)
    return WORKFLOW_CONFIG_DIR / "script_generation" / "config" / f"{slug}_mistake_book.md"


def build_product_mistake_book_file(config):
    mistake_book_path = product_mistake_book_path_for_config(config)
    if not mistake_book_path:
        return None
    try:
        text = mistake_book_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    parts = [
        f"# 错题本\n",
        f"来源文件：{mistake_book_path.as_posix()}\n",
        f"\n\n---\n\n## {mistake_book_path.name}\n\n{text}",
    ]
    cache_path = product_mistake_book_cache_path(config)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return cache_path


def hot_script_files_for_config(config):
    script_dir = hot_script_dir_for_config(config)
    if not script_dir:
        return []
    return sorted(script_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def hot_video_path_for_reference(config, reference_path):
    video_dir = hot_video_dir_for_config(config)
    if not video_dir:
        return None
    reference_stem = Path(reference_path).stem
    _country, core_reference_stem = split_country_prefix_from_reference_stem(reference_stem)
    for suffix in (".mp4", ".mov", ".m4v"):
        candidate = video_dir / f"{reference_stem}{suffix}"
        if candidate.exists():
            return candidate
        if core_reference_stem != reference_stem:
            candidate = video_dir / f"{core_reference_stem}{suffix}"
            if candidate.exists():
                return candidate
    for path in video_dir.glob("*"):
        if (
            path.is_file()
            and path.suffix.lower() in {".mp4", ".mov", ".m4v"}
            and path.stem in {reference_stem, core_reference_stem}
        ):
            return path
    return None


def product_profile_for_slug(slug):
    safe_slug = product_project_slug({"product_project_slug": slug}) if slug else ""
    if not safe_slug:
        return DEFAULT_PRODUCT_PROFILE.copy()
    external_path = external_product_info_path_for_slug(safe_slug)
    if external_path:
        return product_profile_from_external_markdown(external_path)
    path = ROOT / "projects" / safe_slug / "product_profile" / "current_product_profile.md"
    if not path.exists():
        return DEFAULT_PRODUCT_PROFILE.copy()
    return product_profile_from_markdown(path.read_text(encoding="utf-8"))


def product_project_display_name(slug, profile=None):
    profile = normalize_product_profile(profile or {})
    english_name = str(profile.get("english_name", "") or "").strip()
    product_name = str(profile.get("product_name", "") or "").strip()
    if english_name and product_name and english_name != product_name:
        return f"{english_name} / {product_name}"
    return english_name or product_name or slug


def list_product_projects():
    items = []
    seen_slugs = set()
    for source_path in external_product_info_files():
        slug = product_info_slug_from_path(source_path)
        profile = product_profile_from_external_markdown(source_path)
        items.append(
            {
                "slug": slug,
                "name": product_project_display_name(slug, profile),
                "root": PRODUCT_INFO_SOURCE_DIR.as_posix(),
                "profile_path": source_path.as_posix(),
                "product_name": profile.get("product_name", ""),
                "english_name": profile.get("english_name", ""),
                "ready": True,
                "source": "product_info_markdown",
            }
        )
        seen_slugs.add(slug)

    projects_root = ROOT / "projects"
    if items:
        return items
    if not projects_root.exists():
        return items
    for project_dir in sorted([path for path in projects_root.iterdir() if path.is_dir()], key=lambda p: p.name.lower()):
        slug = project_dir.name
        if slug == "current_product":
            continue
        if slug in seen_slugs:
            continue
        profile = product_profile_for_slug(slug)
        profile_path = project_dir / "product_profile" / "current_product_profile.md"
        items.append(
            {
                "slug": slug,
                "name": product_project_display_name(slug, profile),
                "root": project_relative(project_dir),
                "profile_path": project_relative(profile_path) if profile_path.exists() else "",
                "product_name": profile.get("product_name", ""),
                "english_name": profile.get("english_name", ""),
                "ready": profile_path.exists() or has_product_identity({"product_profile": profile}),
            }
        )
    return items


def clear_other_project_paths(config, selected_project_root):
    selected_prefix = project_relative(selected_project_root).rstrip("/") + "/"
    for field in PROJECT_SCOPED_PATH_FIELDS:
        value = str(config.get(field, "") or "").strip()
        if value.startswith("projects/") and not value.startswith(selected_prefix):
            config[field] = ""
    return config


def has_product_identity(config):
    profile = normalize_product_profile((config or {}).get("product_profile", {}))
    return any(str(profile.get(field, "")).strip() for field in PRODUCT_IDENTITY_FIELDS)


def has_declared_product_project(config):
    config = config or {}
    configured_slug = str(config.get("product_project_slug", "") or "").strip()
    if configured_slug and configured_slug != "current_product":
        return True
    return has_product_identity(config)


def apply_product_project_fields(config):
    if not has_declared_product_project(config):
        config["product_project_slug"] = ""
        config["product_profile_path"] = ""
        if str(config.get("data_attribution_download_output_dir", "") or "").strip() == "metrics/raw_downloads":
            config["data_attribution_download_output_dir"] = ""
        return config

    config["product_project_slug"] = product_project_slug(config)
    config["product_profile_path"] = project_relative(project_product_profile_path(config))
    apply_external_product_info_fields(config)
    if not str(config.get("data_attribution_download_output_dir", "") or "").strip() or config.get(
        "data_attribution_download_output_dir"
    ) == "metrics/raw_downloads":
        config["data_attribution_download_output_dir"] = project_relative(product_project_root(config) / "raw_data")
    return config


def product_project_ready(config):
    config = config or {}
    slug = str(config.get("product_project_slug", "") or "").strip()
    if not slug or slug == "current_product":
        return False
    return has_product_identity(config) or project_product_profile_path(config).exists()


def require_product_project(config, action="继续操作"):
    if not product_project_ready(config):
        raise ValueError(f"请先选择已有产品信息 Markdown，再{action}")
    return config


def display_path(value):
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if path.is_absolute():
        return project_relative(path)
    return path.as_posix()


def is_preserve_script_value(value):
    return str(value or "").strip() in {"", SCRIPT_PRESERVE_ORIGINAL_VALUE, "跟随原脚本", "保持原脚本", "不变"}


def normalize_script_target_language(country, target_language):
    country_text = str(country or "").strip()
    language_text = str(target_language or "").strip()
    if is_preserve_script_value(language_text):
        return language_text or SCRIPT_PRESERVE_ORIGINAL_VALUE
    language_key = language_text.lower()
    country_key = country_text.lower()
    if language_text in COUNTRY_DEFAULT_LANGUAGE or language_key in COUNTRY_DEFAULT_LANGUAGE:
        return COUNTRY_DEFAULT_LANGUAGE.get(language_text) or COUNTRY_DEFAULT_LANGUAGE.get(language_key) or language_text
    if country_text and language_text == country_text:
        return COUNTRY_DEFAULT_LANGUAGE.get(country_text) or COUNTRY_DEFAULT_LANGUAGE.get(country_key) or language_text
    return language_text


def resolve_ui_path(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    path = Path(unquote(raw_value)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def save_config(config):
    config = load_unified_console_config() | config
    category_path = config.get("category_path", [])
    if isinstance(category_path, str):
        category_path = [part.strip() for part in category_path.split(">") if part.strip()]
    if category_path and category_path[0] != "全部" and len(category_path) < 1:
        raise ValueError("请选择商品分类")
    config["category_path"] = category_path
    product_types = config.get("product_types", [])
    if isinstance(product_types, str):
        product_types = [part.strip() for part in product_types.split(",") if part.strip()]
    config["product_types"] = product_types
    for field in [
        "shop_type",
        "product_status",
        "creator_conversion_rate_filter",
        "total_sales_filter",
        "total_gmv_filter",
        "sales_7d_filter",
        "gmv_7d_filter",
        "creator_count_filter",
        "commission_rate_filter",
        "shipping_method_filter",
    ]:
        config[field] = str(config.get(field, DEFAULT_CONFIG.get(field, "全部")) or "全部").strip()
    config["product_limit"] = int(config.get("product_limit", 3))
    config["videos_per_product"] = int(config.get("videos_per_product", 20))
    config["show_browser"] = bool(config.get("show_browser", False))
    config["modelmesh_api_key"] = str(config.get("modelmesh_api_key", ""))
    config["modelmesh_base_url"] = str(config.get("modelmesh_base_url", DEFAULT_CONFIG["modelmesh_base_url"])).strip()
    config["video_analysis_model"] = str(config.get("video_analysis_model", DEFAULT_CONFIG["video_analysis_model"])).strip()
    normalize_workflow_config_paths(config)
    if str(config.get("video_analysis_prompt", "") or "").strip():
        write_video_analysis_prompt(config, config.get("video_analysis_prompt", ""))
    config["video_analysis_prompt"] = ""
    config["video_teardown_knowledge_base_path"] = normalize_teardown_knowledge_base_path(
        config.get("video_teardown_knowledge_base_path", DEFAULT_CONFIG["video_teardown_knowledge_base_path"])
    )
    config["video_analysis_max_output_tokens"] = int(config.get("video_analysis_max_output_tokens", 32768))
    config["analysis_input_path"] = str(config.get("analysis_input_path", "")).strip()
    config["product_profile"] = normalize_product_profile(config.get("product_profile", {}))
    normalize_data_attribution_config(config)
    config.pop("analysis_video_limit", None)
    config.pop("script_material_framework", None)
    config.pop("script_reference_case", None)
    config = save_unified_console_config(config)
    return config


def save_collect_config(payload):
    config = save_config(payload)
    return config


def resolve_project_path(raw_path, default_path=None):
    raw_path = str(raw_path or "").strip()
    if not raw_path and default_path:
        return default_path.resolve()
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def resolve_teardown_knowledge_base_path(config):
    return resolve_project_path(
        normalize_teardown_knowledge_base_path(
            config.get("video_teardown_knowledge_base_path", DEFAULT_CONFIG["video_teardown_knowledge_base_path"])
        ),
        DEFAULT_TEARDOWN_KNOWLEDGE_BASE_PATH,
    )


def resolve_video_analysis_prompt_path(config):
    return resolve_project_path(
        config.get("video_analysis_prompt_path", DEFAULT_CONFIG["video_analysis_prompt_path"]),
        DEFAULT_VIDEO_ANALYSIS_PROMPT_PATH,
    )


def resolve_script_generation_prompt_path(config):
    return resolve_project_path(
        config.get("script_generation_prompt_path", DEFAULT_CONFIG["script_generation_prompt_path"]),
        DEFAULT_SCRIPT_GENERATION_PROMPT_PATH,
    )


def resolve_script_adaptation_prompt_path(config):
    return resolve_project_path(
        config.get("script_adaptation_prompt_path", DEFAULT_CONFIG["script_adaptation_prompt_path"]),
        DEFAULT_SCRIPT_ADAPTATION_PROMPT_PATH,
    )


def resolve_product_profile_path(config):
    return project_product_profile_path(config)


def product_profile_to_markdown(profile):
    lines = ["# 产品信息"]
    for field in PRODUCT_PROFILE_FIELDS:
        value = str((profile or {}).get(field, "") or "").strip()
        if value:
            lines.append(f"## {PRODUCT_PROFILE_FIELD_LABELS.get(field, field)}\n{value}")
    if len(lines) == 1:
        lines.append("未填写产品信息。")
    return "\n\n".join(lines).rstrip() + "\n"


def write_product_profile_file(config):
    ensure_project_dirs(config)
    path = resolve_product_profile_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(product_profile_to_markdown(config.get("product_profile", {})), encoding="utf-8")
    return path


def read_teardown_knowledge_base(config):
    path = resolve_teardown_knowledge_base_path(config)
    candidates = [path]
    if path != DEFAULT_TEARDOWN_KNOWLEDGE_BASE_PATH:
        candidates.append(DEFAULT_TEARDOWN_KNOWLEDGE_BASE_PATH)
    if LEGACY_TEARDOWN_KNOWLEDGE_BASE_PATH not in candidates:
        candidates.append(LEGACY_TEARDOWN_KNOWLEDGE_BASE_PATH)
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def read_video_analysis_prompt(config):
    path = resolve_video_analysis_prompt_path(config)
    if path.exists():
        return path.read_text(encoding="utf-8")
    inline = str(config.get("video_analysis_prompt", "") or "")
    return inline


def read_script_generation_prompt(config):
    path = resolve_script_generation_prompt_path(config)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_script_adaptation_prompt(config):
    path = resolve_script_adaptation_prompt_path(config)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_teardown_knowledge_base(config, text):
    path = resolve_teardown_knowledge_base_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or "").rstrip() + "\n", encoding="utf-8")
    return path


def write_video_analysis_prompt(config, text):
    path = resolve_video_analysis_prompt_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or "").rstrip() + "\n", encoding="utf-8")
    return path


def write_script_generation_prompt(config, text):
    path = resolve_script_generation_prompt_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or "").rstrip() + "\n", encoding="utf-8")
    return path


def write_script_adaptation_prompt(config, text):
    path = resolve_script_adaptation_prompt_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or "").rstrip() + "\n", encoding="utf-8")
    return path


def config_payload():
    config = load_unified_console_config()
    config["product_projects"] = list_product_projects()
    config["workflow_input_paths"] = {
        "unified_console": display_path(UNIFIED_CONSOLE_INPUT_PATH),
        **{
            stage: display_path(path)
            for stage, path in ((stage, workflow_input_path(stage)) for stage in WORKFLOW_INPUT_FILES)
        },
    }
    for field in PATH_DISPLAY_FIELDS:
        if field in config:
            config[field] = display_path(config.get(field, ""))
    config["video_analysis_prompt"] = config.get("video_analysis_prompt") or read_video_analysis_prompt(config)
    config["script_generation_prompt"] = config.get("script_generation_prompt") or read_script_generation_prompt(config)
    config["script_adaptation_prompt"] = config.get("script_adaptation_prompt") or read_script_adaptation_prompt(config)
    return config


def fastmoss_category_tree_payload():
    fallback = {
        "top_categories": ["全部", "美妆个护"],
        "category_tree": {
            "美妆个护": {
                "头部护理与造型": ["染发用品"],
            }
        },
    }
    if not CATEGORY_TREE_PATH.exists():
        return fallback
    data = json.loads(CATEGORY_TREE_PATH.read_text(encoding="utf-8"))
    top_categories = data.get("top_categories") or fallback["top_categories"]
    category_tree = data.get("category_tree") or fallback["category_tree"]
    if "全部" not in top_categories:
        top_categories = ["全部", *top_categories]
    return {"top_categories": top_categories, "category_tree": category_tree}


def save_teardown_defaults(payload):
    config = load_unified_console_config()
    config["modelmesh_api_key"] = str(payload.get("modelmesh_api_key", config.get("modelmesh_api_key", ""))).strip()
    config["modelmesh_base_url"] = str(
        payload.get("modelmesh_base_url", config.get("modelmesh_base_url", DEFAULT_CONFIG["modelmesh_base_url"]))
    ).strip()
    config["video_analysis_model"] = str(
        payload.get("video_analysis_model", config.get("video_analysis_model", DEFAULT_CONFIG["video_analysis_model"]))
    ).strip()
    if "video_analysis_prompt_path" in payload:
        config["video_analysis_prompt_path"] = str(
            payload.get(
                "video_analysis_prompt_path",
                config.get("video_analysis_prompt_path", DEFAULT_CONFIG["video_analysis_prompt_path"]),
            )
        ).strip()
    normalize_workflow_config_paths(config)
    if "video_analysis_prompt" in payload:
        config["video_analysis_prompt"] = str(payload.get("video_analysis_prompt", "") or "")
    config["video_teardown_knowledge_base_path"] = normalize_teardown_knowledge_base_path(
        payload.get(
            "video_teardown_knowledge_base_path",
            config.get("video_teardown_knowledge_base_path", DEFAULT_CONFIG["video_teardown_knowledge_base_path"]),
        )
    )
    if "analysis_input_path" in payload:
        config["analysis_input_path"] = str(payload.get("analysis_input_path", config.get("analysis_input_path", ""))).strip()
    config["video_analysis_max_output_tokens"] = int(config.get("video_analysis_max_output_tokens", 32768))
    config.pop("analysis_video_limit", None)
    config = save_unified_console_config(config)
    return config


def save_script_defaults(payload):
    config = load_unified_console_config()
    if "script_content_knowledge_base_path" in payload:
        config["script_content_knowledge_base_path"] = normalize_script_content_knowledge_base_path(
            payload.get(
                "script_content_knowledge_base_path",
                config.get("script_content_knowledge_base_path", DEFAULT_SCRIPT_CONTENT_KNOWLEDGE_BASE_CONFIG_PATH),
            ),
        )
    config["script_generation_prompt_path"] = str(
        payload.get(
            "script_generation_prompt_path",
            config.get("script_generation_prompt_path", DEFAULT_CONFIG["script_generation_prompt_path"]),
        )
    ).strip()
    config["script_generation_backend"] = str(
        payload.get("script_generation_backend", config.get("script_generation_backend", "api"))
    ).strip() or "api"
    config["script_obsidian_cli_command"] = str(
        payload.get("script_obsidian_cli_command", config.get("script_obsidian_cli_command", ""))
    ).strip()
    config["script_obsidian_vault_path"] = str(
        payload.get("script_obsidian_vault_path", config.get("script_obsidian_vault_path", ""))
    ).strip()
    config["script_use_generation_prompt"] = True
    if "script_enable_mutation_rewrite" in payload:
        config["script_enable_mutation_rewrite"] = bool(payload.get("script_enable_mutation_rewrite"))
    config["script_mutation_mode"] = normalize_script_mutation_mode(
        payload.get("script_mutation_mode", config.get("script_mutation_mode", "standard"))
    )
    config["script_generation_mutation_prompt_path"] = mutation_prompt_config_path_for_mode(
        config.get("script_mutation_mode")
    )
    try:
        mutation_variants = int(payload.get("script_mutation_variants", config.get("script_mutation_variants", 3)) or 3)
    except (TypeError, ValueError):
        mutation_variants = 3
    config["script_mutation_variants"] = max(1, mutation_variants)
    config["script_mutation_source"] = "复刻稿"
    normalize_workflow_config_paths(config)
    config["script_reference_analysis_path"] = str(
        payload.get("script_reference_analysis_path", config.get("script_reference_analysis_path", ""))
    ).strip()
    config["script_country"] = str(
        payload.get("script_country", config.get("script_country", SCRIPT_PRESERVE_ORIGINAL_VALUE))
    ).strip() or SCRIPT_PRESERVE_ORIGINAL_VALUE
    config["script_target_language"] = str(
        payload.get("script_target_language", config.get("script_target_language", SCRIPT_PRESERVE_ORIGINAL_VALUE))
    ).strip() or SCRIPT_PRESERVE_ORIGINAL_VALUE
    config["script_target_language"] = normalize_script_target_language(
        config.get("script_country", ""), config.get("script_target_language", "")
    )
    config["script_total_duration"] = str(
        payload.get("script_total_duration", config.get("script_total_duration", SCRIPT_PRESERVE_ORIGINAL_VALUE))
    ).strip() or SCRIPT_PRESERVE_ORIGINAL_VALUE
    config.pop("script_hook_duration", None)
    if "script_generation_prompt" in payload:
        config["script_generation_prompt"] = str(payload.get("script_generation_prompt", "") or "")
    config = save_unified_console_config(config)
    invalidate_file_listing_cache()
    return config


CONTENT_WORKFLOW_FIELDS = [
    "script_adaptation_input_path",
    "script_adaptation_prompt_path",
    "script_adaptation_target_model",
    "script_adaptation_segment_seconds",
    "script_adaptation_notes",
    "clip_assembly_input_dir",
    "clip_assembly_output_name",
    "clip_assembly_notes",
    "video_publish_input_path",
    "video_publish_account",
    "video_publish_caption",
    "video_publish_tags",
    "video_publish_mode",
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
    "script_optimization_input_path",
    "script_optimization_metrics_path",
    "script_optimization_notes",
]


def save_content_workflow_defaults(payload):
    config = load_unified_console_config()
    if "video_teardown_knowledge_base_path" in payload:
        config["video_teardown_knowledge_base_path"] = normalize_teardown_knowledge_base_path(
            payload.get("video_teardown_knowledge_base_path", config.get("video_teardown_knowledge_base_path", ""))
        )
    for field in CONTENT_WORKFLOW_FIELDS:
        if field in payload:
            config[field] = payload.get(field, DEFAULT_CONFIG.get(field, ""))
    normalize_workflow_config_paths(config)
    config["script_adaptation_segment_seconds"] = int(config.get("script_adaptation_segment_seconds") or 8)
    if "script_adaptation_prompt" in payload:
        config["script_adaptation_prompt"] = str(payload.get("script_adaptation_prompt", "") or "")
    config = save_unified_console_config(config)
    return config


def save_product_profile(payload):
    config = load_unified_console_config()
    profile = payload.get("product_profile", payload)
    config["product_profile"] = normalize_product_profile(profile)
    if not has_product_identity(config):
        raise ValueError("请至少填写产品名或英文名，用来创建产品资料")
    if not config.get("product_project_slug") or config.get("product_project_slug") == "current_product":
        config_for_slug = config | {"product_project_slug": ""}
        config["product_project_slug"] = product_project_slug(config_for_slug)
    existing_product_doc = external_product_info_path_for_slug(config.get("product_project_slug"))
    if existing_product_doc:
        config["product_profile_path"] = existing_product_doc.as_posix()
        config["script_product_document_path"] = existing_product_doc.as_posix()
    write_unified_console_inputs(normalize_unified_config(config))
    invalidate_file_listing_cache()
    return config["product_profile"]


def select_product_project(payload):
    requested_slug = str((payload or {}).get("slug", "") or "").strip()
    config = load_unified_console_config()
    if not requested_slug:
        config["product_project_slug"] = ""
        config["product_profile"] = DEFAULT_PRODUCT_PROFILE.copy()
        config["product_profile_path"] = ""
        config["product_project_root"] = ""
        config["script_product_document_path"] = ""
        write_unified_console_inputs(normalize_unified_config(config))
        invalidate_file_listing_cache()
        return config_payload()

    safe_slug = product_project_slug({"product_project_slug": requested_slug})
    projects = {item["slug"]: item for item in list_product_projects()}
    if safe_slug not in projects:
        raise ValueError(f"产品信息 Markdown 不存在: {safe_slug}")

    external_path = external_product_info_path_for_slug(safe_slug)
    if not external_path:
        raise ValueError(f"产品信息 Markdown 不存在: {safe_slug}")
    config["script_product_document_path"] = external_path.as_posix()
    config["product_profile_path"] = external_path.as_posix()
    config["product_project_slug"] = safe_slug
    config["product_profile"] = product_profile_from_external_markdown(external_path)
    config["product_project_root"] = PRODUCT_INFO_SOURCE_DIR.as_posix()
    hot_scripts = hot_script_files_for_config(config)
    config["script_reference_analysis_path"] = hot_scripts[0].as_posix() if hot_scripts else ""
    config["analysis_input_path"] = product_subdir(HOT_VIDEO_SOURCE_ROOT, config).as_posix()
    config["clip_assembly_input_dir"] = (SCRIPT_ADAPTED_SOURCE_ROOT / str(config.get("script_adaptation_target_model", "omni") or "omni") / unified_product_name(config)).as_posix()
    config["data_attribution_download_output_dir"] = ""
    write_unified_console_inputs(normalize_unified_config(config))
    invalidate_file_listing_cache()
    return config_payload()


def file_listing():
    config = load_unified_console_config()
    if not config.get("product_project_ready"):
        return {
            "product_project_root": "",
            "product_project_ready": False,
            "csv_files": [],
            "download_dirs": [],
            "analysis_files": [],
            "hot_script_files": [],
            "script_files": [],
            "adapted_script_files": [],
            "assembled_video_files": [],
            "publish_record_files": [],
            "metrics_files": [],
            "metrics_summary_tables": [],
            "optimization_files": [],
        }
    project_root = product_project_root(config)

    def item(path):
        return {
            "name": path.name,
            "path": display_path(path),
            "size": path.stat().st_size if path.is_file() else 0,
            "mtime": path.stat().st_mtime,
        }

    collection_root = project_root / "collection_runs"
    csv_files = [
        item(path)
        for path in sorted(collection_root.rglob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    ] if collection_root.exists() else []
    download_dirs = []
    hot_sources_root = project_root / "hot_sources"
    source_dirs = sorted(hot_sources_root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) if hot_sources_root.exists() else []
    for source_dir in source_dirs:
        source_path = source_dir / "source"
        if source_path.is_dir():
            count = len(list(source_path.glob("*.mp4")))
            if count:
                download_dirs.append({"name": source_dir.name, "path": display_path(source_path), "count": count, "mtime": source_path.stat().st_mtime})
    script_output_dir = product_output_dir_for_config(config)
    hot_script_dir = hot_script_dir_for_config(config)

    def hot_script_item(path):
        data = item(path)
        clone_path, clone_raw_path = clone_output_paths_for_reference(config, path, script_output_dir)
        cloned = clone_path.exists()
        video_path = hot_video_path_for_reference(config, path)
        country, author, video_id = reference_country_author_and_video_id(path)
        source_key = source_key_for_reference(path)
        mutation_count = len(list(script_output_dir.glob(f"裂变-{product_script_output_name(config)}-{source_key}*.md")))
        data.update(
            {
                "clone_status": "已复刻" if cloned else "未复刻",
                "clone_path": display_path(clone_path) if clone_path.exists() else "",
                "expected_clone_path": display_path(clone_path),
                "mutation_count": mutation_count,
                "source_country": country,
                "source_author": author,
                "source_video_id": video_id,
                "source_key": source_key,
                "source_video_path": display_path(video_path) if video_path else "",
                "source_video_name": video_path.name if video_path else "",
            }
        )
        return data

    analysis_files = [hot_script_item(path) for path in hot_script_files_for_config(config)]

    hot_script_sources = []
    for source in analysis_files:
        source_key = source.get("source_key", "")
        if source_key:
            hot_script_sources.append(source)

    def read_script_raw_metadata(path):
        raw_path = path.with_suffix(".raw.json")
        if not raw_path.exists():
            return {}
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        nested = raw.get("mutation_rewrite_raw") if isinstance(raw, dict) else {}
        return {
            "raw_path": display_path(raw_path),
            "final_stage": raw.get("final_stage", "") if isinstance(raw, dict) else "",
            "mutation_run_id": raw.get("mutation_run_id", "") if isinstance(raw, dict) else "",
            "mutation_mode": raw.get("mutation_mode", "") if isinstance(raw, dict) else "",
            "mutation_source_stage": raw.get("mutation_source_stage", "") if isinstance(raw, dict) else "",
            "mutation_source_path": raw.get("mutation_source_path", "") if isinstance(raw, dict) else "",
            "clone_source_path": raw.get("clone_source_path", "") if isinstance(raw, dict) else "",
            "expected_clone_path": raw.get("expected_clone_path", "") if isinstance(raw, dict) else "",
            "source_reference_path": raw.get("source_reference_path", "") if isinstance(raw, dict) else "",
            "saved_variant_index": raw.get("saved_variant_index") if isinstance(raw, dict) else None,
            "saved_variant_count": raw.get("saved_variant_count") if isinstance(raw, dict) else None,
            "target_language": (
                (nested.get("target_language") if isinstance(nested, dict) else "")
                or (raw.get("target_language") if isinstance(raw, dict) else "")
                or ""
            ),
            "requested_variant_count": nested.get("requested_variant_count") if isinstance(nested, dict) else None,
            "received_variant_count": nested.get("received_variant_count") if isinstance(nested, dict) else None,
            "source_country": raw.get("source_country", "") if isinstance(raw, dict) else "",
            "source_author": raw.get("source_author", "") if isinstance(raw, dict) else "",
            "source_video_id": raw.get("source_video_id", "") if isinstance(raw, dict) else "",
            "source_key": raw.get("source_key", "") if isinstance(raw, dict) else "",
        }

    def script_output_item(path):
        data = item(path)
        stem = path.stem
        parsed_output = parse_script_output_stem(stem)
        data["output_stage"] = parsed_output.get("stage") or ("裂变" if stem.startswith("裂变-") else ("复刻" if stem.startswith("复刻-") else "脚本"))
        data.update(read_script_raw_metadata(path))
        matched_source = None
        for source in hot_script_sources:
            source_key = source.get("source_key", "")
            if source_key and f"-{source_key}" in stem:
                matched_source = source
                break
        if matched_source:
            data.update(
                {
                    "source_key": matched_source.get("source_key", ""),
                    "source_script_name": matched_source.get("name", ""),
                    "source_script_path": matched_source.get("path", ""),
                    "source_video_name": matched_source.get("source_video_name", ""),
                    "source_video_path": matched_source.get("source_video_path", ""),
                    "source_country": matched_source.get("source_country", ""),
                    "source_author": matched_source.get("source_author", ""),
                    "source_video_id": matched_source.get("source_video_id", ""),
                    "expected_clone_path": data.get("expected_clone_path") or matched_source.get("expected_clone_path", ""),
                    "clone_source_path": data.get("clone_source_path") or matched_source.get("clone_path", ""),
                }
            )
        else:
            data["source_key"] = data.get("source_key") or parsed_output.get("source_key") or re.sub(r"_\d{3}$", "", stem)
            data["source_country"] = data.get("source_country") or parsed_output.get("source_country", "")
            data["source_author"] = data.get("source_author") or parsed_output.get("source_author", "")
            data["source_video_id"] = data.get("source_video_id") or parsed_output.get("source_video_id", "")
            data["source_script_name"] = ""
            data["source_script_path"] = ""
            data["source_video_name"] = ""
            data["source_video_path"] = ""
        return data

    script_output_paths = [
        path
        for path in sorted(script_output_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if path.is_file()
    ]
    script_files = [script_output_item(path) for path in script_output_paths[:80]]
    adapted_dir = Path((config.get("unified_agent_paths") or {}).get("adapt_output_dir") or "")
    adaptation_candidates = list(adapted_dir.rglob("*")) if adapted_dir.exists() else []
    if hot_sources_root.exists():
        adaptation_candidates.extend((project_root / "hot_sources").glob("*/adaptations/**/*"))
    product_report_adapt_dir = project_root / "product_level_reports" / "script_adaptations"
    if product_report_adapt_dir.exists():
        adaptation_candidates.extend(product_report_adapt_dir.glob("*"))
    adapted_script_files = [
        item(path)
        for path in sorted(adaptation_candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:120]
        if path.is_file()
        and (
            path.suffix.lower() in {".md", ".csv"}
            or path.name.endswith("_image_prompts.json")
        )
    ]
    assemble_dir = Path((config.get("unified_agent_paths") or {}).get("assemble_output_dir") or "")
    assembled_candidates = list(assemble_dir.rglob("*")) if assemble_dir.exists() else []
    if hot_sources_root.exists():
        assembled_candidates.extend((project_root / "hot_sources").glob("*/generated_videos/**/*"))
    assembled_video_files = [
        item(path)
        for path in sorted(assembled_candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:80]
        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".md", ".json"}
    ]
    publish_record_files = [
        item(path)
        for path in sorted((project_root / "hot_sources").glob("*/publish_records/**/*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:80]
    ] if hot_sources_root.exists() else []
    metrics_root = project_root / "product_level_reports" / "data_attribution"
    metrics_files = [
        item(path)
        for path in sorted(metrics_root.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:80]
        if path.is_file() and path.suffix.lower() in {".md", ".json", ".csv"}
    ] if metrics_root.exists() else []
    metrics_summary_tables = [
        item(path)
        for path in sorted(metrics_root.glob("*作品归因汇总*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
        if path.is_file()
    ] if metrics_root.exists() else []
    optimization_root = project_root / "product_level_reports" / "script_optimizations"
    optimization_candidates = []
    if hot_sources_root.exists():
        optimization_candidates.extend((project_root / "hot_sources").glob("*/optimizations/**/*.md"))
    if optimization_root.exists():
        optimization_candidates.extend(optimization_root.glob("*.md"))
    optimization_files = [
        item(path)
        for path in sorted(optimization_candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:80]
    ]
    return {
        "product_project_root": display_path(project_root),
        "product_project_ready": True,
        "csv_files": csv_files,
        "download_dirs": download_dirs,
        "analysis_files": analysis_files,
        "hot_script_files": analysis_files,
        "hot_script_dir": display_path(hot_script_dir) if hot_script_dir else "",
        "hot_script_count": len(analysis_files),
        "script_output_dir": display_path(script_output_dir),
        "script_output_count": len(script_output_paths),
        "script_files": script_files,
        "adapted_script_files": adapted_script_files,
        "assembled_video_files": assembled_video_files,
        "publish_record_files": publish_record_files,
        "metrics_files": metrics_files,
        "metrics_summary_tables": metrics_summary_tables,
        "optimization_files": optimization_files,
    }


def cached_file_listing():
    now = time.time()
    with FILE_LISTING_CACHE_LOCK:
        if FILE_LISTING_CACHE["payload"] is not None and FILE_LISTING_CACHE["expires_at"] > now:
            return FILE_LISTING_CACHE["payload"]
    payload = file_listing()
    with FILE_LISTING_CACHE_LOCK:
        FILE_LISTING_CACHE["payload"] = payload
        FILE_LISTING_CACHE["expires_at"] = time.time() + FILE_LISTING_CACHE_SECONDS
    return payload


def run_path_chooser(script):
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        stderr = str(exc.stderr or "")
        if exc.returncode == 1 or "User canceled" in stderr or "-128" in stderr or "用户已取消" in stderr:
            return ""
        raise RuntimeError("文件选择窗口打开失败，请检查 macOS 权限后重试") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("无法打开系统文件选择窗口，请确认当前环境支持 macOS 文件选择器") from exc
    return result.stdout.strip()


def choose_analysis_path(kind="folder"):
    if kind == "file":
        script = 'POSIX path of (choose file with prompt "选择要拆解的 MP4 视频")'
    else:
        script = 'POSIX path of (choose folder with prompt "选择要拆解的视频目录")'
    return run_path_chooser(script)


def choose_script_reference_path():
    script = 'POSIX path of (choose file with prompt "选择竞品视频拆解结果 Markdown")'
    return run_path_chooser(script)


def choose_local_path(kind="file", prompt="选择文件"):
    safe_prompt = str(prompt or "选择文件").replace('"', '\\"')
    if kind == "folder":
        script = f'POSIX path of (choose folder with prompt "{safe_prompt}")'
    else:
        script = f'POSIX path of (choose file with prompt "{safe_prompt}")'
    return run_path_chooser(script)


def public_error_message(exc):
    message = str(exc) or "操作失败"
    if isinstance(exc, subprocess.CalledProcessError) or "Command '['" in message or "returned non-zero exit status" in message:
        if "osascript" in message or "choose file" in message or "choose folder" in message:
            return "文件选择没有完成，请重新选择"
        return "外部程序执行失败，请查看运行日志"
    if message == "缺少 path":
        return "请先选择文件或目录"
    if isinstance(exc, FileNotFoundError):
        return message
    if isinstance(exc, PermissionError):
        return "没有权限访问该路径，请检查系统权限后重试"
    return message


def validate_analysis_input_path(config):
    if not selected_product_doc_path(config):
        raise ValueError("请先从产品信息 Markdown 中选择本次视频拆解对应的产品")
    raw_path = str(config.get("analysis_input_path", "") or "").strip()
    if not raw_path:
        raise ValueError("请先选择要拆解的 MP4 视频或包含 MP4 的目录")

    target = resolve_ui_path(raw_path)
    if not target.exists():
        raise ValueError(f"拆解视频路径不存在: {target}")
    if target.is_file() and target.suffix.lower() != ".mp4":
        raise ValueError(f"选择的文件不是 MP4: {target.name}")
    if target.is_dir() and not any(target.glob("*.mp4")):
        raise ValueError(f"选择的目录里没有 MP4: {target}")


def validate_script_generation_input(config):
    product_doc = selected_product_doc_path(config)
    if not product_doc:
        raise ValueError("请先选择产品信息 Markdown，再生成脚本")
    raw_path = str(config.get("script_reference_analysis_path", "") or "").strip()
    if not raw_path:
        raise ValueError("请先选择一个参考爆款脚本 Markdown")

    target = resolve_ui_path(raw_path)
    if not target.exists():
        raise ValueError(f"参考爆款脚本不存在: {target}")
    if target.suffix.lower() != ".md":
        raise ValueError(f"参考爆款脚本必须是 Markdown 文件: {target.name}")
    if mutation_enabled(config):
        clone_path = clone_path_for_current_reference(config)
        if not clone_path or not clone_path.exists():
            raise ValueError(
                "裂变必须以已复刻脚本为输入源。请先关闭“是否裂变”生成复刻稿，再勾选裂变。"
                f"\n缺少复刻稿: {clone_path or ''}"
            )
    if str(config.get("script_generation_backend", "") or "").strip() == "obsidian_cli":
        command = str(config.get("script_obsidian_cli_command", "") or os.environ.get("OBSIDIAN_SCRIPT_CLI_COMMAND", "")).strip()
        if not command:
            raise ValueError("已选择 Obsidian CLI，但还没有填写 Obsidian CLI 命令")

    prompt_path = resolve_script_generation_prompt_path(config)
    if not prompt_path.exists():
        raise ValueError(f"复刻提示词文件不存在: {prompt_path}")
    profile = normalize_product_profile(config.get("product_profile", {}))
    core_fields = [
        "product_name",
        "english_name",
        "top_selling_points",
        "audience_pain_matrix",
        "pain_conversion_talk_tracks",
        "tiktok_marketing_angles",
    ]
    if not any(str(profile.get(field, "")).strip() for field in core_fields):
        raise ValueError("当前产品信息 Markdown 缺少核心产品信息，请先补充产品信息后再生成脚本")


def validate_collect_input(config):
    if not selected_product_doc_path(config):
        raise ValueError("请先从产品信息 Markdown 中选择本次采集对应的产品")
    if int(config.get("product_limit", 0) or 0) < 1:
        raise ValueError("商品链接数量至少为 1")
    if int(config.get("videos_per_product", 0) or 0) < 1:
        raise ValueError("每商品视频数量至少为 1")
    category_path = config.get("category_path", [])
    if isinstance(category_path, str):
        category_path = [part.strip() for part in category_path.split(">") if part.strip()]
    if not category_path:
        raise ValueError("请先选择商品分类，或选择“全部”")


def open_local_path(raw_path):
    target = resolve_ui_path(raw_path)
    if not target:
        raise ValueError("缺少 path")
    if not target.exists():
        raise FileNotFoundError(f"路径不存在: {target}")
    if sys.platform != "darwin":
        return False
    subprocess.Popen(["open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def send_html(handler, status, body):
    payload = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def send_local_video(handler, raw_path):
    target = resolve_ui_path(raw_path)
    if not target or not target.exists() or not target.is_file():
        handler.send_error(404, "Video not found")
        return
    if target.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
        handler.send_error(400, "Unsupported video type")
        return

    size = target.stat().st_size
    range_header = handler.headers.get("Range", "")
    start = 0
    end = size - 1
    status = 200
    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)", range_header)
        if match:
            status = 206
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))
    length = end - start + 1
    content_type = "video/mp4"
    if target.suffix.lower() == ".webm":
        content_type = "video/webm"
    elif target.suffix.lower() == ".mov":
        content_type = "video/quicktime"

    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(length))
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()
    with target.open("rb") as file:
        file.seek(start)
        remaining = length
        while remaining > 0:
            chunk = file.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return
            remaining -= len(chunk)


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OPC 内容量化增长引擎</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23151719'/%3E%3Cpath d='M7 8h18v8c0 5-4 9-9 9s-9-4-9-9V8z' fill='%23b67a2c'/%3E%3Cpath d='M16 25c5 0 9-4 9-9v-3L12 26c1 .6 2.5-1 4-1z' fill='%231d8a6b'/%3E%3C/svg%3E" />
  <style>
    :root {
      color-scheme: light;
      --accent:#b67a2c;
      --accent-hover:#9d6220;
      --accent-soft:#fff4e1;
      --ink:#151719;
      --text:#202326;
      --muted:#6b7078;
      --subtle:#8a9099;
      --bg:#eff1f0;
      --panel:#ffffff;
      --field:#fbfaf7;
      --field-strong:#f5f3ee;
      --line:#d7d9d6;
      --soft-line:#e8e8e3;
      --success:#1d8a6b;
      --danger:#b42318;
      --danger-bg:#fff0ee;
      --shadow:0 18px 55px rgba(22,24,28,.12);
      --shadow-soft:0 1px 0 rgba(255,255,255,.9) inset, 0 12px 28px rgba(24,28,34,.08);
    }
    * { box-sizing: border-box; }
    body {
      margin:0;
      min-height:100vh;
      font:14px/1.48 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;
      color:var(--text);
      background:
        linear-gradient(rgba(16,16,16,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(16,16,16,.035) 1px, transparent 1px),
        linear-gradient(135deg, #f8f7f2 0%, #eef1ef 52%, #f7f6f0 100%);
      background-size:28px 28px, 28px 28px, auto;
      letter-spacing:0;
    }
    body::before {
      content:"";
      position:fixed;
      inset:0;
      z-index:-1;
      pointer-events:none;
      background:
        radial-gradient(circle at 12% 0%, rgba(217,255,99,.18), transparent 30%),
        radial-gradient(circle at 88% 8%, rgba(29,138,107,.12), transparent 28%);
    }
    .page { display:none; }
    .is-hidden { display:none !important; }
    body[data-page="home"] #homePage,
    body[data-page="product"] #productPage,
    body[data-page="collect"] #collectPage,
    body[data-page="analyze"] #analyzePage,
    body[data-page="script"] #scriptPage,
    body[data-page="adapt"] #adaptPage,
    body[data-page="assemble"] #assemblePage,
    body[data-page="publish"] #publishPage,
    body[data-page="metrics"] #metricsPage,
    body[data-page="optimize"] #optimizePage { display:block; }
    header {
      position:sticky;
      top:0;
      z-index:2;
      min-height:72px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:20px;
      padding:0 30px;
      background:rgba(255,253,247,.86);
      border-bottom:1px solid var(--ink);
      box-shadow:0 14px 0 rgba(16,16,16,.06);
      backdrop-filter:blur(14px);
    }
    .headleft { display:flex; align-items:center; gap:20px; min-width:0; }
    h1 { display:flex; align-items:center; gap:10px; margin:0; color:var(--ink); font-size:24px; font-weight:820; letter-spacing:0; white-space:nowrap; }
    h1::before {
      content:"";
      width:24px;
      height:24px;
      border-radius:0;
      background:
        linear-gradient(135deg, #d9ff63 0%, #d2a85c 48%, #1d8a6b 100%);
      border:1px solid var(--ink);
      box-shadow:3px 3px 0 rgba(16,16,16,.14);
      flex:0 0 auto;
    }
    .page { max-width:1400px; margin:30px auto 46px; padding:0 24px; }
    .pageintro {
      display:flex;
      align-items:flex-end;
      justify-content:space-between;
      gap:18px;
      margin:0 0 18px;
      padding:6px 2px 0;
    }
    .pageintro h2 { margin:0 0 5px; color:#151719; font-size:28px; line-height:1.08; font-weight:780; }
    .pageintro .muted { max-width:760px; color:#5c6169; font-size:14px; }
    .workspace { display:grid; grid-template-columns:minmax(360px, 440px) minmax(0,1fr); gap:18px; align-items:start; }
    .workspace.product { grid-template-columns:minmax(0, 1fr) 360px; }
    .homePage { max-width:1280px; margin:14px auto 0; padding:0 22px 10px; overflow:hidden; }
    .homeHero {
      position:relative;
      min-height:248px;
      display:block;
      align-items:center;
      overflow:hidden;
      border:1px solid var(--ink);
      border-radius:0;
      padding:24px 32px;
      color:var(--ink);
      background:linear-gradient(135deg, #fffdf7 0%, #f4f1e8 58%, #eaf5e8 100%);
      box-shadow:0 14px 0 rgba(16,16,16,.08);
    }
    .homeHero h2 { margin:0; color:var(--ink); font-size:clamp(32px, 3.2vw, 38px); line-height:1.05; font-weight:880; max-width:100%; }
    .homeHero p { margin:12px 0 0; max-width:960px; color:var(--muted); font-size:13px; line-height:1.62; font-weight:620; }
    .homeHero p + p { margin-top:7px; }
    .eyebrow { display:inline-flex; align-items:center; min-height:24px; margin-bottom:10px; padding:0 8px; border:1px solid var(--ink); border-radius:0; color:var(--ink); background:#d9ff63; font-size:11px; font-weight:820; box-shadow:3px 3px 0 rgba(16,16,16,.12); }
    .heroActions { display:flex; flex-wrap:wrap; gap:9px; margin-top:14px; }
    .heroActions a, .stageLink {
      position:relative;
      display:inline-flex;
      align-items:center;
      justify-content:space-between;
      gap:14px;
      min-height:34px;
      padding:7px 10px 7px 13px;
      border-radius:8px;
      border:1px solid rgba(210,168,92,.28);
      color:#f9f7f0;
      background:
        linear-gradient(180deg, rgba(255,255,255,.08) 0%, rgba(255,255,255,.02) 100%),
        linear-gradient(135deg, rgba(21,23,25,.94) 0%, rgba(31,47,45,.9) 100%);
      text-decoration:none;
      font-weight:760;
      box-shadow:0 1px 0 rgba(255,255,255,.12) inset, 0 12px 28px rgba(0,0,0,.2);
      overflow:hidden;
      transition:transform .16s ease, background .16s ease, border-color .16s ease, box-shadow .16s ease;
    }
    .heroActions a::before, .stageLink::before {
      content:"";
      position:absolute;
      inset:0;
      background:linear-gradient(90deg, transparent 0%, rgba(210,168,92,.16) 48%, transparent 100%);
      transform:translateX(-100%);
      transition:transform .28s ease;
    }
    .heroActions a::after, .stageLink::after {
      content:"→";
      position:relative;
      z-index:1;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:22px;
      height:22px;
      border-radius:7px;
      background:rgba(255,255,255,.1);
      color:#d9b86f;
      font-weight:820;
      box-shadow:0 0 0 1px rgba(255,255,255,.1) inset;
    }
    .heroActions a span, .stageLink span { position:relative; z-index:1; }
    .heroActions a.primaryCta {
      color:#111315;
      border-color:#e5bd70;
      background:linear-gradient(180deg, #f3d58f 0%, #c9913d 100%);
      box-shadow:0 1px 0 rgba(255,255,255,.42) inset, 0 16px 34px rgba(201,145,61,.28);
    }
    .heroActions a.primaryCta::after { background:rgba(17,19,21,.12); color:#111315; }
    .heroActions a:hover, .stageLink:hover {
      transform:translateY(-2px);
      border-color:rgba(217,184,111,.62);
      box-shadow:0 1px 0 rgba(255,255,255,.18) inset, 0 18px 36px rgba(0,0,0,.26);
    }
    .heroActions a:hover::before, .stageLink:hover::before { transform:translateX(100%); }
    .homePage .pageintro { margin:10px 0 8px; padding:0 2px; }
    .homePage .pageintro h2 { font-size:20px; margin:0 0 2px; }
    .homePage .pageintro .muted { font-size:12px; }
    .workflowMap { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; margin-top:0; }
    .flowStep {
      position:relative;
      display:flex;
      flex-direction:column;
      min-height:126px;
      padding:12px;
      border:1px solid var(--ink);
      border-radius:0;
      background:#fffdf7;
      box-shadow:6px 6px 0 rgba(16,16,16,.08);
      overflow:hidden;
      transition:transform .16s ease, border-color .16s ease, box-shadow .16s ease;
    }
    .flowStep::before {
      content:"";
      position:absolute;
      top:0;
      left:0;
      right:0;
      height:5px;
      background:linear-gradient(90deg, #d9ff63, #d2a85c 62%, #1d8a6b);
      opacity:1;
    }
    .flowStep::after {
      content:"";
      position:absolute;
      right:12px;
      top:12px;
      width:38px;
      height:38px;
      background:
        linear-gradient(rgba(21,23,25,.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(21,23,25,.08) 1px, transparent 1px);
      background-size:10px 10px;
      mask-image:linear-gradient(135deg, #000, transparent 72%);
      pointer-events:none;
    }
    .flowStep:hover { transform:translate(-2px,-2px); box-shadow:8px 8px 0 rgba(16,16,16,.12); }
    .flowStepTop { display:flex; align-items:center; justify-content:flex-start; gap:8px; margin-bottom:5px; }
    .stepNo { display:inline-flex; align-items:center; justify-content:center; width:26px; height:26px; border:1px solid var(--ink); border-radius:0; background:var(--ink); color:#d9ff63; font:820 11px/1 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; box-shadow:3px 3px 0 rgba(16,16,16,.13); }
    .flowStep h3 { margin:0; font-size:15px; color:var(--ink); font-weight:840; }
    .flowStep p {
      flex:1;
      margin:0 0 6px;
      color:#60666f;
      font-size:11px;
      line-height:1.32;
      display:-webkit-box;
      -webkit-line-clamp:2;
      -webkit-box-orient:vertical;
      overflow:hidden;
    }
    .stageLink { width:100px; min-height:42px; color:#fff; border-color:var(--ink); border-radius:0; background:var(--ink); box-shadow:4px 4px 0 #d9ff63; }
    .stageLink::after { color:#d9ff63; border-radius:0; }
    .agentActions { display:grid; grid-template-columns:repeat(3, 100px); gap:8px; align-items:stretch; justify-content:space-between; margin-top:10px; }
    .agentStartButton {
      width:100px;
      min-height:42px;
      border:1px solid var(--ink);
      border-radius:0;
      background:#fff;
      color:var(--ink);
      font-weight:820;
      cursor:pointer;
      box-shadow:3px 3px 0 rgba(16,16,16,.12);
    }
    .agentStartButton:hover { background:#d9ff63; border-color:var(--ink); box-shadow:4px 4px 0 rgba(16,16,16,.18); }
    .agentStartButton:disabled { cursor:wait; opacity:.62; }
    .agentStatus {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:100px;
      min-height:42px;
      padding:0 9px;
      border-radius:0;
      border:1px solid var(--ink);
      background:#f6f7f4;
      color:var(--muted);
      font-size:11px;
      font-weight:760;
      white-space:nowrap;
    }
    .agentStatus.is-running { color:#101010; background:#d9ff63; border-color:var(--ink); }
    .agentStatus.is-starting { color:#101010; background:#fff3c7; border-color:var(--ink); }
    .agentStatus.is-offline { color:#fff; background:#b32125; border-color:var(--ink); }
    section {
      background:rgba(255,255,255,.88);
      border:1px solid rgba(48,51,55,.11);
      border-radius:8px;
      padding:20px;
      box-shadow:var(--shadow);
      backdrop-filter:blur(16px);
    }
    h2 { font-size:16px; line-height:1.25; margin:0 0 16px; font-weight:760; color:#191b1e; }
    label { display:block; margin:14px 0 7px; color:#454a51; font-size:12px; font-weight:740; }
    input, select, textarea {
      width:100%;
      border:1px solid #d5d3cc;
      border-radius:8px;
      padding:10px 12px;
      font:inherit;
      outline:none;
      background:linear-gradient(180deg, #fff 0%, var(--field) 100%);
      color:var(--text);
      box-shadow:0 1px 0 rgba(255,255,255,.85) inset;
      transition:border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }
    input, select { min-height:42px; }
    input::placeholder, textarea::placeholder { color:#9aa0a8; }
    input:focus, select:focus, textarea:focus { border-color:var(--accent); background:#fff; box-shadow:0 0 0 4px rgba(182,122,44,.14), 0 1px 0 rgba(255,255,255,.85) inset; }
    textarea { min-height:78px; resize:vertical; }
    textarea.prompt { min-height:260px; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif; }
    textarea.knowledge { min-height:220px; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif; }
    textarea.scriptprompt { min-height:300px; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif; }
    textarea.tall { min-height:120px; }
    .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .fastmossFilters { display:grid; gap:10px; margin-top:10px; padding:14px; border:1px solid var(--soft-line); border-radius:8px; background:rgba(250,249,245,.72); }
    .filterGrid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px 12px; }
    .filterRow { display:block; min-width:0; }
    .filterLabel { min-height:0; margin:0 0 6px; color:#4d535a; font-size:12px; font-weight:780; }
    .selectedCondition { display:inline-flex; width:fit-content; max-width:100%; align-items:center; gap:6px; padding:7px 10px; border-radius:999px; background:#edf7f3; color:#246457; font-size:12px; font-weight:760; border:1px solid rgba(29,138,107,.13); overflow-wrap:anywhere; }
    .selectGrid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; }
    .buttons { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
    .sectionhead { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--soft-line); }
    .sectionhead h2 { margin:0; }
    .divider { height:1px; background:var(--soft-line); margin:22px 0; }
    .checkline { display:flex; align-items:center; gap:9px; margin-top:14px; font-weight:680; color:#43474d; }
    .checkline input { width:auto; min-height:auto; accent-color:var(--accent); }
    .mutationToggle {
      min-height:46px;
      padding:10px 13px;
      border:1px solid #d5d3cc;
      border-radius:8px;
      background:linear-gradient(180deg, #fff 0%, var(--field) 100%);
      color:#202326;
      font-size:15px;
      font-weight:780;
      cursor:pointer;
      box-shadow:0 1px 0 rgba(255,255,255,.85) inset;
    }
    .mutationToggle input {
      width:18px;
      height:18px;
      transform:translateY(1px);
    }
    .mutationCountRow {
      display:grid;
      grid-template-columns:1fr 120px;
      gap:10px;
      align-items:center;
      margin-top:8px;
      padding:10px 12px;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:rgba(250,249,245,.72);
    }
    .mutationCountRow label { margin:0; font-size:14px; color:#202326; }
    .mutationCountRow input { min-height:38px; text-align:center; font-weight:760; }
    button {
      min-height:38px;
      border:1px solid rgba(42,44,47,.14);
      border-radius:8px;
      padding:9px 14px;
      font-weight:740;
      cursor:pointer;
      background:linear-gradient(180deg, #fff 0%, #efeee9 100%);
      color:#2c3135;
      box-shadow:var(--shadow-soft);
      transition:background .16s ease, transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }
    button:hover { border-color:rgba(182,122,44,.34); box-shadow:0 1px 0 rgba(255,255,255,.92) inset, 0 14px 28px rgba(24,28,34,.12); }
    button:active { transform:translateY(1px); box-shadow:0 1px 0 rgba(255,255,255,.7) inset; }
    button.primary, button.blue {
      background:linear-gradient(180deg, #c9913d 0%, #a56421 100%);
      color:#fff;
      border-color:#9c641f;
      text-shadow:0 1px 0 rgba(0,0,0,.12);
    }
    button.primary:hover, button.blue:hover { background:linear-gradient(180deg, #d09d4d 0%, var(--accent-hover) 100%); }
    button.danger { background:linear-gradient(180deg, #fff8f7 0%, var(--danger-bg) 100%); color:var(--danger); border-color:#f0c8c3; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .status { display:flex; gap:9px; align-items:center; min-height:34px; padding:0 12px; border:1px solid var(--ink); border-radius:0; background:#fff; color:var(--ink); font-size:13px; font-weight:780; white-space:nowrap; box-shadow:3px 3px 0 rgba(16,16,16,.12); }
    .dot { width:8px; height:8px; border-radius:50%; background:#9ca3af; }
    .dot.running { background:var(--success); box-shadow:0 0 0 5px rgba(29,138,107,.18); }
    pre {
      height:430px;
      overflow:auto;
      margin:0;
      padding:16px;
      border-radius:8px;
      background:#101214;
      color:#e9ece8;
      border:1px solid rgba(255,255,255,.09);
      box-shadow:0 1px 0 rgba(255,255,255,.08) inset, 0 18px 36px rgba(16,18,20,.18);
      white-space:pre-wrap;
      word-break:break-word;
      font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
    }
    .compactLog {
      margin:0 0 12px;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:rgba(250,249,245,.68);
      overflow:hidden;
    }
    .compactLog summary {
      display:flex;
      align-items:center;
      justify-content:space-between;
      min-height:40px;
      padding:0 12px;
      cursor:pointer;
      color:#59606a;
      font-size:12px;
      font-weight:780;
      list-style:none;
    }
    .compactLog summary::-webkit-details-marker { display:none; }
    .compactLog summary::after {
      content:"展开";
      padding:3px 8px;
      border-radius:999px;
      background:#edf7f3;
      color:#246457;
      font-size:11px;
      border:1px solid rgba(29,138,107,.12);
    }
    .compactLog[open] summary::after { content:"收起"; }
    .compactLog pre {
      height:180px;
      border-radius:0;
      border:0;
      box-shadow:none;
      font-size:12px;
      background:#151719;
    }
    .files { display:grid; grid-template-columns:1fr; gap:12px; margin-top:16px; }
    .filebox { border:1px solid var(--soft-line); border-radius:8px; padding:14px; max-height:260px; overflow:auto; background:rgba(250,249,245,.76); box-shadow:0 1px 0 rgba(255,255,255,.8) inset; }
    .filebox h2 { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
    .fileitem { padding:10px 0; border-top:1px solid var(--soft-line); min-width:0; }
    .fileitem:first-child { border-top:0; }
    .filelink { display:block; max-width:100%; color:#275f62; font-weight:740; line-height:1.4; text-decoration:none; white-space:normal; overflow-wrap:anywhere; word-break:break-word; }
    .filelink:hover { color:var(--accent); text-decoration:underline; }
    .filebutton { width:100%; min-height:0; border:0; border-radius:0; padding:0; text-align:left; background:transparent; box-shadow:none; }
    .filebutton:hover { background:transparent; }
    .filebutton:active { transform:none; }
    .filemeta { display:inline-flex; align-items:center; margin-top:5px; padding:3px 8px; border-radius:999px; background:#edf7f3; color:#246457; font-size:12px; font-weight:700; border:1px solid rgba(29,138,107,.12); }
    .cloneStatus { margin:0 0 7px 8px; vertical-align:middle; }
    .cloneStatus.done { background:#edf7f3; color:#246457; border-color:rgba(29,138,107,.18); }
    .cloneStatus.pending { background:#fff7e8; color:#8a5a14; border-color:rgba(201,145,61,.22); }
    .dirpath {
      margin:4px 0 8px;
      padding:8px 10px;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:rgba(255,255,255,.68);
      color:#59606a;
      font-size:12px;
      line-height:1.45;
      overflow-wrap:anywhere;
    }
    .selectedScriptName {
      min-height:42px;
      padding:10px 12px;
      border:1px solid #d5d3cc;
      border-radius:8px;
      background:linear-gradient(180deg, #fff 0%, var(--field) 100%);
      color:#245f63;
      font-size:13px;
      font-weight:760;
      line-height:1.45;
      overflow-wrap:anywhere;
    }
    .scriptPickerList {
      max-height:280px;
      overflow:auto;
      margin-top:10px;
      padding:4px 0;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:rgba(255,255,255,.66);
    }
    .scriptPickerList .fileitem {
      padding:10px 12px;
      display:grid;
      grid-template-columns:auto minmax(0,1fr);
      gap:8px 10px;
      align-items:start;
    }
    .scriptPickerList .filebutton { align-self:center; }
    .scriptPickerList .cloneStatus { margin:2px 0 0; width:max-content; }
    .scriptPickerList .filelink { grid-column:2; }
    .scriptPickerList .scriptSourceHint { grid-column:2; }
    .scriptPickerList .empty { padding:14px 12px; }
    .scriptSourceHint {
      color:#6c747d;
      font-size:11px;
      line-height:1.4;
      overflow-wrap:anywhere;
    }
    body[data-page="script"] {
      background:
        linear-gradient(180deg, rgba(245,245,247,.96) 0, rgba(245,245,247,.96) 100%),
        linear-gradient(135deg, #fbfbfd 0%, #f5f5f7 55%, #ffffff 100%);
    }
    body[data-page="script"]::before {
      background-image:none;
    }
    body[data-page="script"] .page {
      max-width:1560px;
      margin-top:22px;
    }
    body[data-page="script"] .pageintro {
      min-height:92px;
      align-items:center;
      margin-bottom:18px;
      padding:0 4px;
    }
    body[data-page="script"] .pageintro h2 {
      font-size:38px;
      font-weight:760;
      letter-spacing:0;
    }
    body[data-page="script"] .pageintro .muted {
      max-width:680px;
      font-size:15px;
      color:#6e6e73;
    }
    .scriptWorkspace {
      grid-template-columns:1fr;
      gap:18px;
    }
    .scriptControlPanel {
      display:grid;
      grid-template-columns:repeat(12, minmax(0, 1fr));
      gap:14px;
      align-items:stretch;
      padding:18px;
      border-radius:18px;
      background:rgba(255,255,255,.78);
      border-color:rgba(0,0,0,.08);
      box-shadow:0 22px 60px rgba(0,0,0,.08);
      backdrop-filter:saturate(180%) blur(22px);
    }
    .scriptControlPanel .sectionhead {
      grid-column:1 / -1;
      min-height:42px;
      margin:0 0 2px;
      padding:0 2px 12px;
    }
    .scriptControlPanel .sectionhead h2 {
      font-size:18px;
      font-weight:760;
    }
    .scriptControlPanel .scriptStep {
      margin:0;
      padding:15px;
      border-radius:16px;
      background:#fbfbfd;
      border:1px solid rgba(0,0,0,.08);
      box-shadow:0 1px 0 rgba(255,255,255,.9) inset;
      min-width:0;
    }
    .scriptControlPanel .productStep,
    .scriptControlPanel .variableStep,
    .scriptControlPanel .backendStep,
    .scriptControlPanel .generationStep {
      grid-column:span 3;
    }
    .scriptControlPanel .pickerStep {
      grid-column:span 12;
    }
    .scriptControlPanel .pathrow.is-hidden,
    .scriptControlPanel .scriptprompt.is-hidden {
      display:none !important;
    }
    .scriptControlPanel > .inlineHint {
      grid-column:1 / 7;
      margin:0;
      align-self:center;
      color:#6e6e73;
    }
    .scriptControlPanel > .batchLabel {
      grid-column:7 / 13;
      margin:0;
      align-self:end;
      color:#1d1d1f;
      font-size:13px;
    }
    .scriptControlPanel > .batchDraft {
      grid-column:7 / 13;
      min-height:90px;
      max-height:148px;
      overflow:auto;
      border-radius:16px;
      background:#f5f5f7;
      border-color:rgba(0,0,0,.08);
      color:#424245;
    }
    .scriptControlPanel > .buttons {
      grid-column:1 / 7;
      margin:0;
      align-self:end;
      align-items:center;
    }
    .scriptControlPanel > .muted {
      grid-column:1 / -1;
      margin:0;
      color:#6e6e73;
      font-size:12px;
    }
    .scriptControlPanel label {
      margin-top:10px;
      color:#515154;
    }
    .scriptControlPanel input,
    .scriptControlPanel select,
    .scriptControlPanel textarea {
      border-radius:12px;
      background:#fff;
      border-color:rgba(0,0,0,.14);
      min-width:0;
    }
    .scriptStepTitle {
      font-size:14px;
      color:#1d1d1f;
    }
    .scriptStepNo {
      width:26px;
      height:26px;
      border-radius:50%;
      background:#1d1d1f;
      color:#fff;
      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;
    }
    .scriptControlPanel .contextCard {
      margin:0;
      padding:0;
      border:0;
      background:transparent;
      box-shadow:none;
    }
    .scriptControlPanel .contextCard h3 {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      margin:0;
      font-size:13px;
    }
    .scriptControlPanel .grid2 {
      gap:10px;
    }
    .scriptControlPanel .selectedScriptName {
      min-height:54px;
      max-height:92px;
      overflow:auto;
      border-radius:12px;
      background:#fff;
      color:#1d5f62;
    }
    .scriptControlPanel .dirpath {
      max-height:48px;
      overflow:auto;
      border-radius:12px;
      background:#fff;
      color:#6e6e73;
    }
    .scriptPickerList {
      max-height:330px;
      border-radius:14px;
      background:#fff;
    }
    .scriptPickerList .fileitem {
      grid-template-columns:76px minmax(0,1fr);
      padding:11px 14px;
      gap:6px 12px;
    }
    .scriptPickerList .fileitem button:not(.filebutton) {
      width:64px;
      min-height:32px;
      padding:6px 10px;
      border-radius:999px;
      background:#f5f5f7;
    }
    .scriptPickerList .filelink {
      font-size:13px;
      display:-webkit-box;
      -webkit-line-clamp:2;
      -webkit-box-orient:vertical;
      max-height:42px;
      overflow:hidden;
      text-align:left;
    }
    .scriptSourceHint {
      max-height:38px;
      overflow:auto;
    }
    .mutationToggle {
      margin-top:10px;
      border-radius:14px;
      background:#fff;
    }
    .mutationCountRow {
      grid-template-columns:minmax(0,1fr) 96px;
      border-radius:14px;
      background:#fff;
    }
    .scriptResultPanel {
      display:grid;
      grid-template-columns:minmax(360px, .42fr) minmax(0, 1fr);
      gap:14px;
      align-items:start;
      border-radius:18px;
      background:rgba(255,255,255,.78);
      border-color:rgba(0,0,0,.08);
      box-shadow:0 22px 60px rgba(0,0,0,.08);
      backdrop-filter:saturate(180%) blur(22px);
    }
    .scriptResultPanel .taskProgress,
    .scriptResultPanel .compactLog {
      grid-column:1;
      margin:0;
      border-radius:16px;
      background:#fbfbfd;
      border-color:rgba(0,0,0,.08);
    }
    .scriptResultPanel .files {
      grid-column:2;
      grid-row:1 / span 2;
      margin:0;
    }
    .scriptResultPanel .filebox {
      max-height:620px;
      border-radius:16px;
      background:#fbfbfd;
      border-color:rgba(0,0,0,.08);
    }
    .scriptResultPanel .compactLog pre {
      height:260px;
    }
    .scriptResultPanel .dirpath {
      max-height:54px;
      overflow:auto;
      border-radius:12px;
      background:#fff;
    }
    .scriptStep {
      margin-top:12px;
      padding:13px;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:rgba(250,249,245,.72);
      box-shadow:0 1px 0 rgba(255,255,255,.8) inset;
    }
    .scriptStep:first-of-type { margin-top:0; }
    .scriptStepTitle {
      display:flex;
      align-items:center;
      gap:8px;
      margin:0 0 10px;
      color:#202326;
      font-size:13px;
      font-weight:800;
    }
    .scriptStepNo {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:24px;
      height:24px;
      border-radius:7px;
      background:#17191b;
      color:#f0c77a;
      font:820 11px/1 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
    }
    .batchDraft {
      display:grid;
      gap:7px;
      min-height:52px;
      padding:12px;
      border:1px solid rgba(29,138,107,.18);
      border-radius:8px;
      background:linear-gradient(180deg,#f4fbf8 0%,#fbfaf7 100%);
      color:#384148;
      font-size:12px;
      line-height:1.45;
    }
    .batchDraft strong { color:#17191b; }
    .scriptVideoPreview {
      display:grid;
      gap:9px;
      padding:10px;
      border:1px solid rgba(24,28,31,.1);
      border-radius:8px;
      background:#fffefa;
    }
    .scriptVideoPreview video {
      width:100%;
      max-height:360px;
      aspect-ratio:9 / 16;
      border-radius:8px;
      background:#111;
      object-fit:contain;
    }
    .scriptVideoMeta {
      display:grid;
      gap:4px;
      color:#66707a;
      font-size:12px;
      line-height:1.42;
      overflow-wrap:anywhere;
    }
    .scriptVideoMeta strong { color:#202326; }
    .scriptVideoMissing {
      display:grid;
      place-items:center;
      min-height:96px;
      padding:12px;
      border:1px dashed rgba(24,28,31,.16);
      border-radius:8px;
      background:#faf8f2;
      color:#7a8288;
      font-size:12px;
      text-align:center;
    }
    .taskProgress {
      margin-bottom:14px;
      padding:14px;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:rgba(250,249,245,.82);
      box-shadow:0 1px 0 rgba(255,255,255,.8) inset;
    }
    .taskProgressTop { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }
    .taskProgressTitle { color:#202326; font-size:14px; font-weight:820; }
    .taskProgressStage { color:#246457; font-size:12px; font-weight:780; }
    .progressTrack { height:9px; overflow:hidden; border-radius:999px; background:#e5e3dc; box-shadow:0 1px 0 rgba(255,255,255,.7) inset; }
    .progressFill { display:block; height:100%; width:0%; border-radius:999px; background:linear-gradient(90deg,var(--success),#d2a85c); transition:width .24s ease; }
    .taskProgressDetail { margin-top:8px; color:#66707a; font-size:12px; line-height:1.45; overflow-wrap:anywhere; }
    .taskProgress.running { border-color:rgba(29,138,107,.24); background:#f3faf7; }
    .taskProgress.done { border-color:rgba(29,138,107,.18); }
    .taskProgress.failed { border-color:#f0c8c3; background:#fff8f7; }
    .taskProgress.failed .taskProgressStage { color:var(--danger); }
    .taskBoard {
      display:grid;
      gap:10px;
      margin-bottom:14px;
    }
    .taskBoardHeader {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      color:#202326;
      font-size:14px;
      font-weight:820;
    }
    .taskBoardMeta {
      color:#66707a;
      font-size:12px;
      font-weight:760;
    }
    .taskList {
      display:grid;
      gap:8px;
    }
    .taskCard {
      display:grid;
      gap:9px;
      padding:12px;
      border:1px solid var(--soft-line);
      border-radius:8px;
      background:#fffefa;
      box-shadow:0 1px 0 rgba(255,255,255,.8) inset;
    }
    .taskCard.running {
      border-color:rgba(29,138,107,.28);
      background:#f3faf7;
    }
    .taskCard.queued {
      border-color:#d8e2ff;
      background:#f8fbff;
    }
    .taskCard.failed {
      border-color:#f0c8c3;
      background:#fff8f7;
    }
    .taskCardTop {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
    }
    .taskName {
      color:#17191b;
      font-size:13px;
      font-weight:860;
    }
    .taskBadge {
      display:inline-flex;
      align-items:center;
      min-height:24px;
      padding:0 9px;
      border-radius:999px;
      border:1px solid rgba(29,138,107,.18);
      background:#eef8f4;
      color:#236356;
      font-size:12px;
      font-weight:820;
      white-space:nowrap;
    }
    .taskCard.failed .taskBadge {
      border-color:#f0c8c3;
      background:#fff2ef;
      color:var(--danger);
    }
    .taskCard.queued .taskBadge {
      border-color:#adc6ff;
      background:#edf3ff;
      color:#004493;
    }
    .taskStats {
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:7px;
    }
    .taskStat {
      min-height:54px;
      padding:8px;
      border:1px solid rgba(24,28,31,.08);
      border-radius:8px;
      background:rgba(250,249,245,.72);
    }
    .taskStatLabel {
      margin-bottom:4px;
      color:#7a8288;
      font-size:11px;
      font-weight:760;
    }
    .taskStatValue {
      color:#202326;
      font-size:13px;
      font-weight:860;
      overflow-wrap:anywhere;
    }
    .taskMini {
      color:#66707a;
      font-size:12px;
      line-height:1.45;
      overflow-wrap:anywhere;
    }
    body[data-page="script"] .page {
      max-width:1680px;
    }
    body[data-page="script"] .pageintro {
      min-height:70px;
      margin-bottom:12px;
    }
    body[data-page="script"] .pageintro h2 {
      font-size:28px;
      line-height:1.12;
    }
    body[data-page="script"] .pageintro .muted {
      font-size:13px;
      line-height:1.45;
    }
    .scriptWorkspace {
      display:grid;
      grid-template-columns:minmax(0, 1fr) minmax(360px, 420px);
      gap:14px;
      align-items:start;
    }
    .scriptControlPanel {
      grid-column:1;
      gap:12px;
      padding:14px;
      border-radius:12px;
      box-shadow:0 12px 38px rgba(24,28,34,.08);
    }
    .scriptControlPanel .sectionhead {
      min-height:34px;
      padding-bottom:10px;
      margin-bottom:0;
    }
    .scriptControlPanel .sectionhead h2 {
      font-size:16px;
    }
    .scriptControlPanel .scriptStep {
      border-radius:10px;
      padding:12px;
      background:#fbfbfd;
    }
    .scriptControlPanel .productStep { grid-column:span 3; }
    .scriptControlPanel .variableStep { grid-column:span 4; }
    .scriptControlPanel .backendStep { grid-column:span 2; }
    .scriptControlPanel .generationStep { grid-column:span 3; }
    .scriptControlPanel .pickerStep { grid-column:1 / -1; }
    .scriptPickerShell {
      display:grid;
      grid-template-columns:1fr;
      gap:12px;
      align-items:start;
    }
    .scriptPickerPane,
    .scriptPreviewPane {
      min-width:0;
    }
    .scriptPreviewPane {
      display:grid;
      gap:8px;
      align-content:start;
      padding:10px;
      border:1px solid rgba(24,28,31,.08);
      border-radius:10px;
      background:#f5f5f7;
    }
    .scriptPreviewPane label:first-child,
    .scriptPickerPane label:first-child {
      margin-top:0;
    }
    .scriptControlPanel .selectedScriptName {
      max-height:78px;
      min-height:48px;
      border-radius:8px;
    }
    .scriptControlPanel .dirpath {
      max-height:42px;
      border-radius:8px;
    }
    .scriptPickerList {
      max-height:520px;
      margin-top:8px;
      border-radius:10px;
    }
    .scriptPickerList .fileitem {
      grid-template-columns:68px minmax(0,1fr);
      padding:10px 12px;
    }
    .scriptPickerList .fileitem button:not(.filebutton) {
      width:58px;
      min-height:30px;
      padding:5px 9px;
    }
    .scriptVideoPreview {
      border-radius:10px;
      background:#fff;
    }
    .scriptVideoPreview video {
      max-height:420px;
      border-radius:8px;
    }
    .scriptPreviewPanel {
      display:grid;
      gap:10px;
      padding:12px;
      border:1px solid rgba(24,28,31,.08);
      border-radius:10px;
      background:#fbfbfd;
      box-shadow:0 1px 0 rgba(255,255,255,.9) inset;
    }
    .scriptPreviewPanel .selectedScriptName {
      min-height:54px;
      max-height:92px;
      overflow:auto;
      padding:10px 12px;
      border:1px solid rgba(24,28,31,.1);
      border-radius:8px;
      background:#fff;
      color:#1d5f62;
      font-size:13px;
      font-weight:760;
      line-height:1.45;
      overflow-wrap:anywhere;
    }
    .scriptPreviewPanel .scriptVideoPreview video {
      max-height:340px;
    }
    .scriptControlPanel > .buttons {
      grid-column:1 / 4;
      margin:0;
    }
    .scriptControlPanel > .inlineHint {
      grid-column:4 / 9;
      align-self:center;
    }
    .scriptControlPanel > .batchLabel {
      grid-column:9 / 13;
    }
    .scriptControlPanel > .batchDraft {
      grid-column:9 / 13;
      min-height:74px;
      max-height:120px;
      border-radius:10px;
    }
    .scriptResultPanel {
      position:sticky;
      top:84px;
      grid-column:2;
      display:grid;
      grid-template-columns:1fr;
      gap:12px;
      max-height:calc(100vh - 104px);
      overflow:auto;
      padding:14px;
      border-radius:12px;
      box-shadow:0 12px 38px rgba(24,28,34,.08);
    }
    .scriptResultPanel .taskProgress,
    .scriptResultPanel .compactLog,
    .scriptResultPanel .files {
      grid-column:1;
      grid-row:auto;
      margin:0;
    }
    .scriptResultPanel .files {
      display:grid;
      gap:12px;
    }
    .scriptResultPanel .filebox {
      max-height:440px;
      border-radius:10px;
    }
    .scriptResultPanel .compactLog pre {
      height:180px;
    }
    .scriptResultPanel .taskStats {
      grid-template-columns:repeat(2,minmax(0,1fr));
    }
    .batchGroup {
      border-top:1px solid var(--soft-line);
      padding:8px 0;
    }
    .batchGroup:first-child { border-top:0; }
    .batchGroup summary {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      min-height:38px;
      cursor:pointer;
      list-style:none;
    }
    .batchGroup summary::-webkit-details-marker { display:none; }
    .batchTitle {
      display:block;
      color:#202326;
      font-size:13px;
      font-weight:800;
      line-height:1.35;
      overflow-wrap:anywhere;
    }
    .batchMeta {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      margin-top:5px;
      color:#6b7078;
      font-size:12px;
    }
    .batchFiles { padding:6px 0 0 12px; border-left:2px solid rgba(29,138,107,.18); }
    .sourceGroup {
      border-top:1px solid var(--soft-line);
      padding:9px 0;
    }
    .sourceGroup:first-child { border-top:0; }
    .sourceGroup > summary {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      min-height:42px;
      cursor:pointer;
      list-style:none;
    }
    .sourceGroup > summary::-webkit-details-marker { display:none; }
    .sourceMeta {
      margin-top:4px;
      color:#69717b;
      font-size:12px;
      line-height:1.35;
      overflow-wrap:anywhere;
    }
    .sourceRuns {
      margin-top:6px;
      padding-left:12px;
      border-left:2px solid rgba(29,138,107,.14);
    }
    .empty { padding:14px 0; color:var(--muted); }
    .muted { color:var(--muted); font-size:13px; }
    .infoList { display:grid; gap:12px; margin-top:10px; }
    .infoItem { padding:13px; border:1px solid var(--soft-line); border-radius:8px; background:rgba(250,249,245,.76); box-shadow:0 1px 0 rgba(255,255,255,.8) inset; }
    .infoItem strong { display:block; margin-bottom:4px; font-size:13px; }
    .contextCard { margin:0 0 14px; padding:12px; border:1px solid var(--soft-line); border-radius:8px; background:rgba(250,249,245,.76); box-shadow:0 1px 0 rgba(255,255,255,.8) inset; }
    .contextCard h3 { margin:0 0 8px; color:#262a2e; font-size:13px; line-height:1.25; }
    .projectSelectWrap { margin:8px 0 10px; }
    .projectSelectWrap label { margin:0 0 6px; }
    .projectSelect { min-height:40px; background:linear-gradient(180deg,#fff 0%,#f7f5ef 100%); font-weight:680; }
    .contextSummary { display:grid; gap:6px; margin-top:8px; color:#59606a; font-size:12px; }
    .contextSummary strong { color:#202326; font-weight:760; }
    .downloadActions { display:grid; gap:12px; margin-top:10px; }
    .downloadAction { border:1px solid var(--soft-line); border-radius:10px; padding:14px; background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(250,249,245,.76)); box-shadow:0 12px 30px rgba(24,28,32,.06); }
    .downloadActionHead { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:10px; }
    .downloadAction h3 { margin:0; color:#202326; font-size:15px; line-height:1.28; }
    .downloadAction p { margin:4px 0 0; color:#64707c; font-size:12px; line-height:1.55; }
    .metaPill { display:inline-flex; align-items:center; min-height:24px; padding:4px 8px; border-radius:999px; background:#edf7f3; color:#246457; font-size:12px; font-weight:760; white-space:nowrap; }
    .inlineHint { margin-top:8px; color:#697481; font-size:12px; line-height:1.55; }
    .readonlyInfo {
      min-height:40px;
      display:flex;
      align-items:center;
      padding:0 12px;
      border:1px solid var(--line);
      border-radius:7px;
      background:#f7f8f5;
      color:#202326;
      font-size:14px;
      font-weight:650;
    }
    .formSection { padding:18px 0; border-top:1px solid var(--soft-line); }
    .formSection:first-of-type { border-top:0; padding-top:0; }
    .formSection h3 { margin:0 0 12px; color:#262a2e; font-size:15px; line-height:1.3; }
    .pathrow { display:grid; grid-template-columns:1fr 1fr; gap:8px; align-items:center; }
    .pathrow input { grid-column:1 / -1; min-width:0; }
    .pathrow button { width:100%; }
    .toast { position:fixed; top:86px; right:24px; z-index:10; max-width:360px; padding:12px 14px; border-radius:8px; background:rgba(18,20,22,.94); color:#fff; box-shadow:0 18px 44px rgba(0,0,0,.24); opacity:0; pointer-events:none; transform:translateY(-8px); transition:opacity .18s ease, transform .18s ease; }
    .toast.show { opacity:1; transform:translateY(0); }
    .toast.error { background:rgba(215,0,21,.94); }
    @media (max-width:1380px) {
      .scriptControlPanel .productStep,
      .scriptControlPanel .variableStep,
      .scriptControlPanel .backendStep,
      .scriptControlPanel .generationStep {
        grid-column:span 6;
      }
      .scriptPickerShell {
        grid-template-columns:1fr;
      }
    }
    @media (max-width:1180px) {
      .scriptWorkspace {
        grid-template-columns:1fr;
      }
      .scriptResultPanel {
        position:relative;
        top:auto;
        grid-column:1;
        max-height:none;
      }
      .scriptResultPanel .filebox {
        max-height:520px;
      }
      .scriptPickerShell {
        grid-template-columns:1fr;
      }
    }
    @media (max-width:1100px) {
      .workspace { grid-template-columns:minmax(320px, 410px) minmax(0,1fr); }
      .scriptWorkspace { grid-template-columns:1fr; }
      .scriptControlPanel .productStep,
      .scriptControlPanel .variableStep,
      .scriptControlPanel .backendStep,
      .scriptControlPanel .generationStep { grid-column:span 6; }
      .scriptControlPanel > .inlineHint,
      .scriptControlPanel > .batchLabel,
      .scriptControlPanel > .batchDraft,
      .scriptControlPanel > .buttons { grid-column:1 / -1; }
      .scriptResultPanel { grid-template-columns:1fr; }
      .scriptResultPanel .taskProgress,
      .scriptResultPanel .compactLog,
      .scriptResultPanel .files { grid-column:1; grid-row:auto; }
      .taskStats { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .files { grid-template-columns:1fr; }
    }
    @media (max-width:900px) {
      body {
        background:
          linear-gradient(rgba(16,16,16,.035) 1px, transparent 1px),
          linear-gradient(90deg, rgba(16,16,16,.035) 1px, transparent 1px),
          linear-gradient(135deg, #f8f7f2 0%, #eef1ef 52%, #f7f6f0 100%);
        background-size:28px 28px, 28px 28px, auto;
      }
      header { align-items:flex-start; padding:14px 18px; flex-direction:column; }
      .headleft { width:100%; align-items:flex-start; flex-direction:column; gap:12px; }
      .workspace, .workspace.product, .homeHero, .homeSummary, .workflowMap { grid-template-columns:1fr; }
      .scriptControlPanel { grid-template-columns:1fr; padding:14px; }
      .scriptControlPanel .productStep,
      .scriptControlPanel .variableStep,
      .scriptControlPanel .backendStep,
      .scriptControlPanel .generationStep,
      .scriptControlPanel .pickerStep,
      .scriptControlPanel .sectionhead,
      .scriptControlPanel > .inlineHint,
      .scriptControlPanel > .batchLabel,
      .scriptControlPanel > .batchDraft,
      .scriptControlPanel > .buttons,
      .scriptControlPanel > .muted { grid-column:1; }
      .scriptPickerShell { grid-template-columns:1fr; }
      .scriptVideoPreview video { max-height:360px; }
      body[data-page="script"] .scriptControlPanel {
        position:relative;
        top:auto;
        max-height:none;
        overflow:visible;
      }
      body[data-page="script"] .pageintro h2 { font-size:30px; }
      .pageintro { align-items:flex-start; flex-direction:column; }
      .page { margin-top:24px; padding:0 14px; }
    }
    @media (max-width:640px) {
      .grid2, .pathrow { grid-template-columns:1fr; }
      .pathrow input { grid-column:auto; }
      section { padding:16px; }
      .pageintro h2 { font-size:24px; }
      .status { width:100%; justify-content:flex-start; }
      .taskStats { grid-template-columns:1fr; }
    }
    @media (min-width:901px) {
      body[data-page="script"] .scriptWorkspace {
        grid-template-columns:minmax(0, 1fr) minmax(320px, 380px);
      }
      body[data-page="script"] .scriptControlPanel {
        position:sticky;
        top:84px;
        max-height:calc(100vh - 104px);
        overflow:auto;
      }
      body[data-page="script"] .scriptResultPanel {
        position:sticky;
        top:84px;
        grid-column:2;
        max-height:calc(100vh - 104px);
      }
    }
    @media (min-width:901px) and (max-width:1100px) {
      body[data-page="script"] .scriptControlPanel .productStep,
      body[data-page="script"] .scriptControlPanel .variableStep,
      body[data-page="script"] .scriptControlPanel .pickerStep {
        grid-column:1 / -1;
      }
      body[data-page="script"] .scriptControlPanel .backendStep,
      body[data-page="script"] .scriptControlPanel .generationStep {
        grid-column:span 6;
      }
    }
    body[data-page="script"] {
      overflow:auto;
      background:#f9f9fe;
      color:#1a1c1f;
      font-family:Inter,-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;
    }
    body[data-page="script"] header {
      position:fixed;
      top:0;
      left:0;
      right:0;
      z-index:20;
      height:52px;
      min-height:52px;
      padding:0 20px;
      background:#f9f9fe;
      border-bottom:1px solid #c1c6d7;
      box-shadow:none;
      backdrop-filter:none;
    }
    body[data-page="script"] h1 {
      color:#0058bc;
      font-size:18px;
      font-weight:800;
    }
    body[data-page="script"] h1::before { display:none; }
    body[data-page="script"] .nav {
      height:52px;
      padding:0;
      border:0;
      border-radius:0;
      background:transparent;
    }
    body[data-page="script"] .nav a {
      min-height:52px;
      border-radius:0;
      border-bottom:2px solid transparent;
      color:#414755;
      background:transparent;
      box-shadow:none;
      font-size:12px;
      font-weight:620;
    }
    body[data-page="script"] .nav a.active,
    body[data-page="script"] .nav a:hover {
      color:#0058bc;
      border-bottom-color:#0058bc;
      background:transparent;
      box-shadow:none;
    }
    body[data-page="script"] .status {
      min-height:34px;
      color:#414755;
      background:#fff;
      border:1px solid #c1c6d7;
      box-shadow:none;
    }
    body[data-page="script"] .pageintro { display:none; }
    body[data-page="script"] #scriptPage.scriptAppPage {
      display:block;
      max-width:none;
      min-height:calc(100vh - 52px);
      margin:52px 0 0;
      padding:0;
      overflow:visible;
    }
    body[data-page="script"] .scriptWorkspace {
      display:grid;
      grid-template-columns:minmax(250px, 280px) minmax(440px, 1fr) minmax(480px, 560px);
      grid-template-rows:auto auto auto;
      gap:0;
      width:100%;
      min-height:calc(100vh - 52px);
      align-items:start;
      background:#f9f9fe;
    }
    body[data-page="script"] .scriptControlPanel {
      grid-column:1;
      grid-row:1 / 4;
      position:static;
      display:flex;
      flex-direction:column;
      gap:0;
      max-height:none;
      overflow:visible;
      padding:16px;
      border:0;
      border-right:1px solid #c1c6d7;
      border-radius:0;
      background:#f3f3f8;
      box-shadow:none;
      backdrop-filter:none;
    }
    body[data-page="script"] .scriptLibraryPanel {
      grid-column:2;
      grid-row:1;
      display:flex;
      min-width:0;
      min-height:0;
      max-height:min(430px, calc(100vh - 150px));
      flex-direction:column;
      overflow:hidden;
      background:#fff;
      border-right:1px solid #c1c6d7;
    }
    body[data-page="script"] .scriptResultPanel {
      grid-column:3;
      grid-row:1 / 4;
      position:static;
      display:contents;
    }
    body[data-page="script"] .scriptBottomPanel {
      grid-column:2;
      grid-row:2 / 4;
      min-height:0;
      display:flex;
      flex-direction:column;
      overflow:visible;
      border-top:1px solid #c1c6d7;
      background:#fff;
    }
    body[data-page="script"] .sectionhead {
      display:flex;
      justify-content:space-between;
      align-items:center;
      min-height:32px;
      margin:0 0 8px;
      padding:0;
      border:0;
    }
    body[data-page="script"] .sectionhead h2,
    body[data-page="script"] .scriptStepTitle,
    body[data-page="script"] .taskBoardHeader,
    body[data-page="script"] .filebox h2 {
      margin:0;
      color:#1a1c1f;
      font-size:13px;
      line-height:18px;
      font-weight:700;
      letter-spacing:0;
    }
    body[data-page="script"] .scriptStep {
      margin:0 0 12px;
      padding:12px;
      border:1px solid #d9dade;
      border-radius:4px;
      background:#fff;
      box-shadow:none;
    }
    body[data-page="script"] .scriptStepNo {
      width:22px;
      height:22px;
      border-radius:4px;
      background:#1a1c1f;
      color:#fff;
      font:700 11px/1 JetBrains Mono,ui-monospace,SFMono-Regular,Menlo,monospace;
    }
    body[data-page="script"] .contextCard {
      margin:0;
      padding:0;
      border:0;
      background:transparent;
      box-shadow:none;
    }
    body[data-page="script"] .contextCard h3 {
      display:flex;
      justify-content:space-between;
      gap:8px;
      margin:0 0 8px;
      font-size:12px;
      line-height:16px;
    }
    body[data-page="script"] label {
      margin:10px 0 5px;
      color:#414755;
      font-size:11px;
      line-height:14px;
      font-weight:650;
    }
    body[data-page="script"] input,
    body[data-page="script"] select,
    body[data-page="script"] textarea {
      min-height:32px;
      border:1px solid #c1c6d7;
      border-radius:4px;
      background:#fff;
      color:#1a1c1f;
      font-size:13px;
      box-shadow:none;
    }
    body[data-page="script"] input:focus,
    body[data-page="script"] select:focus,
    body[data-page="script"] textarea:focus {
      border-color:#0058bc;
      outline:2px solid rgba(0,88,188,.18);
    }
    body[data-page="script"] button {
      min-height:30px;
      border-radius:4px;
      font-size:12px;
      font-weight:650;
    }
    body[data-page="script"] button.blue,
    body[data-page="script"] button.primary {
      background:#0070eb;
      color:#fff;
      border-color:#0070eb;
      box-shadow:none;
    }
    body[data-page="script"] button.danger {
      background:#fff;
      color:#ba1a1a;
      border-color:#ffdad6;
      box-shadow:none;
    }
    body[data-page="script"] .scriptSideNav {
      display:none;
      gap:6px;
      margin-top:auto;
      padding-top:12px;
      border-top:1px solid #c1c6d7;
    }
    body[data-page="script"] .scriptSideNav button {
      justify-content:flex-start;
      min-height:34px;
      padding:0 10px;
      border:0;
      background:transparent;
      color:#414755;
      text-align:left;
      box-shadow:none;
    }
    body[data-page="script"] .scriptSideNav button.active {
      background:#0070eb;
      color:#fff;
    }
    body[data-page="script"] .scriptLibraryToolbar {
      display:flex;
      align-items:center;
      gap:10px;
      min-height:76px;
      padding:16px;
      border-bottom:1px solid #c1c6d7;
      background:#fff;
    }
    body[data-page="script"] .scriptSearchShell {
      display:flex;
      align-items:center;
      gap:8px;
      flex:1;
      min-width:0;
      height:38px;
      padding:0 12px;
      border-radius:999px;
      background:#f3f3f8;
      color:#414755;
    }
    body[data-page="script"] .scriptSearchShell input {
      width:100%;
      min-height:0;
      height:30px;
      padding:0;
      border:0;
      background:transparent;
      outline:0;
    }
    body[data-page="script"] .scriptLibraryToolbar button {
      width:34px;
      min-height:34px;
      padding:0;
      border:0;
      color:#1a1c1f;
      background:#f3f3f8;
      box-shadow:none;
    }
    body[data-page="script"] .scriptLibraryHeader {
      display:grid;
      grid-template-columns:minmax(0, 1fr) auto;
      align-items:center;
      min-height:38px;
      padding:0 20px;
      border-bottom:1px solid #c1c6d7;
      background:#f3f3f8;
      color:#414755;
      font-size:11px;
      font-weight:650;
    }
    body[data-page="script"] .scriptLibraryPanel > .dirpath {
      margin:0;
      padding:8px 20px;
      border:0;
      border-bottom:1px solid #e2e2e7;
      border-radius:0;
      background:#fff;
      color:#717786;
      font-size:11px;
      max-height:34px;
      overflow:hidden;
    }
    body[data-page="script"] .scriptPickerShell,
    body[data-page="script"] .scriptPickerPane {
      display:flex;
      min-height:0;
      flex:1;
      flex-direction:column;
    }
    body[data-page="script"] .scriptPickerList {
      flex:1;
      max-height:none;
      margin:0;
      padding:0;
      overflow:auto;
      border:0;
      border-radius:0;
      background:#fff;
    }
    body[data-page="script"] .scriptPickerList .fileitem {
      position:relative;
      display:grid;
      grid-template-columns:64px minmax(0, 1fr) auto;
      gap:6px 12px;
      align-items:center;
      min-height:52px;
      padding:8px 20px;
      border-top:0;
      border-bottom:1px solid #e2e2e7;
      background:#fff;
    }
    body[data-page="script"] .scriptPickerList .fileitem:hover {
      background:#f3f3f8;
    }
    body[data-page="script"] .scriptPickerList .fileitem.is-selected {
      background:#d8e2ff;
    }
    body[data-page="script"] .scriptPickerList .fileitem.is-selected::before {
      content:"";
      position:absolute;
      left:0;
      top:0;
      bottom:0;
      width:3px;
      background:#0058bc;
    }
    body[data-page="script"] .scriptPickerList .fileitem > button:first-child {
      grid-row:1 / span 2;
      width:54px;
      min-height:30px;
      padding:0;
      border:1px solid #c1c6d7;
      background:#fff;
      color:#0058bc;
      box-shadow:none;
    }
    body[data-page="script"] .scriptPickerList .fileitem > div {
      grid-column:3;
      grid-row:1 / span 2;
      display:flex;
      flex-wrap:wrap;
      justify-content:flex-end;
      gap:4px;
      max-width:150px;
    }
    body[data-page="script"] .scriptPickerList .filelink {
      grid-column:2;
      grid-row:1 / span 2;
      display:-webkit-box;
      -webkit-line-clamp:2;
      -webkit-box-orient:vertical;
      max-height:38px;
      overflow:hidden;
      color:#1a1c1f;
      font:500 12px/18px JetBrains Mono,ui-monospace,SFMono-Regular,Menlo,monospace;
      text-decoration:none;
    }
    body[data-page="script"] .filemeta,
    body[data-page="script"] .cloneStatus {
      display:inline-flex;
      align-items:center;
      min-height:20px;
      margin:0;
      padding:0 6px;
      border-radius:3px;
      background:#e8e8ed;
      color:#414755;
      border:1px solid #d9dade;
      font-size:10px;
      font-weight:700;
      white-space:nowrap;
    }
    body[data-page="script"] .cloneStatus.done {
      background:#e7f7ed;
      color:#146c38;
      border-color:#bde9cb;
    }
    body[data-page="script"] .cloneStatus.pending {
      background:#fff4d8;
      color:#7a4d00;
      border-color:#ffe1a6;
    }
    body[data-page="script"] .scriptPreviewPanel {
      grid-column:1 / -1;
      display:grid;
      grid-template-columns:minmax(220px, .92fr) minmax(0, 1fr);
      gap:0;
      padding:0;
      border:0;
      border-radius:0;
      background:#f9f9fe;
      box-shadow:none;
    }
    body[data-page="script"] .scriptResultPanel > .scriptPreviewPanel {
      grid-column:3;
      grid-row:1;
    }
    body[data-page="script"] .scriptVideoPreview {
      display:grid;
      place-items:center;
      min-height:196px;
      padding:0;
      border:0;
      border-radius:0;
      background:#2e3034;
      overflow:hidden;
    }
    body[data-page="script"] .scriptVideoPreview video {
      width:100%;
      max-height:240px;
      aspect-ratio:16 / 9;
      border-radius:0;
      background:#111;
      object-fit:contain;
    }
    body[data-page="script"] .scriptVideoMeta {
      width:100%;
      padding:8px 12px;
      background:rgba(0,0,0,.48);
      color:#f0f0f5;
      font-size:11px;
    }
    body[data-page="script"] .scriptVideoMissing {
      min-height:196px;
      border:0;
      border-radius:0;
      background:#2e3034;
      color:#f0f0f5;
    }
    body[data-page="script"] .scriptDetailBlock {
      padding:14px 16px;
      background:#f9f9fe;
      border-left:1px solid #c1c6d7;
    }
    body[data-page="script"] .scriptPreviewPanel .selectedScriptName {
      min-height:44px;
      max-height:none;
      margin-top:8px;
      padding:10px 12px;
      border:1px solid #c1c6d7;
      border-radius:4px;
      background:#fff;
      color:#1a1c1f;
      font:500 12px/18px JetBrains Mono,ui-monospace,SFMono-Regular,Menlo,monospace;
      overflow:visible;
    }
    body[data-page="script"] .scriptResultPanel .scriptStep {
      margin:0 20px 14px;
      background:#fff;
    }
    body[data-page="script"] .scriptResultPanel .backendStep,
    body[data-page="script"] .scriptResultPanel .generationStep {
      margin:14px 10px 14px 20px;
    }
    body[data-page="script"] .scriptResultPanel .backendStep {
      grid-column:3;
      grid-row:2;
    }
    body[data-page="script"] .scriptResultPanel .generationStep {
      grid-column:3;
      grid-row:3;
      display:grid;
      grid-template-columns:minmax(88px, .78fr) minmax(0, 1.22fr);
      gap:8px 10px;
      align-items:center;
      margin-left:10px;
      margin-right:20px;
    }
	    body[data-page="script"] .scriptResultPanel .generationStep .scriptStepTitle,
	    body[data-page="script"] .scriptResultPanel .generationStep .promptButtons,
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationToggle,
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationModeControl,
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationCountRow,
    body[data-page="script"] .scriptResultPanel .generationStep .pathrow,
    body[data-page="script"] .scriptResultPanel .generationStep .scriptprompt,
    body[data-page="script"] .scriptResultPanel .generationStep .buttons,
    body[data-page="script"] .scriptResultPanel .generationStep .inlineHint {
      grid-column:1 / -1;
    }
    body[data-page="script"] .scriptResultPanel .generationStep label {
      margin:0;
    }
    body[data-page="script"] .scriptResultPanel .generationStep input,
	    body[data-page="script"] .scriptResultPanel .generationStep select {
	      min-width:0;
	    }
	    body[data-page="script"] .mutationModeControl {
	      display:grid;
	      grid-template-columns:1fr 1fr;
	      gap:8px;
	    }
	    body[data-page="script"] .mutationModeControl button {
	      min-height:62px;
	      padding:10px 12px;
	      border:1px solid #c1c6d7;
	      border-radius:6px;
	      background:#fff;
	      color:#1a1c1f;
	      text-align:left;
	      display:flex;
	      flex-direction:column;
	      gap:4px;
	      box-shadow:none;
	    }
	    body[data-page="script"] .mutationModeControl button strong {
	      font-size:13px;
	      line-height:18px;
	    }
	    body[data-page="script"] .mutationModeControl button span {
	      font-size:11px;
	      line-height:15px;
	      color:#5d6370;
	    }
	    body[data-page="script"] .mutationModeControl button.active {
	      border-color:#0058bc;
	      background:#eaf1ff;
	      color:#003a7a;
	    }
	    body[data-page="script"] .mutationModeControl button.active span {
	      color:#004493;
	    }
    body[data-page="script"] .scriptResultPanel .generationStep .batchLabel {
      grid-column:1;
    }
    body[data-page="script"] .scriptResultPanel .generationStep .batchDraft {
      grid-column:2;
      min-height:54px;
      max-height:74px;
    }
    body[data-page="script"] .promptButtons {
      grid-template-columns:1fr 1fr;
      margin-top:8px;
    }
    body[data-page="script"] .mutationToggle {
      min-height:38px;
      padding:0 10px;
      border:1px solid #d9dade;
      border-radius:4px;
      background:#f3f3f8;
      font-size:13px;
      color:#1a1c1f;
    }
    body[data-page="script"] .mutationToggle input {
      min-height:0;
      width:16px;
      height:16px;
      accent-color:#0070eb;
    }
    body[data-page="script"] .mutationCountRow {
      grid-template-columns:minmax(0, 1fr) 96px;
      padding:10px;
      border:1px solid #d9dade;
      border-radius:4px;
      background:#f3f3f8;
    }
    body[data-page="script"] .batchDraft {
      min-height:66px;
      max-height:112px;
      padding:10px;
      overflow:auto;
      border:1px solid #d9dade;
      border-radius:4px;
      background:#f3f3f8;
      color:#414755;
      font-size:12px;
    }
    body[data-page="script"] .buttons {
      display:grid;
      grid-template-columns:1fr auto;
      gap:8px;
      margin-top:12px;
    }
    body[data-page="script"] .buttons .blue {
      min-height:46px;
      font-size:16px;
      font-weight:800;
    }
    body[data-page="script"] .inlineHint {
      margin-top:10px;
      color:#717786;
      font-size:11px;
      line-height:16px;
    }
    body[data-page="script"] .scriptBottomTabs {
      display:flex;
      min-height:44px;
      border-bottom:1px solid #c1c6d7;
      background:#fff;
    }
    body[data-page="script"] .scriptBottomTabs button {
      min-width:130px;
      min-height:44px;
      padding:0 20px;
      border:0;
      border-bottom:2px solid transparent;
      border-radius:0;
      background:transparent;
      color:#414755;
      box-shadow:none;
    }
    body[data-page="script"] .scriptBottomTabs button.active {
      color:#0058bc;
      border-bottom-color:#0058bc;
    }
    body[data-page="script"] .scriptBottomContent {
      display:none;
      min-height:0;
      flex:0 0 auto;
      overflow:visible;
      padding:0;
    }
    body[data-page="script"] .scriptBottomContent.active {
      display:block;
    }
    body[data-page="script"] #scriptBottomTasks.active {
      display:grid;
      grid-template-columns:1fr;
      gap:0;
    }
    body[data-page="script"] .taskProgress {
      margin:0;
      padding:14px 18px;
      border:0;
      border-bottom:1px solid #e2e2e7;
      border-radius:0;
      background:#fff;
      box-shadow:none;
    }
    body[data-page="script"] .taskBoard {
      margin:0;
      padding:14px 18px;
      overflow:visible;
    }
    body[data-page="script"] .taskList {
      display:grid;
      grid-template-columns:1fr;
      gap:8px;
      margin-top:8px;
      max-height:min(360px, 44vh);
      overflow:auto;
      padding-right:4px;
    }
    body[data-page="script"] .taskCard {
      padding:8px 10px;
      border:1px solid #e2e2e7;
      border-radius:4px;
      background:#fff;
      box-shadow:none;
    }
    body[data-page="script"] .taskStats {
      grid-template-columns:repeat(4,minmax(0,1fr));
    }
    body[data-page="script"] .files {
      display:block;
      margin:0;
      padding:0;
    }
    body[data-page="script"] .filebox {
      max-height:none;
      height:auto;
      max-height:min(620px, 62vh);
      margin:0;
      padding:14px 20px;
      overflow:auto;
      border:0;
      border-radius:0;
      background:#fff;
      box-shadow:none;
    }
    body[data-page="script"] .filebox .dirpath {
      margin:8px 0;
      border-radius:4px;
      background:#f9f9fe;
    }
    body[data-page="script"] .compactLog {
      height:auto;
      margin:0;
      border:0;
      border-radius:0;
      background:#fff;
    }
    body[data-page="script"] .compactLog summary {
      border-bottom:1px solid #e2e2e7;
      border-radius:0;
    }
    body[data-page="script"] .compactLog pre {
      height:min(420px, 50vh);
      margin:0;
      border-radius:0;
      background:#1a1c1f;
    }
	    @media (max-width:760px) {
	      body[data-page="script"] { overflow:auto; }
	      body[data-page="script"] #scriptPage.scriptAppPage {
        height:auto;
        min-height:calc(100vh - 52px);
        overflow:visible;
      }
      body[data-page="script"] .scriptWorkspace {
        grid-template-columns:1fr;
        grid-template-rows:auto;
      }
      body[data-page="script"] .scriptControlPanel,
      body[data-page="script"] .scriptLibraryPanel,
      body[data-page="script"] .scriptResultPanel,
      body[data-page="script"] .scriptBottomPanel {
        grid-column:1;
        grid-row:auto;
        min-height:auto;
        border-right:0;
        border-bottom:1px solid #c1c6d7;
      }
      body[data-page="script"] .scriptControlPanel {
        max-height:none;
      }
      body[data-page="script"] .scriptLibraryPanel {
        min-height:520px;
      }
      body[data-page="script"] .scriptBottomPanel {
	        min-height:360px;
	      }
	    }

	    /* Cartesia-inspired production cockpit for the script workspace. */
	    body[data-page="script"] {
	      --script-bg:#070b0a;
	      --script-bg-2:#0d1412;
	      --script-panel:rgba(15,24,21,.88);
	      --script-panel-strong:rgba(20,31,28,.96);
	      --script-panel-soft:rgba(255,255,255,.045);
	      --script-line:rgba(199,255,230,.14);
	      --script-line-strong:rgba(139,229,198,.34);
	      --script-text:#edf8f3;
	      --script-muted:rgba(237,248,243,.66);
	      --script-faint:rgba(237,248,243,.42);
	      --script-green:#86f7c7;
	      --script-cyan:#7fd7ff;
	      --script-amber:#e8b96d;
	      --script-red:#ff8b86;
	      background:
	        radial-gradient(circle at 22% 0%, rgba(134,247,199,.18) 0, transparent 32%),
	        radial-gradient(circle at 84% 12%, rgba(127,215,255,.13) 0, transparent 30%),
	        linear-gradient(180deg, #050706 0%, var(--script-bg) 44%, #09100e 100%);
	      color:var(--script-text);
	      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Segoe UI",sans-serif;
	    }
	    body[data-page="script"]::before {
	      content:"";
	      position:fixed;
	      inset:0;
	      z-index:-1;
	      pointer-events:none;
	      background-image:
	        linear-gradient(rgba(199,255,230,.055) 1px, transparent 1px),
	        linear-gradient(90deg, rgba(199,255,230,.045) 1px, transparent 1px),
	        radial-gradient(circle at 50% 0%, rgba(255,255,255,.08), transparent 42%);
	      background-size:34px 34px, 34px 34px, 100% 100%;
	      mask-image:linear-gradient(to bottom, #000 0%, #000 72%, transparent 100%);
	    }
	    body[data-page="script"] header {
	      height:64px;
	      min-height:64px;
	      padding:0 22px;
	      background:rgba(5,8,7,.78);
	      border-bottom:1px solid var(--script-line);
	      box-shadow:0 1px 0 rgba(255,255,255,.05) inset, 0 22px 70px rgba(0,0,0,.42);
	      backdrop-filter:saturate(150%) blur(18px);
	    }
	    body[data-page="script"] h1 {
	      color:var(--script-text);
	      font-size:18px;
	      font-weight:780;
	    }
	    body[data-page="script"] h1::before {
	      display:block;
	      width:24px;
	      height:24px;
	      border-radius:7px;
	      background:
	        linear-gradient(135deg, var(--script-green), rgba(127,215,255,.92) 52%, var(--script-amber));
	      box-shadow:0 0 0 1px rgba(255,255,255,.22) inset, 0 0 30px rgba(134,247,199,.22);
	    }
	    body[data-page="script"] .nav {
	      height:42px;
	      padding:4px;
	      border:1px solid var(--script-line);
	      border-radius:8px;
	      background:rgba(255,255,255,.045);
	    }
	    body[data-page="script"] .nav a {
	      min-height:32px;
	      border:0;
	      border-radius:6px;
	      color:var(--script-muted);
	      font-size:12px;
	      font-weight:700;
	    }
	    body[data-page="script"] .nav a.active,
	    body[data-page="script"] .nav a:hover {
	      color:#06100d;
	      background:linear-gradient(180deg, var(--script-green), #5edda7);
	      border:0;
	      box-shadow:0 0 0 1px rgba(255,255,255,.24) inset, 0 12px 28px rgba(94,221,167,.2);
	    }
	    body[data-page="script"] .status {
	      min-height:38px;
	      color:var(--script-muted);
	      background:rgba(255,255,255,.055);
	      border:1px solid var(--script-line);
	      box-shadow:0 1px 0 rgba(255,255,255,.08) inset;
	    }
	    body[data-page="script"] #scriptPage.scriptAppPage {
	      min-height:calc(100vh - 64px);
	      margin:64px 0 0;
	      padding:14px;
	    }
	    body[data-page="script"] .scriptWorkspace {
	      grid-template-columns:minmax(280px, 330px) minmax(480px, 1fr) minmax(430px, 520px);
	      gap:14px;
	      min-height:calc(100vh - 92px);
	      background:transparent;
	      align-items:stretch;
	    }
	    body[data-page="script"] .scriptControlPanel,
	    body[data-page="script"] .scriptLibraryPanel,
	    body[data-page="script"] .scriptBottomPanel,
	    body[data-page="script"] .scriptPreviewPanel,
	    body[data-page="script"] .scriptStep,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog,
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard {
	      border:1px solid var(--script-line);
	      border-radius:8px;
	      background:
	        linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.025)),
	        var(--script-panel);
	      box-shadow:0 1px 0 rgba(255,255,255,.07) inset, 0 26px 80px rgba(0,0,0,.28);
	      backdrop-filter:blur(16px) saturate(140%);
	    }
	    body[data-page="script"] .scriptControlPanel {
	      gap:12px;
	      padding:12px;
	      overflow:auto;
	      border-right:1px solid var(--script-line);
	    }
	    body[data-page="script"] .scriptLibraryPanel {
	      max-height:none;
	      min-height:0;
	      overflow:hidden;
	      border-right:1px solid var(--script-line);
	    }
	    body[data-page="script"] .scriptResultPanel {
	      display:contents;
	    }
	    body[data-page="script"] .scriptBottomPanel {
	      margin-top:0;
	      overflow:hidden;
	      border-top:1px solid var(--script-line);
	    }
	    body[data-page="script"] .sectionhead {
	      min-height:34px;
	      margin:0;
	      padding:0 2px;
	    }
	    body[data-page="script"] .sectionhead h2,
	    body[data-page="script"] .scriptStepTitle,
	    body[data-page="script"] .taskBoardHeader,
	    body[data-page="script"] .filebox h2 {
	      color:var(--script-text);
	      font-size:13px;
	      font-weight:760;
	    }
	    body[data-page="script"] .scriptStep {
	      margin:0;
	      padding:14px;
	    }
	    body[data-page="script"] .scriptStepNo {
	      width:24px;
	      height:24px;
	      border-radius:7px;
	      background:rgba(134,247,199,.12);
	      color:var(--script-green);
	      box-shadow:0 0 0 1px rgba(134,247,199,.28) inset;
	    }
	    body[data-page="script"] .contextCard,
	    body[data-page="script"] .scriptDetailBlock {
	      background:transparent;
	      color:var(--script-muted);
	      border:0;
	    }
	    body[data-page="script"] .contextCard h3,
	    body[data-page="script"] label {
	      color:var(--script-muted);
	    }
	    body[data-page="script"] input,
	    body[data-page="script"] select,
	    body[data-page="script"] textarea {
	      min-height:38px;
	      border:1px solid var(--script-line);
	      border-radius:8px;
	      background:rgba(255,255,255,.055);
	      color:var(--script-text);
	      box-shadow:0 1px 0 rgba(255,255,255,.055) inset;
	    }
	    body[data-page="script"] input::placeholder,
	    body[data-page="script"] textarea::placeholder {
	      color:var(--script-faint);
	    }
	    body[data-page="script"] select option {
	      color:#0b1210;
	      background:#f7fffb;
	    }
	    body[data-page="script"] input:focus,
	    body[data-page="script"] select:focus,
	    body[data-page="script"] textarea:focus {
	      border-color:var(--script-green);
	      outline:3px solid rgba(134,247,199,.16);
	      background:rgba(255,255,255,.08);
	    }
	    body[data-page="script"] button {
	      min-height:36px;
	      border:1px solid var(--script-line);
	      border-radius:8px;
	      color:var(--script-text);
	      background:rgba(255,255,255,.055);
	      box-shadow:0 1px 0 rgba(255,255,255,.08) inset;
	    }
	    body[data-page="script"] button:hover {
	      border-color:var(--script-line-strong);
	      background:rgba(134,247,199,.09);
	    }
	    body[data-page="script"] button.blue,
	    body[data-page="script"] button.primary {
	      background:linear-gradient(180deg, var(--script-green), #54d7a1);
	      color:#04110d;
	      border-color:rgba(134,247,199,.7);
	      box-shadow:0 1px 0 rgba(255,255,255,.35) inset, 0 18px 40px rgba(84,215,161,.24);
	    }
	    body[data-page="script"] button.danger {
	      background:rgba(255,139,134,.08);
	      color:#ffd5d2;
	      border-color:rgba(255,139,134,.28);
	    }
	    body[data-page="script"] .scriptLibraryToolbar {
	      min-height:68px;
	      padding:14px;
	      border-bottom:1px solid var(--script-line);
	      background:rgba(255,255,255,.035);
	    }
	    body[data-page="script"] .scriptSearchShell {
	      height:42px;
	      border:1px solid var(--script-line);
	      border-radius:8px;
	      background:rgba(255,255,255,.055);
	      color:var(--script-green);
	    }
	    body[data-page="script"] .scriptSearchShell input {
	      height:32px;
	      border:0;
	      background:transparent;
	      outline:0;
	    }
	    body[data-page="script"] .scriptLibraryToolbar button {
	      width:38px;
	      min-height:38px;
	      color:var(--script-muted);
	      background:rgba(255,255,255,.055);
	    }
	    body[data-page="script"] .scriptLibraryHeader {
	      padding:0 16px;
	      border-bottom:1px solid var(--script-line);
	      background:rgba(255,255,255,.035);
	      color:var(--script-muted);
	    }
	    body[data-page="script"] .scriptLibraryPanel > .dirpath {
	      max-height:38px;
	      padding:9px 16px;
	      border-bottom:1px solid var(--script-line);
	      background:rgba(255,255,255,.025);
	      color:var(--script-faint);
	    }
	    body[data-page="script"] .scriptPickerList {
	      padding:8px;
	      background:transparent;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem {
	      grid-template-columns:58px minmax(0, 1fr) minmax(92px, auto);
	      gap:8px 10px;
	      min-height:66px;
	      margin-bottom:8px;
	      padding:10px;
	      border:1px solid rgba(199,255,230,.1);
	      border-radius:8px;
	      background:rgba(255,255,255,.04);
	      transition:background .16s ease, border-color .16s ease, transform .16s ease;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem:hover {
	      transform:translateY(-1px);
	      background:rgba(134,247,199,.075);
	      border-color:var(--script-line-strong);
	    }
	    body[data-page="script"] .scriptPickerList .fileitem.is-selected {
	      background:linear-gradient(180deg, rgba(134,247,199,.18), rgba(127,215,255,.08));
	      border-color:rgba(134,247,199,.55);
	    }
	    body[data-page="script"] .scriptPickerList .fileitem.is-selected::before {
	      width:3px;
	      border-radius:3px;
	      background:var(--script-green);
	    }
	    body[data-page="script"] .scriptPickerList .fileitem > button:first-child {
	      width:48px;
	      color:#05110d;
	      border-color:rgba(134,247,199,.56);
	      background:linear-gradient(180deg, var(--script-green), #5ee0a9);
	    }
	    body[data-page="script"] .scriptPickerList .fileitem > div {
	      max-width:170px;
	    }
	    body[data-page="script"] .scriptPickerList .filelink {
	      color:var(--script-text);
	      font-size:12px;
	      line-height:18px;
	    }
	    body[data-page="script"] .filemeta,
	    body[data-page="script"] .cloneStatus {
	      min-height:22px;
	      border-radius:999px;
	      background:rgba(255,255,255,.06);
	      color:var(--script-muted);
	      border:1px solid var(--script-line);
	    }
	    body[data-page="script"] .cloneStatus.done {
	      background:rgba(134,247,199,.12);
	      color:var(--script-green);
	      border-color:rgba(134,247,199,.32);
	    }
	    body[data-page="script"] .cloneStatus.pending {
	      background:rgba(232,185,109,.12);
	      color:#ffdca1;
	      border-color:rgba(232,185,109,.32);
	    }
	    body[data-page="script"] .scriptPreviewPanel {
	      grid-template-columns:minmax(180px, .82fr) minmax(0, 1fr);
	      overflow:hidden;
	    }
	    body[data-page="script"] .scriptVideoPreview,
	    body[data-page="script"] .scriptVideoMissing {
	      min-height:222px;
	      border-right:1px solid var(--script-line);
	      background:
	        linear-gradient(135deg, rgba(134,247,199,.08), transparent 42%),
	        #020403;
	      color:var(--script-muted);
	    }
	    body[data-page="script"] .scriptVideoPreview video {
	      max-height:260px;
	      border-radius:0;
	    }
	    body[data-page="script"] .scriptVideoMeta {
	      background:rgba(0,0,0,.58);
	      color:var(--script-text);
	    }
	    body[data-page="script"] .scriptPreviewPanel .selectedScriptName,
	    body[data-page="script"] .batchDraft {
	      border:1px solid var(--script-line);
	      border-radius:8px;
	      background:rgba(255,255,255,.055);
	      color:var(--script-text);
	    }
	    body[data-page="script"] .scriptResultPanel .scriptStep {
	      margin:0;
	    }
	    body[data-page="script"] .scriptResultPanel .backendStep {
	      margin:14px 0 0 0;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep {
	      margin:14px 0 0 0;
	      grid-template-columns:minmax(96px, .76fr) minmax(0, 1.24fr);
	      gap:9px 10px;
	    }
	    body[data-page="script"] .mutationModeControl button {
	      min-height:68px;
	      border-color:var(--script-line);
	      background:rgba(255,255,255,.045);
	      color:var(--script-text);
	    }
	    body[data-page="script"] .mutationModeControl button span {
	      color:var(--script-faint);
	    }
	    body[data-page="script"] .mutationModeControl button.active {
	      border-color:rgba(134,247,199,.62);
	      background:rgba(134,247,199,.12);
	      color:var(--script-green);
	    }
	    body[data-page="script"] .mutationModeControl button.active span {
	      color:rgba(237,248,243,.78);
	    }
	    body[data-page="script"] .mutationToggle,
	    body[data-page="script"] .mutationCountRow {
	      border-color:var(--script-line);
	      border-radius:8px;
	      background:rgba(255,255,255,.045);
	      color:var(--script-text);
	    }
	    body[data-page="script"] .mutationToggle input {
	      accent-color:var(--script-green);
	    }
	    body[data-page="script"] .buttons .blue {
	      min-height:48px;
	    }
	    body[data-page="script"] .inlineHint,
	    body[data-page="script"] .taskBoardMeta,
	    body[data-page="script"] .taskMini,
	    body[data-page="script"] .dirpath,
	    body[data-page="script"] .muted,
	    body[data-page="script"] .empty {
	      color:var(--script-faint);
	    }
	    body[data-page="script"] .scriptBottomTabs {
	      min-height:48px;
	      border-bottom:1px solid var(--script-line);
	      background:rgba(255,255,255,.035);
	    }
	    body[data-page="script"] .scriptBottomTabs button {
	      min-height:48px;
	      color:var(--script-muted);
	    }
	    body[data-page="script"] .scriptBottomTabs button.active {
	      color:var(--script-green);
	      border-bottom-color:var(--script-green);
	      background:rgba(134,247,199,.07);
	    }
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog {
	      margin:12px;
	      padding:14px;
	      border-radius:8px;
	    }
	    body[data-page="script"] .taskCard {
	      border-color:var(--script-line);
	      border-radius:8px;
	      background:rgba(255,255,255,.045);
	    }
	    body[data-page="script"] .progressTrack {
	      background:rgba(255,255,255,.08);
	    }
	    body[data-page="script"] .progressFill {
	      background:linear-gradient(90deg, var(--script-green), var(--script-cyan));
	    }
	    body[data-page="script"] .filebox {
	      max-height:min(620px, 62vh);
	    }
	    body[data-page="script"] .filebox .dirpath {
	      background:rgba(255,255,255,.045);
	      border-color:var(--script-line);
	    }
	    body[data-page="script"] .compactLog summary {
	      color:var(--script-muted);
	      border-bottom:1px solid var(--script-line);
	    }
	    body[data-page="script"] .compactLog pre {
	      background:#020403;
	      color:#c7ffe6;
	      border:1px solid rgba(199,255,230,.08);
	      border-radius:8px;
	    }
	    @media (max-width:1180px) {
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:minmax(270px, 320px) minmax(0, 1fr);
	      }
	      body[data-page="script"] .scriptResultPanel > .scriptPreviewPanel,
	      body[data-page="script"] .scriptResultPanel .backendStep,
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        grid-column:2;
	      }
	      body[data-page="script"] .scriptResultPanel > .scriptPreviewPanel {
	        grid-row:2;
	        margin-top:14px;
	      }
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:1 / -1;
	        grid-row:auto;
	      }
	    }
	    @media (max-width:760px) {
	      body[data-page="script"] #scriptPage.scriptAppPage {
	        margin-top:64px;
	        padding:10px;
	      }
	      body[data-page="script"] header {
	        height:auto;
	        min-height:64px;
	        flex-wrap:wrap;
	        padding:10px 12px;
	      }
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:1fr;
	        gap:10px;
	      }
	      body[data-page="script"] .scriptControlPanel,
	      body[data-page="script"] .scriptLibraryPanel,
	      body[data-page="script"] .scriptBottomPanel,
	      body[data-page="script"] .scriptResultPanel > .scriptPreviewPanel,
	      body[data-page="script"] .scriptResultPanel .backendStep,
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        grid-column:1;
	        grid-row:auto;
	      }
	      body[data-page="script"] .scriptLibraryPanel {
	        min-height:520px;
	      }
	      body[data-page="script"] .scriptPreviewPanel {
	        grid-template-columns:1fr;
	      }
	      body[data-page="script"] .scriptVideoPreview,
	      body[data-page="script"] .scriptVideoMissing {
	        border-right:0;
	        border-bottom:1px solid var(--script-line);
	      }
	    }

	    /* Final script workspace skin, aligned with the local adaptation UI. */
	    body[data-page="script"] {
	      --script-bg:#050506;
	      --script-panel:#101114;
	      --script-panel-solid:#101114;
	      --script-panel-raised:rgba(30,31,34,.84);
	      --script-ink:#f5f0e8;
	      --script-muted:#aaa49a;
	      --script-subtle:#746f67;
	      --script-line:rgba(255,255,255,.15);
	      --script-line-soft:rgba(255,255,255,.075);
	      --script-accent:#f4c96b;
	      --script-accent-pressed:#d9aa43;
	      --script-green:#9bdc8f;
	      --script-red:#ff7c7c;
	      --script-code:#0a0b0d;
		      min-height:100vh !important;
		      overflow:auto !important;
	      background:
	        linear-gradient(180deg, rgba(244,201,107,.08) 0%, rgba(5,5,6,0) 28%),
	        linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px),
	        linear-gradient(180deg, rgba(255,255,255,.028) 1px, transparent 1px),
	        var(--script-bg) !important;
	      background-size:auto, 44px 44px, 44px 44px, auto !important;
	      color:var(--script-ink) !important;
	      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Arial,"PingFang SC","Microsoft YaHei",sans-serif !important;
	    }
	    body[data-page="script"]::before {
	      display:none !important;
	    }
	    body[data-page="script"] header {
	      height:58px !important;
	      min-height:58px !important;
	      padding:0 18px !important;
	      background:rgba(5,5,6,.82) !important;
	      border-bottom:1px solid rgba(255,255,255,.11) !important;
	      box-shadow:none !important;
	      backdrop-filter:saturate(180%) blur(18px) !important;
	      -webkit-backdrop-filter:saturate(180%) blur(18px) !important;
	    }
	    body[data-page="script"] h1 {
	      color:var(--script-ink) !important;
	      font-size:17px !important;
	      font-weight:700 !important;
	    }
	    body[data-page="script"] h1::before {
	      width:24px !important;
	      height:24px !important;
	      border-radius:7px !important;
	      background:linear-gradient(135deg, #7dd8ff, #f4c96b) !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.38) inset !important;
	    }
	    body[data-page="script"] .nav {
	      height:40px !important;
	      padding:3px !important;
	      background:rgba(255,255,255,.055) !important;
	      border:1px solid rgba(255,255,255,.12) !important;
	      border-radius:8px !important;
	    }
	    body[data-page="script"] .nav a {
	      min-height:32px !important;
	      border-radius:6px !important;
	      color:var(--script-muted) !important;
	      font-size:12px !important;
	    }
	    body[data-page="script"] .nav a.active,
	    body[data-page="script"] .nav a:hover {
	      color:#17130a !important;
	      background:linear-gradient(180deg, #ffe08b, var(--script-accent)) !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.3) inset !important;
	    }
	    body[data-page="script"] .status,
	    body[data-page="script"] .filemeta,
	    body[data-page="script"] .cloneStatus {
	      color:var(--script-muted) !important;
	      background:rgba(255,255,255,.055) !important;
	      border:1px solid rgba(255,255,255,.12) !important;
	      border-radius:999px !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.08) inset !important;
	    }
	    body[data-page="script"] #scriptPage.scriptAppPage {
	      height:auto !important;
	      min-height:calc(100vh - 58px) !important;
	      margin:58px 0 0 !important;
	      padding:14px !important;
	      overflow:visible !important;
	      color:var(--script-ink) !important;
	    }
	    body[data-page="script"] .scriptWorkspace {
	      display:grid !important;
	      grid-template-columns:300px minmax(0, 1fr) !important;
	      grid-template-rows:auto auto auto !important;
	      gap:12px !important;
	      height:auto !important;
	      min-height:0 !important;
	      align-items:start !important;
	      background:transparent !important;
	    }
	    body[data-page="script"] .scriptControlPanel,
	    body[data-page="script"] .scriptLibraryPanel,
	    body[data-page="script"] .scriptResultPanel,
	    body[data-page="script"] .scriptBottomPanel {
	      min-width:0 !important;
	      min-height:0 !important;
	      color:var(--script-ink) !important;
	      background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.012)), var(--script-panel) !important;
	      border:1px solid var(--script-line) !important;
	      border-radius:8px !important;
	      box-shadow:0 24px 70px rgba(0,0,0,.34) !important;
	      backdrop-filter:none !important;
	      -webkit-backdrop-filter:none !important;
	    }
	    body[data-page="script"] .scriptControlPanel {
	      grid-column:1 !important;
	      grid-row:1 / span 3 !important;
	      display:flex !important;
	      flex-direction:column !important;
	      gap:10px !important;
	      padding:10px !important;
	      max-height:calc(100vh - 86px) !important;
	      overflow:auto !important;
	      position:sticky !important;
	      top:72px !important;
	      border-right:1px solid var(--script-line) !important;
	    }
	    body[data-page="script"] .scriptLibraryPanel {
	      grid-column:2 !important;
	      grid-row:1 !important;
	      display:flex !important;
	      flex-direction:column !important;
	      height:min(620px, calc(100vh - 130px)) !important;
	      min-height:520px !important;
	      max-height:620px !important;
	      overflow:hidden !important;
	    }
	    body[data-page="script"] .scriptResultPanel {
	      grid-column:2 !important;
	      grid-row:2 !important;
	      display:grid !important;
	      grid-template-columns:minmax(360px, 1.15fr) minmax(280px, .85fr) !important;
	      grid-template-rows:auto auto !important;
	      align-items:start !important;
	      gap:10px !important;
	      padding:10px !important;
	      overflow:visible !important;
	    }
	    body[data-page="script"] .scriptBottomPanel {
	      grid-column:2 !important;
	      grid-row:3 !important;
	      display:flex !important;
	      flex-direction:column !important;
	      min-height:260px !important;
	      overflow:hidden !important;
	      margin:0 !important;
	    }
	    body[data-page="script"] .sectionhead,
	    body[data-page="script"] .scriptLibraryToolbar,
	    body[data-page="script"] .scriptLibraryHeader,
	    body[data-page="script"] .scriptBottomTabs {
	      background:linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.025)) !important;
	      border-bottom:1px solid var(--script-line-soft) !important;
	      color:var(--script-ink) !important;
	    }
	    body[data-page="script"] .sectionhead {
	      min-height:42px !important;
	      padding:8px 10px !important;
	      margin:0 !important;
	    }
	    body[data-page="script"] .sectionhead h2,
	    body[data-page="script"] .scriptStepTitle,
	    body[data-page="script"] .taskBoardHeader,
	    body[data-page="script"] .filebox h2 {
	      color:var(--script-ink) !important;
	      font-size:13px !important;
	      font-weight:700 !important;
	    }
	    body[data-page="script"] .scriptStep,
	    body[data-page="script"] .contextCard,
	    body[data-page="script"] .scriptDetailBlock,
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog {
	      color:var(--script-ink) !important;
	      background:rgba(255,255,255,.04) !important;
	      border:1px solid rgba(255,255,255,.10) !important;
	      border-radius:8px !important;
	      box-shadow:none !important;
	      backdrop-filter:none !important;
	    }
	    body[data-page="script"] .scriptStep {
	      margin:0 !important;
	      padding:12px !important;
	    }
	    body[data-page="script"] .contextCard {
	      padding:10px !important;
	    }
	    body[data-page="script"] .scriptStepNo {
	      width:24px !important;
	      height:24px !important;
	      border-radius:7px !important;
	      background:rgba(244,201,107,.13) !important;
	      color:var(--script-accent) !important;
	      box-shadow:0 0 0 1px rgba(244,201,107,.26) inset !important;
	    }
	    body[data-page="script"] label,
	    body[data-page="script"] .contextCard h3,
	    body[data-page="script"] .inlineHint,
	    body[data-page="script"] .taskBoardMeta,
	    body[data-page="script"] .taskMini,
	    body[data-page="script"] .dirpath,
	    body[data-page="script"] .muted,
	    body[data-page="script"] .empty {
	      color:var(--script-muted) !important;
	    }
	    body[data-page="script"] input,
	    body[data-page="script"] textarea,
	    body[data-page="script"] select,
	    body[data-page="script"] .readonlyValue,
	    body[data-page="script"] .selectedScriptName,
	    body[data-page="script"] .batchDraft {
	      min-height:32px !important;
	      color:var(--script-ink) !important;
	      background:rgba(255,255,255,.065) !important;
	      border:1px solid rgba(255,255,255,.12) !important;
	      border-radius:6px !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.08) inset !important;
	    }
	    body[data-page="script"] input::placeholder,
	    body[data-page="script"] textarea::placeholder {
	      color:rgba(245,240,232,.46) !important;
	    }
	    body[data-page="script"] input:focus,
	    body[data-page="script"] textarea:focus,
	    body[data-page="script"] select:focus {
	      border-color:rgba(244,201,107,.58) !important;
	      outline:0 !important;
	      box-shadow:0 0 0 4px rgba(244,201,107,.14), 0 1px 0 rgba(255,255,255,.08) inset !important;
	    }
	    body[data-page="script"] select option {
	      color:#f5f0e8 !important;
	      background:#17181b !important;
	    }
	    body[data-page="script"] button {
	      min-height:32px !important;
	      color:var(--script-muted) !important;
	      background:rgba(255,255,255,.055) !important;
	      border:1px solid rgba(255,255,255,.12) !important;
	      border-radius:6px !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.08) inset !important;
	    }
	    body[data-page="script"] button:hover {
	      color:var(--script-ink) !important;
	      border-color:rgba(244,201,107,.38) !important;
	      background:rgba(244,201,107,.08) !important;
	    }
	    body[data-page="script"] button.blue,
	    body[data-page="script"] button.primary {
	      color:#17130a !important;
	      background:linear-gradient(180deg, #ffe08b, var(--script-accent)) !important;
	      border-color:rgba(244,201,107,.55) !important;
	    }
	    body[data-page="script"] button.danger {
	      color:#ffc9c9 !important;
	      background:rgba(255,124,124,.08) !important;
	      border-color:rgba(255,124,124,.24) !important;
	    }
	    body[data-page="script"] .scriptLibraryToolbar {
	      min-height:56px !important;
	      padding:10px !important;
	      gap:8px !important;
	      flex:0 0 auto !important;
	    }
	    body[data-page="script"] .scriptSearchShell {
	      height:38px !important;
	      color:var(--script-accent) !important;
	      background:rgba(255,255,255,.065) !important;
	      border:1px solid rgba(255,255,255,.12) !important;
	      border-radius:6px !important;
	    }
	    body[data-page="script"] .scriptSearchShell input {
	      color:var(--script-ink) !important;
	      background:transparent !important;
	      border:0 !important;
	      box-shadow:none !important;
	    }
	    body[data-page="script"] .scriptLibraryHeader {
	      min-height:38px !important;
	      padding:8px 12px !important;
	      flex:0 0 auto !important;
	    }
	    body[data-page="script"] .scriptLibraryPanel > .dirpath {
	      max-height:none !important;
	      padding:8px 12px !important;
	      color:var(--script-muted) !important;
	      background:rgba(255,255,255,.025) !important;
	      border-bottom:1px solid var(--script-line-soft) !important;
	      overflow:hidden !important;
	      text-overflow:ellipsis !important;
	      white-space:nowrap !important;
	      flex:0 0 auto !important;
	    }
	    body[data-page="script"] .scriptPickerShell,
	    body[data-page="script"] .scriptPickerPane,
	    body[data-page="script"] .scriptPickerList {
	      min-height:0 !important;
	      flex:1 1 auto !important;
	      background:transparent !important;
	    }
	    body[data-page="script"] .scriptPickerList {
	      padding:8px !important;
	      overflow:auto !important;
	      max-height:100% !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem {
	      grid-template-columns:52px minmax(0, 1fr) !important;
	      min-height:58px !important;
	      margin:0 0 8px !important;
	      padding:9px !important;
	      color:var(--script-ink) !important;
	      background:rgba(255,255,255,.055) !important;
	      border:1px solid rgba(255,255,255,.10) !important;
	      border-radius:8px !important;
	      box-shadow:none !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem:hover,
	    body[data-page="script"] .scriptPickerList .fileitem.is-selected {
	      background:rgba(244,201,107,.09) !important;
	      border-color:rgba(244,201,107,.36) !important;
	      transform:none !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem.is-selected::before {
	      background:var(--script-accent) !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem > button:first-child {
	      width:44px !important;
	      color:#17130a !important;
	      background:linear-gradient(180deg, #ffe08b, var(--script-accent)) !important;
	      border-color:rgba(244,201,107,.52) !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem > div {
	      max-width:none !important;
	      min-width:0 !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem > div:nth-child(3),
	    body[data-page="script"] .scriptPickerList .fileitem > .scriptFileBadges {
	      grid-column:2 !important;
	      display:flex !important;
	      flex-wrap:wrap !important;
	      gap:4px !important;
	    }
	    body[data-page="script"] .scriptPickerList .filelink {
	      color:var(--script-ink) !important;
	      font-size:12px !important;
	      line-height:17px !important;
	    }
	    body[data-page="script"] .cloneStatus.done {
	      color:var(--script-green) !important;
	      background:rgba(155,220,143,.12) !important;
	      border-color:rgba(155,220,143,.25) !important;
	    }
	    body[data-page="script"] .cloneStatus.pending {
	      color:var(--script-accent) !important;
	      background:rgba(244,201,107,.12) !important;
	      border-color:rgba(244,201,107,.25) !important;
	    }
	    body[data-page="script"] .scriptPreviewPanel {
	      display:grid !important;
	      grid-column:1 !important;
	      grid-row:1 / span 2 !important;
	      grid-template-columns:1fr !important;
	      grid-template-rows:auto auto !important;
	      gap:0 !important;
	      overflow:hidden !important;
	      min-height:0 !important;
	      height:auto !important;
	      flex:initial !important;
	      background:rgba(255,255,255,.04) !important;
	      border:1px solid rgba(255,255,255,.10) !important;
	      border-radius:8px !important;
	    }
	    body[data-page="script"] .scriptVideoPreview,
	    body[data-page="script"] .scriptVideoMissing {
	      min-height:420px !important;
	      height:420px !important;
	      color:var(--script-muted) !important;
	      background:#050506 !important;
	      border-right:0 !important;
	      border-bottom:1px solid var(--script-line-soft) !important;
	    }
	    body[data-page="script"] .scriptVideoPreview video {
	      width:100% !important;
	      height:100% !important;
	      max-height:none !important;
	      object-fit:contain !important;
	      background:#050506 !important;
	    }
	    body[data-page="script"] .scriptDetailBlock {
	      border:0 !important;
	      border-radius:0 !important;
	      background:transparent !important;
	      padding:10px !important;
	      max-height:none !important;
	      overflow:auto !important;
	    }
	    body[data-page="script"] .scriptResultPanel .backendStep,
	    body[data-page="script"] .scriptResultPanel .generationStep {
	      grid-template-columns:1fr !important;
	      margin:0 !important;
	      display:block !important;
	      min-height:0 !important;
	      height:auto !important;
	      max-height:none !important;
	      align-self:stretch !important;
	      overflow:visible !important;
	    }
	    body[data-page="script"] .scriptResultPanel .backendStep {
	      grid-column:2 !important;
	      grid-row:1 !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep {
	      grid-column:2 !important;
	      grid-row:2 !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .buttons {
	      position:static !important;
	      z-index:2 !important;
	      margin-top:10px !important;
	      padding-top:10px !important;
	      background:transparent !important;
	    }
	    body[data-page="script"] .pathrow.promptButtons {
	      display:grid !important;
	      grid-template-columns:1fr 1fr !important;
	      gap:8px !important;
	    }
	    body[data-page="script"] .mutationModeControl {
	      display:grid !important;
	      grid-template-columns:1fr 1fr !important;
	      gap:8px !important;
	    }
	    body[data-page="script"] .mutationModeControl button,
	    body[data-page="script"] .mutationToggle,
	    body[data-page="script"] .mutationCountRow {
	      color:var(--script-ink) !important;
	      background:rgba(255,255,255,.045) !important;
	      border:1px solid rgba(255,255,255,.10) !important;
	      border-radius:8px !important;
	    }
	    body[data-page="script"] .mutationModeControl button.active {
	      color:var(--script-accent) !important;
	      background:rgba(244,201,107,.10) !important;
	      border-color:rgba(244,201,107,.34) !important;
	    }
	    body[data-page="script"] .mutationModeControl button span {
	      color:var(--script-muted) !important;
	    }
	    body[data-page="script"] .mutationToggle input {
	      accent-color:var(--script-accent) !important;
	    }
	    body[data-page="script"] .scriptBottomTabs {
	      min-height:42px !important;
	      padding:0 8px !important;
	    }
	    body[data-page="script"] .scriptBottomTabs button {
	      min-height:42px !important;
	      color:var(--script-muted) !important;
	      border-radius:0 !important;
	      background:transparent !important;
	      border:0 !important;
	    }
	    body[data-page="script"] .scriptBottomTabs button.active {
	      color:var(--script-accent) !important;
	      border-bottom:2px solid var(--script-accent) !important;
	    }
	    body[data-page="script"] .scriptBottomContent {
	      min-height:0 !important;
	      overflow:auto !important;
	      flex:1 1 auto !important;
	    }
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog {
	      margin:8px !important;
	      padding:10px !important;
	    }
	    body[data-page="script"] .progressTrack {
	      background:rgba(255,255,255,.09) !important;
	    }
	    body[data-page="script"] .progressFill {
	      background:linear-gradient(90deg, var(--script-accent), #ffe08b) !important;
	    }
	    body[data-page="script"] .compactLog pre {
	      color:#e8dfd0 !important;
	      background:var(--script-code) !important;
	      border:1px solid rgba(255,255,255,.10) !important;
	      border-radius:8px !important;
	    }
	    @media (min-width:1280px) {
	      body[data-page="script"] #scriptPage.scriptAppPage {
	        padding:14px !important;
	      }
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:300px minmax(620px, 1fr) minmax(440px, 36vw) !important;
	        grid-template-rows:minmax(620px, calc(100vh - 86px)) minmax(260px, auto) !important;
	        align-items:start !important;
	      }
	      body[data-page="script"] .scriptControlPanel {
	        grid-column:1 !important;
	        grid-row:1 / span 2 !important;
	      }
	      body[data-page="script"] .scriptLibraryPanel {
	        grid-column:2 !important;
	        grid-row:1 !important;
	        height:calc(100vh - 86px) !important;
	        min-height:620px !important;
	        max-height:none !important;
	      }
	      body[data-page="script"] .scriptPickerList {
	        height:auto !important;
	        min-height:0 !important;
	      }
	      body[data-page="script"] .scriptPickerList .fileitem {
	        grid-template-columns:52px minmax(0, 1fr) auto !important;
	      }
	      body[data-page="script"] .scriptPickerList .fileitem > div:nth-child(3),
	      body[data-page="script"] .scriptPickerList .fileitem > .scriptFileBadges {
	        grid-column:3 !important;
	        align-self:center !important;
	        justify-content:flex-end !important;
	      }
	      body[data-page="script"] .scriptResultPanel {
	        grid-column:3 !important;
	        grid-row:1 !important;
	        grid-template-columns:1fr !important;
	        grid-template-rows:minmax(360px, 46vh) auto !important;
	        height:calc(100vh - 86px) !important;
	        min-height:620px !important;
	        overflow:auto !important;
	      }
	      body[data-page="script"] .scriptPreviewPanel {
	        grid-column:1 !important;
	        grid-row:1 !important;
	        height:auto !important;
	        min-height:360px !important;
	      }
	      body[data-page="script"] .scriptVideoPreview,
	      body[data-page="script"] .scriptVideoMissing {
	        height:clamp(340px, 46vh, 520px) !important;
	        min-height:340px !important;
	      }
	      body[data-page="script"] .scriptVideoPreview video {
	        width:100% !important;
	        height:100% !important;
	        object-fit:contain !important;
	      }
	      body[data-page="script"] .scriptResultPanel .backendStep {
	        grid-column:1 !important;
	        grid-row:2 !important;
	      }
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        grid-column:1 !important;
	        grid-row:3 !important;
	      }
	      body[data-page="script"] .scriptResultPanel .backendStep,
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        width:100% !important;
	      }
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:2 / span 2 !important;
	        grid-row:2 !important;
	        min-height:260px !important;
	      }
	    }
	    @media (max-width:980px) {
	      body[data-page="script"] #scriptPage.scriptAppPage {
	        overflow:auto !important;
	      }
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:300px minmax(0, 1fr) !important;
	        grid-template-rows:minmax(420px, 58vh) auto minmax(260px, 36vh) !important;
	        height:auto !important;
	        min-height:calc(100vh - 78px) !important;
	      }
	      body[data-page="script"] .scriptControlPanel {
	        grid-column:1 !important;
	        grid-row:1 / span 3 !important;
	        max-height:none !important;
	      }
	      body[data-page="script"] .scriptLibraryPanel {
	        grid-column:2 !important;
	        grid-row:1 !important;
	        min-height:420px !important;
	      }
	      body[data-page="script"] .scriptResultPanel {
	        grid-column:2 !important;
	        grid-row:2 !important;
	        max-height:none !important;
	      }
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:2 !important;
	        grid-row:3 !important;
	      }
	    }
	    @media (max-width:780px) {
	      body[data-page="script"] #scriptPage.scriptAppPage {
	        margin-top:58px !important;
	        padding:8px !important;
	      }
	      body[data-page="script"] header {
	        height:auto !important;
	        min-height:58px !important;
	        padding:9px 10px !important;
	      }
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:1fr !important;
	        grid-template-rows:auto !important;
	      }
	      body[data-page="script"] .scriptControlPanel,
	      body[data-page="script"] .scriptLibraryPanel,
	      body[data-page="script"] .scriptResultPanel,
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:1 !important;
	        grid-row:auto !important;
	      }
	      body[data-page="script"] .scriptPreviewPanel,
	      body[data-page="script"] .mutationModeControl,
	      body[data-page="script"] .pathrow.promptButtons {
	        grid-template-columns:1fr !important;
	      }
	      body[data-page="script"] .scriptVideoPreview,
	      body[data-page="script"] .scriptVideoMissing {
	        border-right:0 !important;
	        border-bottom:1px solid var(--script-line-soft) !important;
	      }
	    }

	    body[data-page="script"] #scriptPage.scriptAppPage {
	      padding:18px 20px 22px !important;
	      overflow:auto !important;
	    }
	    body[data-page="script"] .scriptWorkspace {
	      grid-template-columns:minmax(280px, 320px) minmax(0, 1fr) !important;
	      grid-template-rows:auto auto minmax(240px, auto) !important;
	      gap:16px !important;
	      max-width:1680px !important;
	      margin:0 auto !important;
	      align-items:start !important;
	    }
	    body[data-page="script"] .scriptControlPanel,
	    body[data-page="script"] .scriptLibraryPanel,
	    body[data-page="script"] .scriptResultPanel,
	    body[data-page="script"] .scriptBottomPanel {
	      border-radius:8px !important;
	      box-shadow:0 18px 44px rgba(0,0,0,.24) !important;
	    }
	    body[data-page="script"] .scriptControlPanel {
	      grid-column:1 !important;
	      grid-row:1 / span 3 !important;
	      gap:14px !important;
	      padding:14px !important;
	      max-height:calc(100vh - 94px) !important;
	      position:static !important;
	      top:auto !important;
	    }
	    body[data-page="script"] .scriptSideNav,
	    body[data-page="script"] .scriptLibraryToolbar > button {
	      display:none !important;
	    }
	    body[data-page="script"] .scriptLibraryPanel {
	      grid-column:2 !important;
	      grid-row:1 !important;
	      height:min(520px, calc(100vh - 142px)) !important;
	      min-height:430px !important;
	      max-height:none !important;
	    }
	    body[data-page="script"] .scriptResultPanel {
	      grid-column:2 !important;
	      grid-row:2 !important;
	      display:grid !important;
	      grid-template-columns:minmax(320px, .95fr) minmax(340px, 1.05fr) !important;
	      grid-template-rows:auto auto !important;
	      gap:16px !important;
	      padding:14px !important;
	      overflow:visible !important;
	    }
	    body[data-page="script"] .scriptBottomPanel {
	      grid-column:2 !important;
	      grid-row:3 !important;
	      min-height:240px !important;
	    }
	    body[data-page="script"] .sectionhead,
	    body[data-page="script"] .scriptLibraryToolbar,
	    body[data-page="script"] .scriptLibraryHeader,
	    body[data-page="script"] .scriptBottomTabs {
	      padding-left:14px !important;
	      padding-right:14px !important;
	    }
	    body[data-page="script"] .scriptLibraryToolbar {
	      min-height:62px !important;
	    }
	    body[data-page="script"] .scriptSearchShell {
	      width:100% !important;
	      max-width:none !important;
	    }
	    body[data-page="script"] .scriptStep {
	      padding:15px !important;
	    }
	    body[data-page="script"] .scriptStep,
	    body[data-page="script"] .contextCard,
	    body[data-page="script"] .scriptDetailBlock,
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog {
	      border-color:rgba(255,255,255,.12) !important;
	    }
	    body[data-page="script"] label {
	      margin-top:10px !important;
	      font-size:12px !important;
	    }
	    body[data-page="script"] input,
	    body[data-page="script"] textarea,
	    body[data-page="script"] select,
	    body[data-page="script"] .readonlyValue,
	    body[data-page="script"] .selectedScriptName,
	    body[data-page="script"] .batchDraft {
	      width:100% !important;
	      min-height:40px !important;
	      box-sizing:border-box !important;
	      line-height:1.45 !important;
	    }
	    body[data-page="script"] .selectedScriptName,
	    body[data-page="script"] .batchDraft,
	    body[data-page="script"] .dirpath {
	      white-space:normal !important;
	      overflow-wrap:anywhere !important;
	    }
	    body[data-page="script"] .scriptPickerList {
	      padding:12px !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem {
	      min-height:70px !important;
	      padding:12px !important;
	      margin-bottom:10px !important;
	    }
	    body[data-page="script"] .scriptPickerList .filelink {
	      font-size:13px !important;
	      line-height:1.55 !important;
	    }
	    body[data-page="script"] .scriptPreviewPanel {
	      grid-column:1 !important;
	      grid-row:1 / span 2 !important;
	      min-height:0 !important;
	    }
	    body[data-page="script"] .scriptVideoPreview,
	    body[data-page="script"] .scriptVideoMissing {
	      height:clamp(220px, 30vh, 340px) !important;
	      min-height:220px !important;
	    }
	    body[data-page="script"] .scriptResultPanel .backendStep {
	      grid-column:2 !important;
	      grid-row:1 !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep {
	      grid-column:2 !important;
	      grid-row:2 !important;
	    }
	    body[data-page="script"] .scriptResultPanel .backendStep,
	    body[data-page="script"] .scriptResultPanel .generationStep {
	      width:100% !important;
	      overflow:visible !important;
	    }
	    body[data-page="script"] .mutationModeControl,
	    body[data-page="script"] .pathrow.promptButtons {
	      gap:10px !important;
	    }
	    body[data-page="script"] .mutationModeControl button {
	      padding:12px !important;
	      text-align:left !important;
	    }
	    body[data-page="script"] .mutationCountRow {
	      padding:12px !important;
	      gap:10px !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .buttons {
	      display:grid !important;
	      grid-template-columns:minmax(0, 1fr) auto !important;
	      gap:10px !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .buttons button {
	      min-height:44px !important;
	      padding:0 18px !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .inlineHint {
	      display:none !important;
	    }
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog {
	      margin:12px !important;
	      padding:14px !important;
	    }
	    @media (min-width:1500px) {
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:320px minmax(560px, 1fr) minmax(400px, 440px) !important;
	        grid-template-rows:minmax(620px, calc(100vh - 98px)) minmax(240px, auto) !important;
	      }
	      body[data-page="script"] .scriptLibraryPanel {
	        grid-column:2 !important;
	        grid-row:1 !important;
	        height:calc(100vh - 98px) !important;
	        min-height:620px !important;
	      }
	      body[data-page="script"] .scriptResultPanel {
	        grid-column:3 !important;
	        grid-row:1 !important;
	        display:flex !important;
	        flex-direction:column !important;
	        height:calc(100vh - 98px) !important;
	        min-height:620px !important;
	        overflow:auto !important;
	      }
	      body[data-page="script"] .scriptPreviewPanel,
	      body[data-page="script"] .scriptResultPanel .backendStep,
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        width:100% !important;
	      }
	      body[data-page="script"] .scriptPreviewPanel {
	        flex:0 0 auto !important;
	      }
	      body[data-page="script"] .scriptVideoPreview,
	      body[data-page="script"] .scriptVideoMissing {
	        height:clamp(220px, 26vh, 300px) !important;
	      }
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:2 / span 2 !important;
	        grid-row:2 !important;
	      }
	    }
	    @media (max-width:1180px) {
	      body[data-page="script"] #scriptPage.scriptAppPage {
	        padding:14px !important;
	      }
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:1fr !important;
	        grid-template-rows:auto !important;
	      }
	      body[data-page="script"] .scriptControlPanel,
	      body[data-page="script"] .scriptLibraryPanel,
	      body[data-page="script"] .scriptResultPanel,
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:1 !important;
	        grid-row:auto !important;
	        position:static !important;
	        max-height:none !important;
	      }
	      body[data-page="script"] .scriptLibraryPanel {
	        height:auto !important;
	      }
	      body[data-page="script"] .scriptPickerList {
	        max-height:460px !important;
	      }
	    }
	    @media (max-width:860px) {
	      body[data-page="script"] .scriptResultPanel {
	        grid-template-columns:1fr !important;
	      }
	      body[data-page="script"] .scriptPreviewPanel,
	      body[data-page="script"] .scriptResultPanel .backendStep,
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        grid-column:1 !important;
	        grid-row:auto !important;
	      }
	      body[data-page="script"] .scriptResultPanel .generationStep .buttons,
	      body[data-page="script"] .mutationModeControl,
	      body[data-page="script"] .pathrow.promptButtons {
	        grid-template-columns:1fr !important;
	      }
	    }
	    body[data-page="script"] {
	      background:
	        linear-gradient(180deg, rgba(16,18,20,.96) 0, rgba(16,18,20,.96) 72px, transparent 72px),
	        linear-gradient(135deg, #f8f7f2 0%, #eef1ef 52%, #f7f6f0 100%) !important;
	      color:var(--text) !important;
	      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif !important;
	    }
	    body[data-page="script"] header {
	      position:sticky !important;
	      height:auto !important;
	      min-height:72px !important;
	      padding:0 30px !important;
	      background:rgba(18,20,22,.86) !important;
	      border-bottom:1px solid rgba(255,255,255,.1) !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.05) inset, 0 20px 42px rgba(0,0,0,.18) !important;
	      backdrop-filter:saturate(160%) blur(18px) !important;
	    }
	    body[data-page="script"] h1 { color:#f9f7f0 !important; }
	    body[data-page="script"] h1::before { display:block !important; }
	    body[data-page="script"] .nav {
	      height:auto !important;
	      padding:4px !important;
	      border-radius:8px !important;
	      background:rgba(255,255,255,.07) !important;
	      border:1px solid rgba(255,255,255,.09) !important;
	    }
	    body[data-page="script"] .nav a {
	      min-height:34px !important;
	      border-radius:6px !important;
	      border-bottom:0 !important;
	      color:rgba(255,255,255,.68) !important;
	    }
	    body[data-page="script"] .nav a.active,
	    body[data-page="script"] .nav a:hover {
	      background:#f8f5ee !important;
	      color:#161719 !important;
	      box-shadow:0 1px 0 rgba(255,255,255,.72) inset, 0 10px 22px rgba(0,0,0,.22) !important;
	    }
	    body[data-page="script"] .scriptControlPanel,
	    body[data-page="script"] .scriptLibraryPanel,
	    body[data-page="script"] .scriptResultPanel,
	    body[data-page="script"] .scriptBottomPanel,
	    body[data-page="script"] .scriptStep,
	    body[data-page="script"] .contextCard,
	    body[data-page="script"] .scriptDetailBlock,
	    body[data-page="script"] .taskProgress,
	    body[data-page="script"] .taskBoard,
	    body[data-page="script"] .filebox,
	    body[data-page="script"] .compactLog {
	      background:var(--panel) !important;
	      color:var(--text) !important;
	      border-color:var(--line) !important;
	      box-shadow:var(--shadow-soft) !important;
	    }
	    body[data-page="script"] .scriptControlPanel *,
	    body[data-page="script"] .scriptLibraryPanel *,
	    body[data-page="script"] .scriptResultPanel *,
	    body[data-page="script"] .scriptBottomPanel * {
	      color:inherit;
	    }
	    body[data-page="script"] h2,
	    body[data-page="script"] h3,
	    body[data-page="script"] label,
	    body[data-page="script"] .scriptStepTitle,
	    body[data-page="script"] .taskBoardHeader,
	    body[data-page="script"] .sectionhead h2,
	    body[data-page="script"] .filebox h2,
	    body[data-page="script"] .selectedScriptName,
	    body[data-page="script"] .batchDraft,
	    body[data-page="script"] .readonlyValue {
	      color:var(--text) !important;
	    }
	    body[data-page="script"] .muted,
	    body[data-page="script"] .dirpath,
	    body[data-page="script"] .filemeta,
	    body[data-page="script"] .cloneStatus,
	    body[data-page="script"] .inlineHint,
	    body[data-page="script"] .taskMini,
	    body[data-page="script"] .taskBoardMeta,
	    body[data-page="script"] .empty,
	    body[data-page="script"] .scriptVideoMeta {
	      color:var(--muted) !important;
	    }
	    body[data-page="script"] input,
	    body[data-page="script"] select,
	    body[data-page="script"] textarea,
	    body[data-page="script"] .selectedScriptName,
	    body[data-page="script"] .batchDraft,
	    body[data-page="script"] .readonlyValue {
	      background:#fff !important;
	      color:var(--text) !important;
	      border:1px solid var(--line) !important;
	      box-shadow:none !important;
	    }
	    body[data-page="script"] input::placeholder,
	    body[data-page="script"] textarea::placeholder {
	      color:#8d95a1 !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem,
	    body[data-page="script"] .scriptStep,
	    body[data-page="script"] .contextCard,
	    body[data-page="script"] .scriptDetailBlock,
	    body[data-page="script"] .taskCard {
	      background:#fff !important;
	      color:var(--text) !important;
	      border-color:var(--line) !important;
	    }
	    body[data-page="script"] .scriptPickerList .fileitem.is-selected,
	    body[data-page="script"] .scriptPickerList .fileitem:hover,
	    body[data-page="script"] .mutationModeControl button.active {
	      background:#fff8e7 !important;
	      color:var(--text) !important;
	      border-color:rgba(242,184,64,.55) !important;
	    }
	    body[data-page="script"] .scriptPickerList .filelink,
	    body[data-page="script"] .scriptPickerList .fileitem > button:first-child,
	    body[data-page="script"] .scriptBottomTabs button,
	    body[data-page="script"] .mutationModeControl button {
	      color:var(--text) !important;
	    }
	    body[data-page="script"] .scriptBottomTabs button.active {
	      color:#b77900 !important;
	      border-color:#f2b840 !important;
	    }
	    body[data-page="script"] .scriptStepNo {
	      color:#b77900 !important;
	      background:#fff6db !important;
	      border-color:#f2d488 !important;
	    }
	    body[data-page="script"] .cloneStatus.done {
	      color:#147a4a !important;
	      background:#eef9f2 !important;
	      border-color:#bfe8cc !important;
	    }
	    body[data-page="script"] .cloneStatus.pending {
	      color:#ad7511 !important;
	      background:#fff8e6 !important;
	      border-color:#f4d58b !important;
	    }
	    body[data-page="script"] button.blue,
	    body[data-page="script"] button.primary {
	      background:var(--ink) !important;
	      color:#fff !important;
	      border-color:var(--ink) !important;
	    }
	    @media (min-width:1280px) {
	      body[data-page="script"] #scriptPage.scriptAppPage {
	        padding:24px 28px 30px !important;
	      }
	      body[data-page="script"] .scriptWorkspace {
	        grid-template-columns:minmax(280px, 300px) minmax(620px, 1fr) minmax(400px, 440px) !important;
	        grid-template-rows:clamp(500px, 58vh, 560px) auto minmax(240px, auto) !important;
	        column-gap:24px !important;
	        row-gap:18px !important;
	        max-width:none !important;
	        width:100% !important;
	      }
	      body[data-page="script"] .scriptControlPanel {
	        grid-column:1 !important;
	        grid-row:1 / span 3 !important;
	        align-self:start !important;
	        max-height:clamp(500px, 58vh, 560px) !important;
	      }
	      body[data-page="script"] .scriptLibraryPanel {
	        grid-column:2 !important;
	        grid-row:1 !important;
	        height:clamp(500px, 58vh, 560px) !important;
	        min-height:500px !important;
	      }
	      body[data-page="script"] .scriptResultPanel {
	        display:contents !important;
	        padding:0 !important;
	        border:0 !important;
	        box-shadow:none !important;
	        background:transparent !important;
	      }
	      body[data-page="script"] .scriptPreviewPanel {
	        grid-column:3 !important;
	        grid-row:1 !important;
	        display:flex !important;
	        flex-direction:column !important;
	        height:clamp(500px, 58vh, 560px) !important;
	        min-height:500px !important;
	        min-width:0 !important;
	        overflow:hidden !important;
	        background:var(--panel) !important;
	        border:1px solid var(--line) !important;
	        border-radius:8px !important;
	        box-shadow:var(--shadow-soft) !important;
	      }
	      body[data-page="script"] .scriptVideoPreview,
	      body[data-page="script"] .scriptVideoMissing {
	        flex:0 0 auto !important;
	        height:clamp(220px, 28vh, 300px) !important;
	        min-height:220px !important;
	      }
	      body[data-page="script"] .scriptDetailBlock {
	        flex:1 1 auto !important;
	        min-height:0 !important;
	        overflow:auto !important;
	        padding:14px !important;
	      }
	      body[data-page="script"] .scriptResultPanel .backendStep,
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        width:auto !important;
	        min-width:0 !important;
	        background:var(--panel) !important;
	        border:1px solid var(--line) !important;
	        border-radius:8px !important;
	        box-shadow:var(--shadow-soft) !important;
	        overflow:visible !important;
	      }
	      body[data-page="script"] .scriptResultPanel .backendStep {
	        grid-column:2 !important;
	        grid-row:2 !important;
	      }
	      body[data-page="script"] .scriptResultPanel .generationStep {
	        grid-column:3 !important;
	        grid-row:2 !important;
	      }
	      body[data-page="script"] .scriptResultPanel .generationStep .scriptStepTitle,
	      body[data-page="script"] .scriptResultPanel .generationStep label,
	      body[data-page="script"] .scriptResultPanel .generationStep .pathrow,
	      body[data-page="script"] .scriptResultPanel .generationStep .mutationToggle,
	      body[data-page="script"] .scriptResultPanel .generationStep .mutationModeControl,
	      body[data-page="script"] .scriptResultPanel .generationStep .mutationCountRow,
	      body[data-page="script"] .scriptResultPanel .generationStep .batchLabel,
	      body[data-page="script"] .scriptResultPanel .generationStep .batchDraft,
	      body[data-page="script"] .scriptResultPanel .generationStep .buttons {
	        position:static !important;
	        opacity:1 !important;
	        transform:none !important;
	      }
	      body[data-page="script"] .scriptBottomPanel {
	        grid-column:2 / span 2 !important;
	        grid-row:3 !important;
	      }
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow {
	      grid-column:1 / -1 !important;
	      display:grid !important;
	      grid-template-columns:minmax(0, 1fr) auto !important;
	      align-items:center !important;
	      gap:10px !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationToggle,
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationCountRow {
	      grid-column:auto !important;
	      margin:0 !important;
	      min-height:42px !important;
	      border:1px solid #d7dce2 !important;
	      border-radius:7px !important;
	      background:#fff !important;
	      color:#171a1d !important;
	      box-shadow:none !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationToggle {
	      display:flex !important;
	      align-items:center !important;
	      gap:9px !important;
	      padding:0 12px !important;
	      font-size:14px !important;
	      font-weight:780 !important;
	      white-space:nowrap !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationCountRow {
	      display:grid !important;
	      grid-template-columns:auto 88px !important;
	      gap:10px !important;
	      align-items:center !important;
	      padding:0 10px !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationCountRow label {
	      color:#171a1d !important;
	      font-size:14px !important;
	      font-weight:780 !important;
	      white-space:nowrap !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationCountRow input {
	      min-height:34px !important;
	      height:34px !important;
	      color:#171a1d !important;
	      background:#f8fafc !important;
	      border-color:#c9d1dc !important;
	      font-weight:800 !important;
	      text-align:center !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .promptButtons button {
	      color:#171a1d !important;
	      background:#fff8e7 !important;
	      border-color:#d8b55f !important;
	      opacity:1 !important;
	      font-weight:780 !important;
	      text-shadow:none !important;
	    }
	    body[data-page="script"] .scriptResultPanel .generationStep .promptButtons button:hover {
	      background:#fff1c7 !important;
	      border-color:#c9921f !important;
	    }
	    @media (max-width: 760px) {
	      body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow {
	        grid-template-columns:1fr !important;
	      }
	      body[data-page="script"] .scriptResultPanel .generationStep .mutationControlsRow .mutationCountRow {
	        grid-template-columns:minmax(0, 1fr) 88px !important;
	      }
	    }
	  </style>
</head>
  <body data-page="home">
  <header>
    <div class="headleft">
      <h1>OPC 跨境电商 Agent 控制台</h1>
    </div>
    <div class="status"><span id="dot" class="dot running"></span><span id="statusText">控制台在线</span></div>
  </header>
  <div id="toast" class="toast"></div>
  <main id="homePage" class="page homePage">
    <div class="homeHero">
      <div>
        <span class="eyebrow">OPC Agent Portal</span>
        <h2>把跨境电商内容生产，升级成可量化的增长基础设施。</h2>
        <p>OPC 面向的是从选品验证、爆款素材研究、脚本生成到视频资产产出的完整内容增长链路。它不把创作当成一次性任务，而是把每一次采集、拆解、改写、适配和产出都沉淀为可复用的业务资产。</p>
        <p>这个入口只负责统一检测、启动和进入八个独立 agent。每个 agent 仍然保留自己的配置、运行方式和输出边界，你可以按自己的判断单独使用任意一个能力，而不是被迫走固定流程。</p>
        <p>对用户来说，这是一个 OPC 跨境电商内容量化增长引擎；对工程来说，它是八个互相独立、可以持续升级的本地 agent 系统。</p>
      </div>
    </div>

    <div class="pageintro">
      <div>
        <h2>Agent 启动台</h2>
        <p class="muted">先点“启动/检测”确认本地网页服务，再进入对应 agent。入口只负责连接，不改变各 agent 的业务设置。</p>
      </div>
    </div>
    <div class="workflowMap">
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">01</span><h3>视频采集</h3></div>
        <p>按可选关键词、国家和三级类目采集竞品商品关联视频，并下载无水印素材。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('collect')">启动/检测</button><span id="agentStatus_collect" class="agentStatus">检测中</span><a class="stageLink" href="__HOT_VIDEO_AGENT_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">02</span><h3>脚本解析</h3></div>
        <p>结合爆款内容知识库，把视频拆成镜头、文案、情绪、转化逻辑和素材类型。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('analyze')">启动/检测</button><span id="agentStatus_analyze" class="agentStatus">检测中</span><a class="stageLink" href="__VIDEO_TEARDOWN_AGENT_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">03</span><h3>脚本产出</h3></div>
        <p>选择产品信息 Markdown 和竞品拆解/爆款脚本，生成自家产品带货脚本。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('script')">启动/检测</button><span id="agentStatus_script" class="agentStatus">检测中</span><a class="stageLink" href="__SCRIPT_PRODUCTION_AGENT_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">04</span><h3>脚本适配</h3></div>
        <p>把成品脚本整理成可交给大模型的视频文案和首帧图片提示词上下文。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('adapt')">启动/检测</button><span id="agentStatus_adapt" class="agentStatus">检测中</span><a class="stageLink" href="__SCRIPT_ADAPTATION_AGENT_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">05</span><h3>视频产出</h3></div>
        <p>进入视频片段产出 agent，按对应模型生成图片、故事版图和视频片段。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('assemble')">启动/检测</button><span id="agentStatus_assemble" class="agentStatus">检测中</span><a class="stageLink" href="__VIDEO_OUTPUT_AGENT_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">06</span><h3>成品管理</h3></div>
        <p>管理已经产出的成品视频，集中查看、筛选、预览和归档最终交付资产。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('finished')">启动/检测</button><span id="agentStatus_finished" class="agentStatus">检测中</span><a class="stageLink" href="__FINISHED_VIDEO_MANAGER_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">07</span><h3>产品脚本改写</h3></div>
        <p>把已有爆款产品脚本改写成目标产品可直接使用的带货脚本。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('rewrite')">启动/检测</button><span id="agentStatus_rewrite" class="agentStatus">检测中</span><a class="stageLink" href="__PRODUCT_SCRIPT_REWRITE_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
      <div class="flowStep">
        <div class="flowStepTop"><span class="stepNo">08</span><h3>片段合成</h3></div>
        <p>扫描已生成的视频片段，确认待拼接项目，并在本地离线合成成品视频。</p>
        <div class="agentActions"><button class="agentStartButton" onclick="startAgentService('compose')">启动/检测</button><span id="agentStatus_compose" class="agentStatus">检测中</span><a class="stageLink" href="__VIDEO_ASSEMBLY_AGENT_URL__" target="_blank" rel="noopener noreferrer">进入</a></div>
      </div>
    </div>
  </main>
  <main id="collectPage" class="page">
    <div class="pageintro">
      <div>
        <h2>爆款采集</h2>
        <p class="muted">按可选关键词、国家和三级类目采集商品关联视频，并自动下载视频素材。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>爆款采集参数</h2>
        <span class="filemeta">本地保存</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="collectProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow">
          <input id="collect_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="collectProductProjectHint" class="contextSummary">请选择产品信息 Markdown，采集结果会按该产品进入采集 agent 的输出目录。</div>
      </div>
      <label>手机号</label>
      <input id="phone" autocomplete="off" />
      <label>密码</label>
      <input id="password" type="password" autocomplete="off" />
      <label>关键词（可选）</label>
      <input id="keyword" placeholder="可留空，仅按国家、类目和筛选条件采集" />
      <div class="fastmossFilters">
        <input id="country" type="hidden" />
        <input id="category_path" type="hidden" />
        <input id="shop_type" type="hidden" />
        <input id="product_status" type="hidden" />
        <div class="filterGrid">
          <div class="filterRow">
            <div class="filterLabel">国家/地区</div>
            <select id="country_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">一级类目</div>
            <select id="category_level1_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">二级类目</div>
            <select id="category_level2_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">三级类目</div>
            <select id="category_level3_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">店铺类型</div>
            <select id="shop_type_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">商品状态</div>
            <select id="product_status_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">商品类型</div>
            <select id="product_type_select"></select>
          </div>
          <div class="filterRow">
            <div class="filterLabel">已选分类</div>
            <div id="selectedCategoryCondition" class="selectedCondition">全部</div>
          </div>
        </div>
        <div class="selectGrid">
          <div>
            <label>达人出单率</label>
            <select id="creator_conversion_rate_filter"></select>
          </div>
          <div>
            <label>总销量</label>
            <select id="total_sales_filter"></select>
          </div>
          <div>
            <label>总GMV</label>
            <select id="total_gmv_filter"></select>
          </div>
          <div>
            <label>近7天销量</label>
            <select id="sales_7d_filter"></select>
          </div>
          <div>
            <label>近7天GMV</label>
            <select id="gmv_7d_filter"></select>
          </div>
          <div>
            <label>带货达人数</label>
            <select id="creator_count_filter"></select>
          </div>
          <div>
            <label>佣金比例</label>
            <select id="commission_rate_filter"></select>
          </div>
          <div>
            <label>带货方式</label>
            <select id="shipping_method_filter"></select>
          </div>
        </div>
      </div>
      <div class="grid2">
        <div><label>商品链接数量</label><input id="product_limit" type="number" min="1" /></div>
        <div><label>每商品视频数量</label><input id="videos_per_product" type="number" min="1" /></div>
      </div>
      <label class="checkline"><input id="show_browser" type="checkbox" /> 显示浏览器窗口</label>
      <div class="buttons">
        <button class="primary" onclick="saveConfig()">保存设置</button>
        <button class="blue" onclick="startTask('full')">一键采集</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">默认启动后最小化浏览器窗口，你只看日志。遇到验证码或滑块时，勾选「显示浏览器窗口」后重新运行，手动完成验证即可。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="collectLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>CSV 输出</h2>
          <div id="csvFiles" class="muted">加载中...</div>
        </div>
        <div class="filebox">
          <h2>视频下载目录</h2>
          <div id="downloadDirs" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <main id="productPage" class="page">
    <div class="pageintro">
      <div>
        <h2>产品信息</h2>
        <p class="muted">这里保留为产品资料入口。统一控制台的各 agent 会从已有产品信息 Markdown 中选择产品。</p>
      </div>
    </div>
    <div class="workspace product">
      <section>
        <div class="sectionhead">
          <h2>我的产品资料</h2>
          <span class="filemeta">本地保存</span>
        </div>
        <div class="contextCard">
          <h3>产品 MD 资料库 <span id="productProductProjectBadge" class="filemeta">未选择</span></h3>
          <div class="pathrow">
            <input id="product_product_project_root" readonly placeholder="产品信息 Markdown 资料库目录" />
            <input id="product_profile_path" type="hidden" />
            <button onclick="openLocalPath(product_product_project_root.value)">打开项目目录</button>
            <button onclick="openLocalPath(product_profile_path.value)">打开产品信息</button>
          </div>
          <div id="productProductProjectHint" class="contextSummary">统一控制台从产品信息 Markdown 选择产品，不强制走完整产品项目流程。</div>
        </div>
        <div class="formSection">
          <h3>基础识别</h3>
          <div class="grid2">
            <div>
              <label>市场 / 地区</label>
              <input id="product_market" placeholder="例如：马来西亚 TikTok 市场" />
            </div>
            <div>
              <label>收集日期</label>
              <input id="product_collection_date" placeholder="例如：2026-04-30" />
            </div>
          </div>
          <div class="grid2">
            <div>
              <label>产品名</label>
              <input id="product_product_name" placeholder="例如：泡泡染发洗发水" />
            </div>
            <div>
              <label>英文名</label>
              <input id="product_english_name" placeholder="例如：Bubble Hair Dye Shampoo" />
            </div>
          </div>
          <label>类目</label>
          <input id="product_category" placeholder="例如：美妆个护 > 美发护发 > 染发霜/染发剂" />
          <div class="grid2">
            <div>
              <label>规格</label>
              <input id="product_spec" placeholder="例如：500ml/瓶" />
            </div>
            <div>
              <label>作用时间</label>
              <input id="product_action_time" placeholder="例如：15-25 分钟" />
            </div>
          </div>
          <label>色号</label>
          <textarea id="product_colors" placeholder="例如：自然黑、棕黑色、咖啡色、栗棕色、黑茶色（共5色）"></textarea>
        </div>

        <div class="formSection">
          <h3>定价策略</h3>
          <div class="grid2">
            <div>
              <label>日常价</label>
              <input id="product_regular_price" placeholder="例如：40 马来币" />
            </div>
            <div>
              <label>活动价</label>
              <input id="product_promo_price" placeholder="例如：20.9 马来币" />
            </div>
          </div>
        </div>

        <div class="formSection">
          <h3>TOP 3 核心卖点</h3>
          <textarea id="product_top_selling_points" class="tall" placeholder="按 1/2/3 填写核心卖点，例如：极简操作、天然植物成分、发色自然持久。"></textarea>
        </div>

        <div class="formSection">
          <h3>目标人群 × 痛点矩阵</h3>
          <textarea id="product_audience_pain_matrix" class="tall" placeholder="按人群整理痛点矩阵，例如：白发遮盖族、上班族、年轻爱美人士、居家 DIY 新手。"></textarea>
        </div>

        <div class="formSection">
          <h3>核心痛点与转化话术</h3>
          <textarea id="product_pain_conversion_talk_tracks" class="tall" placeholder="按人群写痛点和话术方向，例如：15分钟泡泡一按一洗、洗澡顺便染发。"></textarea>
        </div>

        <div class="formSection">
          <h3>营销推广切入点（TikTok）</h3>
          <textarea id="product_tiktok_marketing_angles" class="tall" placeholder="填写切入角度、目标人群和关键钩子，例如：15分钟洗掉白发、洗澡顺便染发。"></textarea>
        </div>

        <div class="formSection">
          <h3>西班牙 / 东南亚市场关键词参考</h3>
          <textarea id="product_market_keywords" class="tall" placeholder="例如：bubble hair dye、15 min covering grey、no mess hair dye。"></textarea>
        </div>

        <div class="formSection">
          <h3>适配素材类型建议</h3>
          <textarea id="product_material_type_suggestions" class="tall" placeholder="例如：洗护痛点对比、视觉诊断、15秒快手教程、读心式困惑、暴露缺点。"></textarea>
        </div>

        <div class="formSection">
          <h3>补充备注</h3>
          <textarea id="product_notes" class="tall" placeholder="其他无法归类但生成脚本时必须保留的信息。"></textarea>
        </div>
        <div class="buttons">
          <button class="primary" onclick="saveProductProfile()">创建/保存产品资料</button>
        </div>
        <p class="muted">保存后会更新本地产品资料。统一控制台推荐直接选择已有产品信息 Markdown 作为各 agent 的产品确认来源。</p>
      </section>
      <section>
        <h2>后续用途</h2>
        <div class="infoList">
          <div class="infoItem">
            <strong>1. 对齐当前产品资料</strong>
            <span class="muted">拆解竞品脚本后，用你的产品卖点替换竞品产品，不会只复刻形式。</span>
          </div>
          <div class="infoItem">
            <strong>2. 控制转化重点</strong>
            <span class="muted">价格、优惠、信任背书和禁用表达会约束脚本生成方向。</span>
          </div>
          <div class="infoItem">
            <strong>3. 支持脚本产出</strong>
            <span class="muted">把「视频拆解结果 + 产品信息」合并，让模型输出你的带货脚本。</span>
          </div>
        </div>
      </section>
    </div>
  </main>
  <main id="analyzePage" class="page">
    <div class="pageintro">
      <div>
        <h2>视频拆解</h2>
        <p class="muted">选择本地 MP4 或包含 MP4 的目录，用保存的模型和提示词拆解爆款视频。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>视频拆解参数</h2>
        <span class="filemeta">本地保存</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="analyzeProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow is-hidden">
          <input id="analyze_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="analyzeProductProjectHint" class="contextSummary">请选择产品信息 Markdown，拆解结果会按该产品进入解析 agent 的输出目录。</div>
      </div>
      <label>ModelMesh API Key</label>
      <input id="modelmesh_api_key" type="password" autocomplete="off" placeholder="只保存在本地 app_config.json" />
      <label>拆解模型</label>
      <select id="video_analysis_model">
        <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
        <option value="google/gemini-3-flash">Gemini 3 Flash Preview</option>
        <option value="google/gemini-3.1-flash-lite-preview">Gemini 3.1 Flash Lite Preview</option>
        <option value="google/gemini-3.1-pro-preview">Gemini 3.1 Pro Preview</option>
        <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
        <option value="google/gemini-2.5-pro">Gemini 2.5 Pro</option>
      </select>
      <label>接口 Base URL</label>
      <input id="modelmesh_base_url" />
      <label>爆款内容知识库</label>
      <div class="pathrow">
        <input id="video_teardown_knowledge_base_path" placeholder="knowledge_base/hot_content_knowledge_base.md" />
        <button onclick="openLocalPath(video_teardown_knowledge_base_path.value)">打开文件</button>
      </div>
      <label>拆解提示词文件</label>
      <div class="pathrow">
        <input id="video_analysis_prompt_path" readonly placeholder="workflow_configs/video_teardown/config/video_teardown_prompt.md" />
        <button onclick="openLocalPath(video_analysis_prompt_path.value)">打开文件</button>
      </div>
      <label>拆解视频路径</label>
      <div class="pathrow">
        <input id="analysis_input_path" placeholder="请选择 MP4 视频或包含 MP4 的目录" />
        <button onclick="chooseAnalysisPath('folder')">选择目录</button>
        <button onclick="chooseAnalysisPath('file')">选择视频</button>
      </div>
      <label>爆款视频拆解提示词</label>
      <textarea id="video_analysis_prompt" class="prompt" placeholder="粘贴或修改你的爆款视频拆解提示词；留空时使用最小测试提示词"></textarea>
      <div class="buttons">
        <button class="primary" onclick="saveTeardownDefaults()">保存设置</button>
        <button class="blue" onclick="startTask('analyze')">拆解视频</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">选择目录时会拆解目录下全部 MP4；选择单个视频时只拆解该视频。爆款内容知识库服务于视频拆解和脚本适配；脚本产出单独读取当前产品错题本。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="analyzeLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>视频拆解结果</h2>
          <div id="analysisFiles" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <main id="scriptPage" class="page scriptAppPage">
    <div class="scriptWorkspace">
      <aside class="scriptControlPanel">
        <div class="sectionhead">
          <h2>产品节点</h2>
          <span class="filemeta">本地</span>
        </div>
        <div class="scriptStep productStep">
          <div class="scriptStepTitle"><span class="scriptStepNo">1</span>选择产品</div>
          <div class="contextCard">
            <h3>本 Agent 产品确认 <span id="scriptProductProjectBadge" class="filemeta">未选择</span></h3>
            <div class="pathrow is-hidden">
              <input id="script_product_project_root" readonly placeholder="请选择产品信息 Markdown 所在目录" />
              <input id="script_product_profile_path" type="hidden" />
              <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
              <button onclick="openLocalPath(script_product_profile_path.value)">打开产品信息</button>
            </div>
            <div id="scriptProductProjectHint" class="contextSummary">下拉框会读取 __PRODUCT_INFO_SOURCE_DIR__ 中的 Markdown 产品信息。</div>
            <div id="scriptProductProfileSummary" class="contextSummary is-hidden">加载产品信息中...</div>
          </div>
        </div>
        <div id="scriptReferenceManualWrap" class="is-hidden">
          <label>参考爆款脚本</label>
          <div class="pathrow">
            <input id="script_reference_analysis_path" placeholder="从当前产品爆款脚本中选择" />
            <button onclick="chooseScriptReferencePath()">手动选择</button>
            <button onclick="openLocalPath(script_reference_analysis_path.value)">打开文件</button>
          </div>
        </div>
        <div class="scriptStep variableStep">
          <div class="scriptStepTitle"><span class="scriptStepNo">2</span>变量配置</div>
          <label>国家/地区</label>
          <input id="script_country" placeholder="不改变原脚本" />
          <label>目标语言</label>
          <input id="script_target_language" placeholder="不改变原脚本" />
          <label>视频总时长</label>
          <input id="script_total_duration" placeholder="不改变原脚本" />
        </div>
        <div class="scriptSideNav">
          <button type="button" onclick="document.getElementById('scriptAnalysisFiles')?.scrollIntoView({block:'nearest'})">脚本库</button>
          <button type="button" class="active" onclick="document.getElementById('script_country')?.focus()">变量配置</button>
          <button type="button" onclick="document.querySelector('.compactLog')?.setAttribute('open', '')">系统日志</button>
        </div>
      </aside>
      <section class="scriptLibraryPanel">
        <div class="scriptLibraryToolbar">
          <div class="scriptSearchShell">
            <span>⌕</span>
            <input id="scriptLibrarySearch" placeholder="搜索脚本..." oninput="filterScriptLibrary(this.value)" />
          </div>
          <button type="button" title="筛选">筛选</button>
          <button type="button" title="排序">排序</button>
        </div>
        <div class="scriptLibraryHeader">
          <span>脚本标识（国家-用户-ID-标题）</span>
          <span id="scriptHotScriptCount" class="filemeta">0 个</span>
        </div>
        <div id="scriptHotScriptDir" class="dirpath">加载中...</div>
        <div class="scriptPickerShell">
          <div class="scriptPickerPane">
            <div id="scriptAnalysisFiles" class="scriptPickerList muted">加载中...</div>
          </div>
        </div>
      </section>
      <aside class="scriptResultPanel">
        <div class="scriptPreviewPanel">
          <div id="scriptSelectedVideoPreview" class="scriptVideoPreview">
            <div class="scriptVideoMissing">请选择脚本后显示对应 MP4 视频预览</div>
          </div>
          <div class="scriptDetailBlock">
            <div class="taskBoardHeader">
              <span>脚本详情</span>
              <span class="taskBoardMeta">视频预览</span>
            </div>
            <div id="scriptSelectedReferenceName" class="selectedScriptName">请从中间脚本库选择</div>
          </div>
        </div>
        <div class="scriptStep backendStep">
          <div class="scriptStepTitle"><span class="scriptStepNo">3</span>生成配置</div>
          <label>脚本生产方式</label>
          <select id="script_generation_backend">
            <option value="api">API 模型</option>
            <option value="obsidian_cli">Obsidian CLI</option>
          </select>
          <div id="scriptObsidianCliSettings" class="is-hidden">
            <label>Obsidian Vault 路径</label>
            <input id="script_obsidian_vault_path" placeholder="可选；也可用 OBSIDIAN_VAULT_PATH 环境变量" />
            <label>Obsidian CLI 命令</label>
            <input id="script_obsidian_cli_command" placeholder="例如：obsidian-cli run --prompt {prompt_file} --output {output_file}" />
          </div>
        </div>
        <div class="scriptStep generationStep">
          <div class="scriptStepTitle"><span class="scriptStepNo">4</span>复刻 / 裂变</div>
          <label>错题本</label>
          <input id="script_content_knowledge_base_path" readonly placeholder="__SCRIPT_MISTAKE_BOOK_SOURCE_ROOT__/<产品名>.md" />
          <div class="pathrow promptButtons">
            <button onclick="openLocalPath(script_generation_prompt_path.value)">复刻提示词</button>
            <button onclick="openLocalPath(script_generation_mutation_prompt_path.value)">裂变提示词</button>
          </div>
          <input id="script_mutation_mode" type="hidden" value="standard" />
          <input id="script_mutation_source" type="hidden" value="复刻稿" />
          <div class="mutationControlsRow">
            <label class="checkline mutationToggle"><input id="script_enable_mutation_rewrite" type="checkbox" /> 是否裂变</label>
            <div class="mutationCountRow">
              <label for="script_mutation_variants">裂变数量</label>
              <input id="script_mutation_variants" type="number" min="1" step="1" placeholder="默认 3" />
            </div>
          </div>
          <div class="pathrow is-hidden">
            <input id="script_generation_prompt_path" readonly placeholder="opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md" />
            <input id="script_generation_mutation_prompt_path" readonly placeholder="opc_engine/features/script_generation/config/script_generation_mutation_prompt.md" />
          </div>
          <textarea id="script_generation_prompt" class="scriptprompt is-hidden" hidden placeholder="这里会读取本地复刻提示词；只负责规定怎么根据已注入的拆解结果、产品信息和知识库复刻脚本。"></textarea>
          <label class="batchLabel">当前批次</label>
          <div id="scriptCurrentBatchCard" class="batchDraft">请选择产品和参考脚本</div>
          <div class="buttons">
            <button class="blue" onclick="startTask('script')">生成脚本</button>
            <button class="danger" onclick="stopTask()">停止任务</button>
          </div>
          <div class="inlineHint">产品、变量、所选脚本、复刻提示词和裂变提示词都会按当前页面状态注入生产流程。</div>
        </div>
      </aside>
      <section class="scriptBottomPanel">
        <div class="scriptBottomTabs">
          <button id="scriptBottomTaskTab" class="active" type="button" onclick="showScriptBottomTab('tasks')">活动任务</button>
          <button id="scriptBottomResultTab" type="button" onclick="showScriptBottomTab('results')">结果资源管理器</button>
          <button id="scriptBottomLogTab" type="button" onclick="showScriptBottomTab('logs')">系统日志</button>
        </div>
        <div id="scriptBottomTasks" class="scriptBottomContent active">
          <div id="scriptTaskProgress" class="taskProgress idle">
            <div class="taskProgressTop">
              <div class="taskProgressTitle">任务进程</div>
              <div id="scriptTaskStage" class="taskProgressStage">未运行</div>
            </div>
            <div class="progressTrack"><span id="scriptTaskProgressFill" class="progressFill"></span></div>
            <div id="scriptTaskDetail" class="taskProgressDetail">点击生成脚本后，这里会显示当前阶段。</div>
          </div>
          <div class="taskBoard">
            <div class="taskBoardHeader">
              <span>任务看板</span>
              <span id="scriptTaskBoardMeta" class="taskBoardMeta">暂无任务</span>
            </div>
            <div id="scriptTaskBoard" class="taskList">
              <div class="empty">暂无任务</div>
            </div>
          </div>
        </div>
        <div id="scriptBottomResults" class="scriptBottomContent">
          <div class="files">
            <div class="filebox">
              <h2>脚本产出结果 <span id="scriptOutputCount" class="filemeta">0 个</span></h2>
              <div id="scriptOutputDir" class="dirpath">加载中...</div>
              <div id="scriptFiles" class="muted">加载中...</div>
            </div>
          </div>
        </div>
        <div id="scriptBottomLogs" class="scriptBottomContent">
          <details class="compactLog" open>
            <summary>运行日志</summary>
            <pre id="scriptLogs"></pre>
          </details>
        </div>
      </section>
    </div>
  </main>
  <main id="adaptPage" class="page">
    <div class="pageintro">
      <div>
        <h2>脚本适配</h2>
        <p class="muted">调用文本模型把成品脚本适配成可交给 Veo 等视频生成模型使用的片段文案、镜头指令和首帧图片提示词，并同步提取文生图 JSON 与视频片段 CSV。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>脚本适配参数</h2>
        <span class="filemeta">本地保存</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="adaptProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow">
          <input id="adapt_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="adaptProductProjectHint" class="contextSummary">请选择产品信息 Markdown，适配结果会按该产品进入脚本适配输出目录。</div>
      </div>
      <label>成品脚本路径</label>
      <div class="pathrow">
        <input id="script_adaptation_input_path" placeholder="选择该产品的成品脚本 .md" />
        <button onclick="chooseGenericPath('script_adaptation_input_path','file','选择要适配的成品脚本')">选择脚本</button>
        <button onclick="openLocalPath(script_adaptation_input_path.value)">打开文件</button>
      </div>
      <div class="grid2">
        <div>
          <label>视频生成模型</label>
          <select id="script_adaptation_target_model">
            <option value="omni">Omni</option>
            <option value="sora">Sora</option>
            <option value="grok">Grok</option>
          </select>
        </div>
        <div>
          <label>单片段时长上限（秒）</label>
          <input id="script_adaptation_segment_seconds" type="number" min="1" placeholder="8" />
        </div>
      </div>
      <label>爆款内容知识库</label>
      <div class="pathrow">
        <input id="script_adaptation_knowledge_base_path" placeholder="knowledge_base/hot_content_knowledge_base.md" />
        <button onclick="openLocalPath(script_adaptation_knowledge_base_path.value)">打开文件</button>
      </div>
      <label>适配备注</label>
      <textarea id="script_adaptation_notes" class="tall" placeholder="例如：按当前模型能力拆分片段；首帧图突出 [product]；保持 TikTok 原生感。"></textarea>
      <label>适配规则与输出格式提示词</label>
      <div class="pathrow">
        <input id="script_adaptation_prompt_path" readonly placeholder="workflow_configs/script_adaptation/config/script_adaptation_prompt.md" />
        <button onclick="openLocalPath(script_adaptation_prompt_path.value)">打开文件</button>
      </div>
      <div class="inlineHint">上方成品脚本路径、视频生成模型、单片段时长、适配备注和爆款内容知识库会由系统自动注入；这里不需要再写“用户输入区”或脚本占位，只维护适配规则和输出格式。</div>
      <textarea id="script_adaptation_prompt" class="scriptprompt" placeholder="这里会读取本地脚本适配提示词；只负责规定怎么把已注入的成品脚本转换为视频生成模型可执行的分镜和首帧图描述。"></textarea>
      <div class="buttons">
        <button class="primary" onclick="saveContentWorkflowDefaults()">保存设置</button>
        <button class="blue" onclick="startTask('adapt')">适配脚本</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">脚本适配会调用 ModelMesh / Gemini 文本模型生成适配结果，但不会调用 Veo 或其他视频生成模型；每次完成后会保存完整 Markdown、文生图 JSON 和视频片段 CSV。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="adaptLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>脚本适配结果</h2>
          <p class="muted compact">包含完整 Markdown、文生图 JSON、视频片段 CSV。</p>
          <div id="adaptedScriptFiles" class="muted">加载中...</div>
        </div>
        <div class="filebox">
          <h2>可选成品脚本</h2>
          <div id="adaptSourceScriptFiles" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <main id="assemblePage" class="page">
    <div class="pageintro">
      <div>
        <h2>视频生成 <span class="filemeta">流程框架</span></h2>
        <p class="muted">当前只搭好流程框架，不会调用 Veo/可灵等模型生成片段，也不是完整自动剪辑链路；仅支持保存参数、扫描已有片段、生成清单，必要时尝试本地 ffmpeg 合并。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>视频生成参数</h2>
        <span class="filemeta">流程框架</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="assembleProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow">
          <input id="assemble_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="assembleProductProjectHint" class="contextSummary">请选择产品信息 Markdown，视频产出会按该产品进入视频片段输出目录。</div>
      </div>
      <label>视频片段目录</label>
      <div class="pathrow">
        <input id="clip_assembly_input_dir" placeholder="选择存放片段 mp4 的文件夹" />
        <button onclick="chooseGenericPath('clip_assembly_input_dir','folder','选择视频片段目录')">选择目录</button>
        <button onclick="openLocalPath(clip_assembly_input_dir.value)">打开目录</button>
      </div>
      <label>输出视频名称</label>
      <input id="clip_assembly_output_name" placeholder="例如：script_v1_test_video" />
      <label>生成备注</label>
      <textarea id="clip_assembly_notes" class="tall" placeholder="例如：按文件名顺序整理已有片段；后续接入片头、字幕、BGM、转场和真实生成链路。"></textarea>
      <div class="buttons">
        <button class="primary" onclick="saveContentWorkflowDefaults()">保存设置</button>
        <button class="blue" onclick="startTask('assemble')">生成流程清单</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">流程框架阶段：不会生成新视频片段；如果本机检测到 ffmpeg 且目录内已有视频片段，会尝试无转码合并，否则只生成视频生成清单和计划。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="assembleLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>视频生成流程输出</h2>
          <div id="assembledVideoFiles" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <main id="publishPage" class="page">
    <div class="pageintro">
      <div>
        <h2>视频发布 <span class="filemeta">流程框架</span></h2>
        <p class="muted">当前只搭好流程框架，不会自动登录或发布到 TikTok；仅支持管理待发布视频、账号、文案、标签，并生成本地发布计划。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>视频发布参数</h2>
        <span class="filemeta">流程框架</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="publishProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow">
          <input id="publish_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="publishProductProjectHint" class="contextSummary">请选择产品信息 Markdown，发布记录仅作为备份兼容流程使用。</div>
      </div>
      <label>待发布视频</label>
      <div class="pathrow">
        <input id="video_publish_input_path" placeholder="选择生成后的视频 .mp4" />
        <button onclick="chooseGenericPath('video_publish_input_path','file','选择待发布视频')">选择视频</button>
        <button onclick="openLocalPath(video_publish_input_path.value)">打开文件</button>
      </div>
      <div class="grid2">
        <div>
          <label>TikTok 账号</label>
          <input id="video_publish_account" placeholder="账号昵称或内部备注" />
        </div>
        <div>
          <label>发布模式</label>
          <select id="video_publish_mode">
            <option value="manual_record">手动发布记录</option>
            <option value="api_pending">自动发布待接入</option>
          </select>
        </div>
      </div>
      <label>发布文案</label>
      <textarea id="video_publish_caption" class="tall" placeholder="视频 caption / 标题 / 购物车引导。"></textarea>
      <label>标签</label>
      <input id="video_publish_tags" placeholder="#hairdye #beauty #tiktokshop" />
      <div class="buttons">
        <button class="primary" onclick="saveContentWorkflowDefaults()">保存设置</button>
        <button class="blue" onclick="startTask('publish')">生成发布计划</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">流程框架阶段：当前不会自动登录或发布到 TikTok，只会生成本地发布计划。等你确认账号管理方式后再接自动发布。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="publishLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>发布流程记录</h2>
          <div id="publishRecordFiles" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <main id="metricsPage" class="page">
    <div class="pageintro">
      <div>
        <h2>数据归因</h2>
        <p class="muted">分两步完成：先下载自然流和投放两类原始数据，再按作品维度合并整理，判断内容表现和投放表现的真实贡献。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>阶段一：下载原始数据</h2>
        <span class="filemeta">本地保存</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="metricsProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow">
          <input id="metrics_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="metricsProductProjectHint" class="contextSummary">请选择产品信息 Markdown，数据归因仍作为备份兼容流程使用。</div>
      </div>
      <input id="data_attribution_download_script_path" type="hidden" />
      <input id="data_attribution_ads_download_script_path" type="hidden" />
      <input id="data_attribution_download_output_dir" type="hidden" />
      <input id="natural_flow_management_url" type="hidden" />
      <input id="natural_flow_login_url" type="hidden" />
      <input id="natural_flow_export_button_text_re" type="hidden" />
      <textarea id="data_attribution_download_notes" hidden></textarea>
      <div class="downloadActions">
        <div class="downloadAction">
          <div class="downloadActionHead">
            <div>
              <h3>自然流数据</h3>
              <p>选择要归因的账号分组，然后下载该分组的自然流作品表现。</p>
            </div>
            <span class="metaPill">按分组导出</span>
          </div>
          <label>账号分组</label>
          <input id="natural_flow_account_group" placeholder="例如：赛弗美国" />
          <div class="buttons">
            <button class="blue" onclick="startTask('metrics-natural-download')">下载自然流数据</button>
          </div>
        </div>
        <div class="downloadAction">
          <div class="downloadActionHead">
            <div>
              <h3>投放数据</h3>
              <p>默认下载昨天的投放素材数据，用于和自然流作品 ID 做同作品归因。</p>
            </div>
            <span class="metaPill">昨天</span>
          </div>
          <div class="buttons">
            <button class="blue" onclick="startTask('metrics-ads-download')">下载投放数据</button>
          </div>
        </div>
        <div class="buttons">
          <button class="primary" onclick="saveContentWorkflowDefaults()">保存设置</button>
          <button class="danger" onclick="stopTask()">停止任务</button>
        </div>
        <div class="inlineHint">原始数据会保存到本地下载目录，阶段二会自动优先读取最新的自然流和投放数据文件。</div>
      </div>

      <hr />
      <div class="sectionhead">
        <h2>阶段二：整理与分析</h2>
        <span class="filemeta">本地分析</span>
      </div>
      <input id="data_recovery_natural_input_path" type="hidden" />
      <input id="data_recovery_ads_input_path" type="hidden" />
      <textarea id="data_recovery_manual_metrics" hidden></textarea>
      <div class="downloadAction">
        <div class="downloadActionHead">
          <div>
            <h3>归因汇总表</h3>
            <p>阶段二会自动读取本地最新原始数据，生成同作品维度的归因 CSV。</p>
          </div>
          <span class="metaPill">处理后结果</span>
        </div>
        <label>处理后表格路径</label>
        <div class="pathrow">
          <input id="data_attribution_output_table_path" readonly placeholder="整理分析后自动生成" />
          <button onclick="openLocalPath(getPathInputValue('data_attribution_output_table_path'))">打开归因表</button>
        </div>
      </div>
      <div class="buttons">
        <button class="primary" onclick="saveContentWorkflowDefaults()">保存设置</button>
        <button class="blue" onclick="startTask('metrics')">整理分析数据</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">阶段二前端只显示处理后的归因表。原始数据读取目录固定在本地项目配置中，README 里有路径说明。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="metricsLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>数据归因结果</h2>
          <div id="metricsFiles" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <main id="optimizePage" class="page">
    <div class="pageintro">
      <div>
        <h2>脚本优化</h2>
        <p class="muted">根据同一脚本产出的所有视频数据做加权评估，再反向优化脚本。</p>
      </div>
    </div>
    <div class="workspace">
    <section>
      <div class="sectionhead">
        <h2>脚本优化参数</h2>
        <span class="filemeta">本地保存</span>
      </div>
      <div class="contextCard">
        <h3>本 Agent 产品确认 <span id="optimizeProductProjectBadge" class="filemeta">未选择</span></h3>
        <div class="pathrow">
          <input id="optimize_product_project_root" readonly placeholder="请选择产品信息 Markdown" />
          <button onclick="openLocalPath('__PRODUCT_INFO_SOURCE_DIR__')">打开产品目录</button>
        </div>
        <div id="optimizeProductProjectHint" class="contextSummary">请选择产品信息 Markdown，脚本优化仍作为备份兼容流程使用。</div>
      </div>
      <label>原脚本路径</label>
      <div class="pathrow">
        <input id="script_optimization_input_path" placeholder="选择要优化的脚本 .md" />
        <button onclick="chooseGenericPath('script_optimization_input_path','file','选择要优化的脚本')">选择脚本</button>
        <button onclick="openLocalPath(script_optimization_input_path.value)">打开文件</button>
      </div>
      <label>数据归因结果</label>
      <div class="pathrow">
        <input id="script_optimization_metrics_path" placeholder="选择 metrics 中的数据归因结果" />
        <button onclick="chooseGenericPath('script_optimization_metrics_path','file','选择数据归因结果')">选择数据</button>
        <button onclick="openLocalPath(script_optimization_metrics_path.value)">打开文件</button>
      </div>
      <label>优化备注</label>
      <textarea id="script_optimization_notes" class="tall" placeholder="例如：更看重成交/GMV；完播低优先重写前3秒；评论低优化争议点。"></textarea>
      <div class="buttons">
        <button class="primary" onclick="saveContentWorkflowDefaults()">保存设置</button>
        <button class="blue" onclick="startTask('optimize')">优化脚本</button>
        <button class="danger" onclick="stopTask()">停止任务</button>
      </div>
      <p class="muted">当前先产出加权评估和优化建议框架；后续接入真实发布数据后，再自动生成新脚本版本。</p>
    </section>
    <section>
      <h2>运行日志</h2>
      <pre id="optimizeLogs"></pre>
      <div class="files">
        <div class="filebox">
          <h2>脚本优化结果</h2>
          <div id="optimizationFiles" class="muted">加载中...</div>
        </div>
      </div>
    </section>
    </div>
  </main>
  <script>
    const pageMap = {
      '/': 'home',
      '/product': 'product',
      '/collect': 'collect',
      '/analyze': 'analyze',
      '/script': 'script',
      '/adapt': 'adapt',
      '/assemble': 'assemble',
      '/publish': 'publish',
      '/metrics': 'metrics',
      '/optimize': 'optimize'
    };
    const currentPage = pageMap[location.pathname] || 'home';
    document.body.dataset.page = currentPage;
    ['home','collect','analyze','script','adapt','assemble'].forEach(page => {
      const nav = document.getElementById(`${page}Nav`);
      if (nav) nav.classList.toggle('active', currentPage === page);
    });
    const productFields = [
      'market',
      'collection_date',
      'product_name',
      'english_name',
      'category',
      'spec',
      'colors',
      'action_time',
      'regular_price',
      'promo_price',
      'top_selling_points',
      'audience_pain_matrix',
      'pain_conversion_talk_tracks',
      'tiktok_marketing_angles',
      'market_keywords',
      'material_type_suggestions',
      'notes'
    ];
    let currentConfig = {};
    let currentFiles = {};
    const productFieldLabels = {
      market: '市场 / 地区',
      collection_date: '收集日期',
      product_name: '产品名',
      english_name: '英文名',
      category: '类目',
      spec: '规格',
      colors: '色号',
      action_time: '作用时间',
      regular_price: '日常价',
      promo_price: '活动价',
      top_selling_points: 'TOP 3 核心卖点',
      audience_pain_matrix: '目标人群 x 痛点矩阵',
      pain_conversion_talk_tracks: '核心痛点与转化话术',
      tiktok_marketing_angles: 'TikTok 营销推广切入点',
      market_keywords: '市场关键词参考',
      material_type_suggestions: '适配素材类型建议',
      notes: '补充备注'
    };
    const workflowInputStageByPrefix = {
      product: 'product_info',
      collect: 'hot_collection',
      analyze: 'video_teardown',
      script: 'script_generation',
      adapt: 'script_adaptation',
      assemble: 'video_generation',
      publish: 'video_publish',
      metrics: 'data_attribution',
      optimize: 'script_optimization'
    };
    const sanitizedPathInputIds = new Set([
      'data_recovery_natural_input_path',
      'data_recovery_ads_input_path'
    ]);
    const countryOptionsData = ['全部','美国','印度尼西亚','英国','越南','泰国','马来西亚','菲律宾','西班牙','墨西哥','德国','法国','意大利','巴西','日本','新加坡'];
    let topCategoryOptions = ['全部','美妆个护'];
    let categoryTree = {
      '美妆个护': {
        '头部护理与造型': ['染发用品']
      }
    };
    const shopTypeOptionsData = ['全部','跨境店','本土店'];
    const productTypeOptionsData = ['全部','上新商品','包邮商品','本地仓商品','爆款商品'];
    const productStatusOptionsData = ['全部','在售','下架'];
    const filterOptionsData = {
      creator_conversion_rate_filter: ['全部','<25%','25%-50%','50%-75%','75%-100%'],
      total_sales_filter: ['全部','<1万','1万-10万','10万-20万','20万-30万','30万-40万','50万-100万','>100万'],
      total_gmv_filter: ['全部','<$500','$500-$1000','$1000-$5000','$5000-$1.00万','$1.00万-$5.00万','$5.00万-$10.00万','$10.00万-$50.00万','$50.00万-$100.00万','>$100.00万'],
      sales_7d_filter: ['全部','<500','500-1000','1000-5000','5000-1万','1万-5万','>5万'],
      gmv_7d_filter: ['全部','<$500','$500-$1000','$1000-$5000','$5000-$1.00万','$1.00万-$5.00万','$5.00万-$10.00万','$10.00万-$50.00万','$50.00万-$100.00万','>$100.00万'],
      creator_count_filter: ['全部','100-499','500-999','1000-5000','5000-1万','>1万'],
      commission_rate_filter: ['全部','<15%','15%-30%','30%-50%','50%-70%','>70%'],
      shipping_method_filter: ['全部','视频带货','直播带货']
    };
    let selectedCategoryPath = ['美妆个护','头部护理与造型','染发用品'];
    let selectedProductTypes = [];

    function fillSelect(selectId, options, selected='') {
      const el = document.getElementById(selectId);
      if (!el) return;
      const finalOptions = Array.isArray(options) ? options.slice() : [];
      if (selected && !finalOptions.includes(selected)) finalOptions.push(selected);
      el.innerHTML = '';
      finalOptions.forEach(option => el.add(new Option(option, option)));
      el.value = finalOptions.includes(selected) ? selected : (finalOptions[0] || '');
    }
    function syncCollectHiddenFields() {
      country.value = country_select.value || '全部';
      category_path.value = selectedCategoryPath.join(' > ');
      shop_type.value = shop_type_select.value || '全部';
      product_status.value = product_status_select.value || '在售';
      selectedProductTypes = product_type_select.value && product_type_select.value !== '全部' ? [product_type_select.value] : [];
      const selectedEl = document.getElementById('selectedCategoryCondition');
      if (selectedEl) selectedEl.textContent = `已选条件：商品分类：${category_path.value || '全部'}`;
    }
    function renderCategoryPicker(path) {
      selectedCategoryPath = Array.isArray(path) && path.length ? path.slice(0, 3) : ['全部'];
      const level1 = selectedCategoryPath[0] || '全部';
      const level2 = selectedCategoryPath[1] || '';
      const level3 = selectedCategoryPath[2] || '';
      fillSelect('category_level1_select', topCategoryOptions, level1);
      if (level1 === '全部') selectedCategoryPath = ['全部'];
      else {
        const secondLevelOptions = ['全部', ...Object.keys(categoryTree[level1] || {})];
        fillSelect('category_level2_select', secondLevelOptions, level2 || '全部');
        const activeLevel2 = secondLevelOptions.includes(level2) ? level2 : '全部';
        const thirdLevelOptions = activeLevel2 === '全部' ? ['全部'] : ['全部', ...(categoryTree[level1]?.[activeLevel2] || [])];
        fillSelect('category_level3_select', thirdLevelOptions, level3 || '全部');
        const activeLevel3 = thirdLevelOptions.includes(level3) ? level3 : '全部';
        selectedCategoryPath = [level1];
        if (activeLevel2 && activeLevel2 !== '全部') selectedCategoryPath.push(activeLevel2);
        if (activeLevel3 && activeLevel3 !== '全部') selectedCategoryPath.push(activeLevel3);
      }
      if (level1 === '全部') {
        fillSelect('category_level2_select', ['全部'], '全部');
        fillSelect('category_level3_select', ['全部'], '全部');
      }
      syncCollectHiddenFields();
    }
    function renderCollectSelectors(cfg) {
      country.value = cfg.country || '马来西亚';
      fillSelect('country_select', countryOptionsData, country.value);
      renderCategoryPicker(cfg.category_path || selectedCategoryPath);
      shop_type.value = cfg.shop_type || '全部';
      fillSelect('shop_type_select', shopTypeOptionsData, shop_type.value);
      selectedProductTypes = Array.isArray(cfg.product_types) ? cfg.product_types.slice() : [];
      fillSelect('product_type_select', productTypeOptionsData, selectedProductTypes[0] || '全部');
      product_status.value = cfg.product_status || '在售';
      fillSelect('product_status_select', productStatusOptionsData, product_status.value);
      Object.entries(filterOptionsData).forEach(([id, options]) => {
        const selected = options.includes(cfg[id]) ? cfg[id] : '全部';
        fillSelect(id, options, selected);
      });
      country_select.onchange = syncCollectHiddenFields;
      shop_type_select.onchange = syncCollectHiddenFields;
      product_status_select.onchange = syncCollectHiddenFields;
      product_type_select.onchange = syncCollectHiddenFields;
      category_level1_select.onchange = () => {
        const nextLevel1 = category_level1_select.value;
        if (nextLevel1 === '全部') renderCategoryPicker(['全部']);
        else renderCategoryPicker([nextLevel1]);
      };
      category_level2_select.onchange = () => {
        const first = category_level1_select.value;
        const second = category_level2_select.value;
        const nextPath = second && second !== '全部' ? [first, second] : [first];
        renderCategoryPicker(nextPath);
      };
      category_level3_select.onchange = () => {
        const first = category_level1_select.value;
        const second = category_level2_select.value;
        const third = category_level3_select.value;
        const nextPath = [first].filter(Boolean);
        if (second && second !== '全部') nextPath.push(second);
        if (third && third !== '全部') nextPath.push(third);
        renderCategoryPicker(nextPath);
      };
      syncCollectHiddenFields();
    }

    function renderProductProfileSummary(profile) {
      const target = document.getElementById('scriptProductProfileSummary');
      if (!target) return;
      const filled = productFields
        .map(field => ({field, value: String((profile || {})[field] || '').trim()}))
        .filter(item => item.value);
      if (!filled.length) {
        target.innerHTML = '<div>尚未保存产品信息。请先进入「产品信息」页填写产品名、卖点、目标人群和痛点。</div>';
        return;
      }
      const priority = ['product_name', 'english_name', 'top_selling_points', 'audience_pain_matrix'];
      const items = priority
        .map(field => filled.find(item => item.field === field))
        .filter(Boolean)
        .slice(0, 4);
      const fallbackItems = items.length ? items : filled.slice(0, 4);
      target.innerHTML = fallbackItems.map(item => {
        const value = escapeHtml(item.value).slice(0, 160);
        return `<div><strong>${productFieldLabels[item.field] || item.field}：</strong>${value}</div>`;
      }).join('');
    }

    async function api(path, options={}) {
      const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
      const data = await res.json();
      if (!res.ok) throw new Error(friendlyErrorMessage(data.error || '请求失败'));
      return data;
    }
    const agentServiceIds = ['collect','analyze','script','adapt','assemble','finished','rewrite','compose'];
    function renderAgentServiceStatus(service) {
      const el = document.getElementById(`agentStatus_${service.id}`);
      if (!el) return;
      el.classList.remove('is-running', 'is-starting', 'is-offline');
      if (service.running) {
        el.textContent = '运行中';
        el.classList.add('is-running');
      } else if (service.process_running) {
        el.textContent = '启动中';
        el.classList.add('is-starting');
      } else {
        el.textContent = '未运行';
        el.classList.add('is-offline');
      }
    }
    async function refreshAgentServices() {
      try {
        const payload = await api('/api/agent-services');
        (payload.services || []).forEach(renderAgentServiceStatus);
      } catch (error) {
        agentServiceIds.forEach(id => renderAgentServiceStatus({id, running:false, process_running:false}));
      }
    }
    async function startAgentService(id) {
      const buttons = Array.from(document.querySelectorAll(`button[onclick="startAgentService('${id}')"]`));
      buttons.forEach(button => {
        button.disabled = true;
        button.textContent = '启动中...';
      });
      renderAgentServiceStatus({id, running:false, process_running:true});
      try {
        const result = await api('/api/agent-services/start', {method:'POST', body:JSON.stringify({id})});
        renderAgentServiceStatus(result);
        showToast(result.message || '已发送启动命令');
        const startedAt = Date.now();
        const timer = setInterval(async () => {
          await refreshAgentServices();
          const statusEl = document.getElementById(`agentStatus_${id}`);
          if (statusEl && statusEl.classList.contains('is-running')) clearInterval(timer);
          if (Date.now() - startedAt > 30000) clearInterval(timer);
        }, 1500);
      } catch (error) {
        showToast(error.message || '启动失败', true);
        renderAgentServiceStatus({id, running:false, process_running:false});
      } finally {
        setTimeout(() => {
          buttons.forEach(button => {
            button.disabled = false;
            button.textContent = '启动/检测';
          });
        }, 1200);
      }
    }
    function friendlyErrorMessage(message) {
      const text = String(message || '操作失败');
      if (
        (text.includes("Command '['") && text.includes('osascript')) ||
        text.includes('choose file') ||
        text.includes('choose folder') ||
        text.includes('returned non-zero exit status')
      ) {
        return '文件选择没有完成，请重新选择';
      }
      if (/缺少 path/.test(text)) {
        return '请先选择文件或目录';
      }
      return text;
    }
    function updateScriptBackendControls() {
      const settings = document.getElementById('scriptObsidianCliSettings');
      if (!settings) return;
      settings.classList.toggle('is-hidden', script_generation_backend.value !== 'obsidian_cli');
    }
    async function loadFastmossCategoryTree() {
      try {
        const data = await api('/api/fastmoss-category-tree');
        topCategoryOptions = Array.isArray(data.top_categories) && data.top_categories.length ? data.top_categories : topCategoryOptions;
        categoryTree = data.category_tree && typeof data.category_tree === 'object' ? data.category_tree : categoryTree;
      } catch (error) {
        console.warn('FastMoss category tree load failed', error);
      }
    }
    async function loadConfig() {
      await loadFastmossCategoryTree();
      const cfg = await api('/api/config');
      currentConfig = cfg;
      phone.value = cfg.phone || '';
      password.value = cfg.password || '';
      keyword.value = cfg.keyword || '';
      renderCollectSelectors(cfg);
      product_limit.value = cfg.product_limit || 3;
      videos_per_product.value = cfg.videos_per_product || 20;
      show_browser.checked = !!cfg.show_browser;
      modelmesh_api_key.value = cfg.modelmesh_api_key || '';
      modelmesh_base_url.value = cfg.modelmesh_base_url || 'https://router.shengsuanyun.com/api';
      video_analysis_model.value = cfg.video_analysis_model || 'google/gemini-3-flash';
      video_analysis_prompt_path.value = cfg.video_analysis_prompt_path || 'workflow_configs/video_teardown/config/video_teardown_prompt.md';
      video_teardown_knowledge_base_path.value = cfg.video_teardown_knowledge_base_path || 'knowledge_base/hot_content_knowledge_base.md';
      analysis_input_path.value = cfg.analysis_input_path || '';
      video_analysis_prompt.value = cfg.video_analysis_prompt || '';
      script_generation_prompt_path.value = cfg.script_generation_prompt_path || 'opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md';
      script_generation_mutation_prompt_path.value = cfg.script_generation_mutation_prompt_path || 'opc_engine/features/script_generation/config/script_generation_mutation_prompt.md';
      script_generation_backend.value = cfg.script_generation_backend || 'api';
      script_obsidian_cli_command.value = cfg.script_obsidian_cli_command || '';
      script_obsidian_vault_path.value = cfg.script_obsidian_vault_path || '';
      updateScriptBackendControls();
      script_enable_mutation_rewrite.checked = !!cfg.script_enable_mutation_rewrite;
      setScriptMutationMode('standard', false);
      script_mutation_variants.value = cfg.script_mutation_variants || 3;
      script_mutation_source.value = '复刻稿';
      script_generation_prompt.value = cfg.script_generation_prompt || '';
      script_content_knowledge_base_path.value = cfg.script_content_knowledge_base_path || '';
      script_reference_analysis_path.value = cfg.script_reference_analysis_path || '';
      renderSelectedScriptName();
      script_country.value = cfg.script_country || '不改变原脚本';
      script_target_language.value = cfg.script_target_language || '不改变原脚本';
      script_total_duration.value = cfg.script_total_duration || '不改变原脚本';
      updateCurrentScriptBatchCard();
      script_adaptation_input_path.value = cfg.script_adaptation_input_path || '';
      script_adaptation_prompt_path.value = cfg.script_adaptation_prompt_path || 'workflow_configs/script_adaptation/config/script_adaptation_prompt.md';
      script_adaptation_target_model.value = cfg.script_adaptation_target_model || 'omni';
      script_adaptation_segment_seconds.value = cfg.script_adaptation_segment_seconds || 8;
      script_adaptation_knowledge_base_path.value = cfg.video_teardown_knowledge_base_path || 'knowledge_base/hot_content_knowledge_base.md';
      script_adaptation_notes.value = cfg.script_adaptation_notes || '';
      script_adaptation_prompt.value = cfg.script_adaptation_prompt || '';
      clip_assembly_input_dir.value = cfg.clip_assembly_input_dir || '';
      clip_assembly_output_name.value = cfg.clip_assembly_output_name || '';
      clip_assembly_notes.value = cfg.clip_assembly_notes || '';
      video_publish_input_path.value = cfg.video_publish_input_path || '';
      video_publish_account.value = cfg.video_publish_account || '';
      video_publish_caption.value = cfg.video_publish_caption || '';
      video_publish_tags.value = cfg.video_publish_tags || '';
      video_publish_mode.value = cfg.video_publish_mode || 'manual_record';
      data_attribution_download_script_path.value = cfg.data_attribution_download_script_path || 'opc_engine.features.data_attribution.download_natural_flow_data';
      data_attribution_ads_download_script_path.value = cfg.data_attribution_ads_download_script_path || 'opc_engine.features.data_attribution.download_ad_performance_data';
      data_attribution_download_output_dir.value = cfg.data_attribution_download_output_dir || '';
      data_attribution_download_notes.value = cfg.data_attribution_download_notes || '';
      natural_flow_management_url.value = cfg.natural_flow_management_url || '';
      natural_flow_login_url.value = cfg.natural_flow_login_url || '';
      natural_flow_account_group.value = cfg.natural_flow_account_group || '';
      natural_flow_export_button_text_re.value = cfg.natural_flow_export_button_text_re || '导出|下载|Export|Download';
      setPathInputDisplay('data_recovery_natural_input_path', '');
      setPathInputDisplay('data_recovery_ads_input_path', '');
      data_recovery_manual_metrics.value = cfg.data_recovery_manual_metrics || '';
      script_optimization_input_path.value = cfg.script_optimization_input_path || '';
      script_optimization_metrics_path.value = cfg.script_optimization_metrics_path || '';
      script_optimization_notes.value = cfg.script_optimization_notes || '';
      const productProfilePath = cfg.product_profile_path || '';
      if (document.getElementById('product_profile_path')) product_profile_path.value = productProfilePath;
      if (document.getElementById('script_product_profile_path')) script_product_profile_path.value = productProfilePath;
      renderProductProjectCard('product', cfg, '产品资料和后续结果会归档到');
      renderProductProjectCard('collect', cfg, '后续结果会归档到');
      renderProductProjectCard('analyze', cfg, '视频拆解结果会归档到');
      renderProductProjectCard('script', cfg, '脚本产出结果会归档到');
      renderProductProjectCard('adapt', cfg, '脚本适配结果会归档到');
      renderProductProjectCard('assemble', cfg, '视频生成流程输出会归档到');
      renderProductProjectCard('publish', cfg, '视频发布记录会归档到');
      renderProductProjectCard('metrics', cfg, '数据归因结果会归档到');
      renderProductProjectCard('optimize', cfg, '脚本优化结果会归档到');
      const profile = cfg.product_profile || {};
      productFields.forEach(field => {
        const el = document.getElementById('product_' + field);
        if (el) el.value = profile[field] || '';
      });
      renderProductProfileSummary(profile);
    }
    function renderProductProjectCard(prefix, cfg, readyLabel) {
      renderProductProjectSelector(prefix, cfg);
      renderWorkflowInputFile(prefix, cfg);
      const input = document.getElementById(`${prefix}_product_project_root`);
      const agentPaths = cfg.unified_agent_paths || {};
      const pathByPrefix = {
        product: cfg.product_profile_path || cfg.product_project_root || '',
        collect: agentPaths.collect_output_dir || '',
        analyze: agentPaths.analyze_output_dir || '',
        script: agentPaths.script_output_dir || '',
        adapt: agentPaths.adapt_output_dir || '',
        assemble: agentPaths.assemble_output_dir || '',
        publish: cfg.product_project_root || '',
        metrics: cfg.product_project_root || '',
        optimize: cfg.product_project_root || ''
      };
      if (input) input.value = pathByPrefix[prefix] || '';
      const badge = document.getElementById(`${prefix}ProductProjectBadge`);
      if (badge) badge.textContent = cfg.product_project_ready ? '已选择产品 MD' : '未选择';
      const hint = document.getElementById(`${prefix}ProductProjectHint`);
      if (!hint) return;
      const inputDir = {
        collect: agentPaths.collect_input_dir || '',
        analyze: agentPaths.analyze_input_dir || '',
        script: agentPaths.script_input_dir || '',
        adapt: agentPaths.adapt_input_dir || '',
        assemble: agentPaths.assemble_input_dir || ''
      }[prefix] || '';
      const outputDir = pathByPrefix[prefix] || '';
      hint.innerHTML = cfg.product_project_ready
        ? `产品：<strong>${escapeHtml(cfg.unified_product_name || cfg.product_project_slug || '')}</strong>${inputDir ? `<br>输入目录：${escapeHtml(inputDir)}` : ''}${outputDir ? `<br>输出目录：${escapeHtml(outputDir)}` : ''}`
        : '请先从产品信息 Markdown 中选择本 agent 要处理的产品。';
    }
    function renderProductProjectSelector(prefix, cfg) {
      const input = document.getElementById(`${prefix}_product_project_root`);
      if (!input) return;
      const card = input.closest('.contextCard');
      if (!card) return;
      let wrap = document.getElementById(`${prefix}_product_project_selector_wrap`);
      if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = `${prefix}_product_project_selector_wrap`;
        wrap.className = 'projectSelectWrap';
        const selectorLabel = '选择产品信息 Markdown';
        wrap.innerHTML = `<label for="${prefix}_product_project_select">${selectorLabel}</label><select id="${prefix}_product_project_select" class="projectSelect" onchange="selectProductProject(this.value)"></select>`;
        const h3 = card.querySelector('h3');
        if (h3 && h3.nextSibling) {
          card.insertBefore(wrap, h3.nextSibling);
        } else {
          card.prepend(wrap);
        }
      }
      const select = document.getElementById(`${prefix}_product_project_select`);
      if (!select) return;
      const projects = Array.isArray(cfg.product_projects) ? cfg.product_projects : [];
      const current = cfg.product_project_slug || '';
      const currentKnown = projects.some(item => item.slug === current);
      const emptyLabel = prefix === 'product' ? '请选择产品信息 Markdown' : '请选择产品信息 Markdown';
      const options = [`<option value="">${escapeHtml(emptyLabel)}</option>`];
      projects.forEach(item => {
        const label = item.name && item.name !== item.slug ? `${item.name} (${item.slug})` : item.slug;
        options.push(`<option value="${escapeHtml(item.slug)}">${escapeHtml(label)}</option>`);
      });
      if (current && !currentKnown) {
        options.push(`<option value="${escapeHtml(current)}">${escapeHtml(current)}</option>`);
      }
      select.innerHTML = options.join('');
      select.value = current;
    }
    function renderWorkflowInputFile(prefix, cfg) {
      const input = document.getElementById(`${prefix}_product_project_root`);
      if (!input) return;
      const card = input.closest('.contextCard');
      if (!card) return;
      const stage = workflowInputStageByPrefix[prefix];
      const path = ((cfg.workflow_input_paths || {}).unified_console) || ((cfg.workflow_input_paths || {})[stage]) || '';
      let wrap = document.getElementById(`${prefix}_workflow_inputs_wrap`);
      if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = `${prefix}_workflow_inputs_wrap`;
        wrap.className = 'projectSelectWrap';
        wrap.innerHTML = `<label for="${prefix}_workflow_inputs_path">统一控制台配置文件</label><div class="pathrow"><input id="${prefix}_workflow_inputs_path" readonly /><button onclick="openLocalPath(getPathInputValue('${prefix}_workflow_inputs_path'))">打开文件</button></div>`;
        const selector = document.getElementById(`${prefix}_product_project_selector_wrap`);
        if (selector && selector.nextSibling) {
          card.insertBefore(wrap, selector.nextSibling);
        } else {
          card.appendChild(wrap);
        }
      }
      const pathInput = document.getElementById(`${prefix}_workflow_inputs_path`);
      if (pathInput) setPathInputDisplay(`${prefix}_workflow_inputs_path`, path);
    }
    async function selectProductProject(slug) {
      try {
        const cfg = await api('/api/product-project/select', {method:'POST', body:JSON.stringify({slug})});
        currentConfig = cfg;
        await loadConfig();
        await refresh();
        showToast(slug ? '已切换产品信息 Markdown' : '已清空当前产品选择');
      } catch (error) {
        showToast(error.message || '产品信息切换失败', true);
        await loadConfig();
      }
    }
    function requireProductProjectReady(actionText='继续操作') {
      if (currentConfig && currentConfig.product_project_ready) return true;
      showToast(`请先选择产品信息 Markdown，再${actionText}`, true);
      return false;
    }
    async function saveConfig(silent=false) {
      syncCollectHiddenFields();
      const payload = {
        phone: phone.value.trim(),
        password: password.value,
        keyword: keyword.value.trim(),
        country: country.value.trim(),
        category_path: category_path.value.split('>').map(x => x.trim()).filter(Boolean),
        shop_type: shop_type.value.trim() || '全部',
        product_types: selectedProductTypes,
        product_status: product_status.value.trim() || '在售',
        creator_conversion_rate_filter: creator_conversion_rate_filter.value,
        total_sales_filter: total_sales_filter.value,
        total_gmv_filter: total_gmv_filter.value,
        sales_7d_filter: sales_7d_filter.value,
        gmv_7d_filter: gmv_7d_filter.value,
        creator_count_filter: creator_count_filter.value,
        commission_rate_filter: commission_rate_filter.value,
        shipping_method_filter: shipping_method_filter.value,
        product_limit: Number(product_limit.value || 3),
        videos_per_product: Number(videos_per_product.value || 20),
        show_browser: show_browser.checked
      };
      await api('/api/config', {method:'POST', body:JSON.stringify(payload)});
      await refresh();
      if (!silent) alert('爆款采集设置已保存到本地');
    }
    async function saveTeardownDefaults(silent=false) {
      const payload = {
        modelmesh_api_key: modelmesh_api_key.value.trim(),
        modelmesh_base_url: modelmesh_base_url.value.trim(),
        video_analysis_model: video_analysis_model.value,
        video_analysis_prompt_path: video_analysis_prompt_path.value.trim(),
        video_teardown_knowledge_base_path: video_teardown_knowledge_base_path.value.trim(),
        analysis_input_path: analysis_input_path.value.trim(),
        video_analysis_prompt: video_analysis_prompt.value
      };
      await api('/api/teardown-defaults', {method:'POST', body:JSON.stringify(payload)});
      await refresh();
      if (!silent) alert('视频拆解设置已保存到本地');
    }
    async function saveScriptDefaults(silent=false) {
      const payload = {
        script_generation_prompt_path: script_generation_prompt_path.value.trim(),
        script_generation_backend: script_generation_backend.value,
        script_obsidian_cli_command: script_obsidian_cli_command.value.trim(),
        script_obsidian_vault_path: script_obsidian_vault_path.value.trim(),
        script_enable_mutation_rewrite: script_enable_mutation_rewrite.checked,
        script_mutation_mode: 'standard',
        script_mutation_variants: Number(script_mutation_variants.value || 3),
        script_mutation_source: '复刻稿',
        script_generation_prompt: script_generation_prompt.value,
        script_content_knowledge_base_path: script_content_knowledge_base_path.value.trim(),
        script_reference_analysis_path: script_reference_analysis_path.value.trim(),
        script_country: script_country.value.trim(),
        script_target_language: script_target_language.value.trim(),
        script_total_duration: script_total_duration.value.trim()
      };
      await api('/api/script-defaults', {method:'POST', body:JSON.stringify(payload)});
      await refresh();
      if (!silent) alert('脚本产出设置已保存到本地');
    }
    async function saveContentWorkflowDefaults(silent=false) {
      const payload = {
        script_adaptation_input_path: script_adaptation_input_path.value.trim(),
        script_adaptation_prompt_path: script_adaptation_prompt_path.value.trim(),
        script_adaptation_target_model: script_adaptation_target_model.value,
        script_adaptation_segment_seconds: Number(script_adaptation_segment_seconds.value || 8),
        video_teardown_knowledge_base_path: script_adaptation_knowledge_base_path.value.trim(),
        script_adaptation_notes: script_adaptation_notes.value,
        script_adaptation_prompt: script_adaptation_prompt.value,
        clip_assembly_input_dir: clip_assembly_input_dir.value.trim(),
        clip_assembly_output_name: clip_assembly_output_name.value.trim(),
        clip_assembly_notes: clip_assembly_notes.value,
        video_publish_input_path: video_publish_input_path.value.trim(),
        video_publish_account: video_publish_account.value.trim(),
        video_publish_caption: video_publish_caption.value,
        video_publish_tags: video_publish_tags.value.trim(),
        video_publish_mode: video_publish_mode.value,
        data_attribution_download_script_path: data_attribution_download_script_path.value.trim(),
        data_attribution_ads_download_script_path: data_attribution_ads_download_script_path.value.trim(),
        data_attribution_download_output_dir: data_attribution_download_output_dir.value.trim(),
        data_attribution_download_notes: data_attribution_download_notes.value,
        natural_flow_management_url: natural_flow_management_url.value.trim(),
        natural_flow_login_url: natural_flow_login_url.value.trim(),
        natural_flow_account_group: natural_flow_account_group.value.trim(),
        natural_flow_export_button_text_re: natural_flow_export_button_text_re.value.trim(),
        data_recovery_input_path: '',
        data_recovery_natural_input_path: '',
        data_recovery_ads_input_path: '',
        data_recovery_manual_metrics: data_recovery_manual_metrics.value,
        script_optimization_input_path: script_optimization_input_path.value.trim(),
        script_optimization_metrics_path: script_optimization_metrics_path.value.trim(),
        script_optimization_notes: script_optimization_notes.value
      };
      await api('/api/content-workflow-defaults', {method:'POST', body:JSON.stringify(payload)});
      await refresh();
      if (!silent) alert('内容分发工作流设置已保存到本地');
    }
    async function saveProductProfile(silent=false) {
      try {
        const product_profile = {};
        productFields.forEach(field => {
          const el = document.getElementById('product_' + field);
          product_profile[field] = el ? el.value.trim() : '';
        });
        const profilePathValue = document.getElementById('product_profile_path')?.value || '';
        await api('/api/product-profile', {method:'POST', body:JSON.stringify({product_profile, product_profile_path: profilePathValue})});
        await loadConfig();
        renderProductProfileSummary(product_profile);
        if (!silent) showToast('产品 MD 已保存到统一控制台');
      } catch (error) {
        showToast(error.message || '产品信息保存失败', true);
      }
    }
    async function startTask(task) {
      try {
        if (!requireProductProjectReady('启动任务')) return;
        if (task === 'analyze') {
          if (!analysis_input_path.value.trim()) {
            showToast('请先选择要拆解的 MP4 视频或包含 MP4 的目录', true);
            return;
          }
          await saveTeardownDefaults(true);
        } else if (task === 'script') {
          if (!script_reference_analysis_path.value.trim()) {
            showToast('请先选择当前产品的参考爆款脚本 Markdown', true);
            return;
          }
          if (!canRunScriptGeneration()) return;
          await saveScriptDefaults(true);
        } else if (task === 'adapt') {
          if (!script_adaptation_input_path.value.trim()) {
            showToast('请先选择要适配的成品脚本 Markdown', true);
            return;
          }
          await saveContentWorkflowDefaults(true);
        } else if (task === 'metrics-natural-download') {
          if (!natural_flow_account_group.value.trim()) {
            showToast('请先填写要导出的账号分组', true);
            return;
          }
          await saveContentWorkflowDefaults(true);
        } else if (task === 'metrics-ads-download') {
          await saveContentWorkflowDefaults(true);
        } else if (['assemble', 'publish', 'metrics-download', 'metrics', 'optimize'].includes(task)) {
          await saveContentWorkflowDefaults(true);
        } else {
          await saveConfig(true);
        }
        await api('/api/run/' + task, {method:'POST', body:'{}'});
        await refresh();
      } catch (error) {
        showToast(error.message || '任务启动失败', true);
      }
    }
    async function stopTask() {
      await api('/api/stop', {method:'POST', body:'{}'});
      await refresh();
    }
    async function chooseAnalysisPath(kind) {
      try {
        const res = await api('/api/choose-analysis-path', {method:'POST', body:JSON.stringify({kind})});
        if (!res.path) {
          showToast('已取消选择');
          return;
        }
        analysis_input_path.value = res.path;
        await saveTeardownDefaults(true);
      } catch (error) {
        showToast(error.message || '选择路径失败', true);
      }
    }
    async function chooseScriptReferencePath() {
      try {
        const res = await api('/api/choose-script-reference-path', {method:'POST', body:'{}'});
        if (!res.path) {
          showToast('已取消选择');
          return;
        }
        script_reference_analysis_path.value = res.path;
        await saveScriptDefaults(true);
      } catch (error) {
        showToast(error.message || '选择拆解结果失败', true);
      }
    }
    async function chooseGenericPath(targetId, kind, prompt) {
      try {
        const res = await api('/api/choose-path', {method:'POST', body:JSON.stringify({kind, prompt})});
        if (!res.path) {
          showToast('已取消选择');
          return;
        }
        const el = document.getElementById(targetId);
        if (el) setPathInputDisplay(targetId, res.path);
        await saveContentWorkflowDefaults(true);
      } catch (error) {
        showToast(error.message || '选择路径失败', true);
      }
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    function showToast(message, isError=false) {
      toast.textContent = message;
      toast.className = 'toast show' + (isError ? ' error' : '');
      clearTimeout(window.toastTimer);
      window.toastTimer = setTimeout(() => { toast.className = 'toast'; }, 2400);
    }
    async function openLocalPath(path) {
      try {
        if (!String(path || '').trim()) {
          showToast('请先选择文件或目录', true);
          return;
        }
        const result = await api('/api/open-path', {method:'POST', body:JSON.stringify({path})});
        if (result.opened === false) {
          showToast('Docker 已确认路径：' + sanitizePublicName(result.path || result.name));
        } else {
          showToast('已打开：' + sanitizePublicName(result.name));
        }
      } catch (error) {
        showToast(error.message || '打开失败', true);
      }
    }
    function sanitizePublicName(value) {
      return String(value || '')
        .replace(/download_natural_flow_data/ig, '自然流数据下载')
        .replace(/login_natural_flow_assisted/ig, '自然流辅助登录')
        .replace(/TikTok Ads GMV Max/ig, '投放数据')
        .replace(/TikTok Ads/ig, '投放数据')
        .replace(/GMVMax/ig, '投放数据')
        .replace(/GMV Max/ig, '投放数据');
    }
    function setPathInputDisplay(id, rawValue) {
      const el = document.getElementById(id);
      if (!el) return;
      const value = String(rawValue || '');
      if (sanitizedPathInputIds.has(id)) {
        el.dataset.realPath = value;
        el.value = sanitizePublicName(value);
      } else {
        el.value = value;
      }
    }
    function getPathInputValue(id) {
      const el = document.getElementById(id);
      if (!el) return '';
      return sanitizedPathInputIds.has(id) ? (el.dataset.realPath || el.value || '') : (el.value || '');
    }
    function openButton(file) {
      const name = escapeHtml(sanitizePublicName(file.name));
      const encodedPath = encodeURIComponent(file.path);
      return `<button class="filelink filebutton" type="button" data-path="${encodedPath}" onclick="openLocalPath(decodeURIComponent(this.dataset.path))" title="${escapeHtml(sanitizePublicName(file.path))}">${name}</button>`;
    }
    function chooseReferenceButton(file) {
      const encodedPath = encodeURIComponent(file.path);
      return `<button type="button" data-path="${encodedPath}" onclick="selectScriptReferencePath(decodeURIComponent(this.dataset.path))">选择</button>`;
    }
    function renderScriptReferencePicker(hotScripts) {
      const selectedPath = script_reference_analysis_path.value.trim();
      return hotScripts.length
        ? hotScripts.map(f => `<div class="fileitem ${f.path === selectedPath ? 'is-selected' : ''}" data-script-name="${escapeHtml((f.name || '').toLowerCase())}">${chooseReferenceButton(f)}<div>${cloneStatusBadge(f)}${mutationCountBadge(f)}${videoMatchBadge(f)}</div>${openButton(f)}</div>`).join('')
        : '<div class="empty">当前产品暂无可用爆款脚本。请先把拆解后的 .md 脚本放入当前产品对应的爆款脚本目录。</div>';
    }
    function filterScriptLibrary(query) {
      const keyword = String(query || '').trim().toLowerCase();
      document.querySelectorAll('#scriptAnalysisFiles .fileitem').forEach(item => {
        const text = item.dataset.scriptName || item.textContent.toLowerCase();
        item.style.display = !keyword || text.includes(keyword) ? '' : 'none';
      });
    }
    function showScriptBottomTab(tab) {
      const tabs = {
        tasks: ['scriptBottomTaskTab', 'scriptBottomTasks'],
        results: ['scriptBottomResultTab', 'scriptBottomResults'],
        logs: ['scriptBottomLogTab', 'scriptBottomLogs'],
      };
      Object.entries(tabs).forEach(([key, pair]) => {
        const tabEl = document.getElementById(pair[0]);
        const panelEl = document.getElementById(pair[1]);
        if (tabEl) tabEl.classList.toggle('active', key === tab);
        if (panelEl) panelEl.classList.toggle('active', key === tab);
      });
    }
    function cloneStatusBadge(file) {
      const done = file.clone_status === '已复刻';
      const title = done && file.clone_path ? ` title="${escapeHtml(file.clone_path)}"` : '';
      return `<span class="filemeta cloneStatus ${done ? 'done' : 'pending'}"${title}>${done ? '已复刻' : '未复刻'}</span>`;
    }
    function mutationCountBadge(file) {
      const count = Number(file.mutation_count || 0);
      return count ? `<span class="filemeta cloneStatus">已裂变 ${count} 条</span>` : '';
    }
    function videoMatchBadge(file) {
      const ok = !!(file && file.source_video_path);
      return `<span class="filemeta cloneStatus ${ok ? 'done' : 'pending'}">${ok ? '有视频' : '无视频'}</span>`;
    }
    function clonePathLine(file) {
      const path = file.clone_path || file.expected_clone_path || '';
      const label = file.clone_status === '已复刻' ? '复刻母稿' : '预计复刻稿';
      return path ? `<div class="scriptSourceHint">${escapeHtml(label)}：${escapeHtml(path)}</div>` : '';
    }
    function fileStem(name) {
      return String(name || '').replace(/\.md$/i, '');
    }
    function scriptBatchStem(name) {
      return fileStem(name).replace(/_\d{3}$/i, '');
    }
    function formatFileTime(value) {
      if (!value) return '';
      try {
        return new Date(value * 1000).toLocaleString('zh-CN', {hour12:false});
      } catch (error) {
        return '';
      }
    }
    function renderScriptOutputBatches(files) {
      const sourceGroups = new Map();
      (files || []).forEach(file => {
        const key = file.source_key || scriptBatchStem(file.name);
        if (!sourceGroups.has(key)) sourceGroups.set(key, []);
        sourceGroups.get(key).push(file);
      });
      const sortedSources = Array.from(sourceGroups.entries()).sort((a, b) => {
        const aTime = Math.max(...a[1].map(file => file.mtime || 0));
        const bTime = Math.max(...b[1].map(file => file.mtime || 0));
        return bTime - aTime;
      });
      if (!sortedSources.length) return '<div class="empty">暂无脚本产出结果</div>';

      function sourceTitle(key, sourceFiles) {
        const sample = sourceFiles.find(file => file.source_script_name || file.source_video_name) || sourceFiles[0] || {};
        return sample.source_script_name || sample.source_video_name || key;
      }
      function sourcePathLine(sourceFiles) {
        const sample = sourceFiles.find(file => file.source_video_path || file.source_script_path) || sourceFiles[0] || {};
        if (sample.source_video_path) return `源视频：${sample.source_video_path}`;
        if (sample.source_script_path) return `源脚本：${sample.source_script_path}`;
        if (sample.source_reference_path) return `源脚本：${sample.source_reference_path}`;
        return '源文件：暂未匹配到当前产品的 03 爆款视频或 04 爆款脚本';
      }
      function sourceCloneLine(sourceFiles) {
        const sample = sourceFiles.find(file => file.mutation_source_path || file.clone_source_path || file.expected_clone_path) || sourceFiles[0] || {};
        const path = sample.mutation_source_path || sample.clone_source_path || sample.expected_clone_path || '';
        const label = sample.mutation_source_path ? `裂变母稿${sample.mutation_source_stage ? `（${sample.mutation_source_stage}）` : ''}` : '复刻稿';
        return path ? `<div class="sourceMeta">${label}：${escapeHtml(path)}</div>` : '';
      }
      function runGroupsForSource(sourceFiles) {
        const sorted = sourceFiles.slice().sort((a, b) => (a.mtime || 0) - (b.mtime || 0) || String(a.name).localeCompare(String(b.name), 'zh-CN'));
        const runs = [];
        sorted.forEach(file => {
          const stage = file.output_stage || (file.name.startsWith('裂变-') ? '裂变' : (file.name.startsWith('复刻-') ? '复刻' : '脚本'));
          const variantIndex = Number(file.saved_variant_index || 0);
          const fallbackKey = scriptBatchStem(file.name);
          const runKey = file.mutation_run_id || (stage === '裂变' && variantIndex ? `${fallbackKey}-${file.raw_path || file.path}-${variantIndex === 1 ? file.mtime : ''}` : fallbackKey);
          let current = runs[runs.length - 1];
          const startsNewMutation = stage === '裂变' && variantIndex === 1;
          const noVariantNewStem = !variantIndex && current && current.fallbackKey !== fallbackKey;
          const newRunId = current && file.mutation_run_id && current.runKey !== file.mutation_run_id;
          if (!current || current.stage !== stage || startsNewMutation || noVariantNewStem || newRunId) {
            current = {stage, files: [], fallbackKey, runKey: file.mutation_run_id || runKey, startedAt: file.mtime || 0};
            runs.push(current);
          }
          current.files.push(file);
          current.latest = Math.max(current.latest || 0, file.mtime || 0);
        });
        return runs.sort((a, b) => (b.latest || 0) - (a.latest || 0));
      }
      function renderRun(run, runIndex, sourceIndex) {
        const ordered = run.files.slice().sort((a, b) => {
          const ai = Number(a.saved_variant_index || 0);
          const bi = Number(b.saved_variant_index || 0);
          if (ai || bi) return ai - bi;
          return String(a.name).localeCompare(String(b.name), 'zh-CN');
        });
        const requested = Math.max(...ordered.map(file => Number(file.saved_variant_count || file.requested_variant_count || 0)));
        const stageText = run.stage === '裂变' ? `第 ${runIndex + 1} 次裂变` : (run.stage === '复刻' ? `第 ${runIndex + 1} 次复刻` : `第 ${runIndex + 1} 次产出`);
        const countText = requested ? `${ordered.length}/${requested} 个 md` : `${ordered.length} 个 md`;
        const language = ordered.find(file => file.target_language)?.target_language || '';
        return `<details class="batchGroup" ${sourceIndex === 0 && runIndex === 0 ? 'open' : ''}>
          <summary>
            <div>
              <span class="batchTitle">${escapeHtml(stageText)}</span>
              <div class="batchMeta">${language ? `<span>${escapeHtml(language)}</span>` : ''}<span>${escapeHtml(countText)}</span><span>${escapeHtml(formatFileTime(run.latest))}</span></div>
            </div>
            <span class="filemeta">${ordered.length} 个</span>
          </summary>
          <div class="batchFiles">${ordered.map(file => `<div class="fileitem">${openButton(file)}</div>`).join('')}</div>
        </details>`;
      }
      return sortedSources.map(([key, sourceFiles], sourceIndex) => {
        const runs = runGroupsForSource(sourceFiles);
        const latest = Math.max(...sourceFiles.map(file => file.mtime || 0));
        const runCount = runs.length;
        const mdCount = sourceFiles.length;
        return `<details class="sourceGroup" ${sourceIndex === 0 ? 'open' : ''}>
          <summary>
            <div>
              <span class="batchTitle">${escapeHtml(sourceTitle(key, sourceFiles))}</span>
              <div class="sourceMeta">${escapeHtml(sourcePathLine(sourceFiles))}</div>
              ${sourceCloneLine(sourceFiles)}
              <div class="batchMeta"><span>${runCount} 次操作</span><span>${mdCount} 个 md</span><span>${escapeHtml(formatFileTime(latest))}</span></div>
            </div>
            <span class="filemeta">${mdCount} 个</span>
          </summary>
          <div class="sourceRuns">${runs.map((run, runIndex) => renderRun(run, runIndex, sourceIndex)).join('')}</div>
        </details>`;
      }).join('');
    }
    function selectedProductName() {
      const raw = script_product_profile_path.value || '';
      const name = raw.split('/').pop() || '';
      return name.replace(/-产品信息\.md$/i, '').replace(/\.md$/i, '') || '未选择产品';
    }
    function variableValue(id) {
      const el = document.getElementById(id);
      const value = String((el && el.value) || '').trim();
      return value || '不改变原脚本';
    }
    const scriptMutationPromptPaths = {
      standard: 'opc_engine/features/script_generation/config/script_generation_mutation_prompt.md'
    };
    function normalizeScriptMutationMode(mode) {
      return 'standard';
    }
    function setScriptMutationMode(mode, shouldUpdate=true) {
      const normalized = normalizeScriptMutationMode(mode);
      if (document.getElementById('script_mutation_mode')) script_mutation_mode.value = normalized;
      if (document.getElementById('script_generation_mutation_prompt_path')) {
        script_generation_mutation_prompt_path.value = scriptMutationPromptPaths[normalized];
      }
      if (shouldUpdate) updateCurrentScriptBatchCard();
    }
    function updateCurrentScriptBatchCard() {
      const el = document.getElementById('scriptCurrentBatchCard');
      if (!el) return;
      const selectedPath = script_reference_analysis_path.value.trim();
      const selectedName = selectedPath ? selectedPath.split('/').pop() : '未选择脚本';
      const selected = currentReferenceCloneStatus();
      const clonePath = selected ? (selected.clone_path || selected.expected_clone_path || '') : '';
      const cloneState = selected ? selected.clone_status : '未选择';
      const mode = script_enable_mutation_rewrite.checked ? `裂变 ${variableValue('script_mutation_variants')} 个` : '仅复刻';
      const backend = script_generation_backend.value === 'obsidian_cli' ? 'Obsidian CLI' : 'API 模型';
      const sourceLine = script_enable_mutation_rewrite.checked
        ? `<div><strong>裂变母稿：</strong>${escapeHtml(cloneState === '已复刻' ? '复刻后脚本' : '缺少复刻稿')} ${clonePath ? `<span>${escapeHtml(clonePath)}</span>` : ''}</div>`
        : `<div><strong>复刻输出：</strong>${escapeHtml(clonePath || '选择脚本后自动匹配')}</div>`;
      el.innerHTML = `
        <div><strong>产品：</strong>${escapeHtml(selectedProductName())}</div>
        <div><strong>变量：</strong>${escapeHtml(variableValue('script_country'))} / ${escapeHtml(variableValue('script_target_language'))} / ${escapeHtml(variableValue('script_total_duration'))}</div>
        <div><strong>脚本：</strong>${escapeHtml(selectedName)}</div>
        ${sourceLine}
        <div><strong>方式：</strong>${escapeHtml(backend)}，${escapeHtml(mode)}</div>
      `;
    }
    function formatTaskTime(timestamp) {
      if (!timestamp) return '-';
      const date = new Date(Number(timestamp) * 1000);
      if (Number.isNaN(date.getTime())) return '-';
      return date.toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false});
    }
    function taskStatusLabel(job) {
      if (job.queued) return '排队中';
      if (job.running) return '运行中';
      const summary = job.summary || {};
      const meta = job.metadata || {};
      const total = Number(summary.total || meta.mutation_variants || 0);
      const completed = Number(summary.completed || 0);
      if (job.exit_code === 0 && total && completed && completed < total) return '部分完成';
      if (job.exit_code === 0) return '已完成';
      if (job.exit_code === null || job.exit_code === undefined) return '未运行';
      return `异常 ${job.exit_code}`;
    }
    function taskProgressText(job) {
      const summary = job.summary || {};
      const meta = job.metadata || {};
      const total = Number(summary.total || meta.mutation_variants || 0);
      if (total) return `${Number(summary.completed || 0)}/${total}`;
      return job.running ? '进行中' : '-';
    }
    function taskProgressPercent(job) {
      const summary = job.summary || {};
      const meta = job.metadata || {};
      const total = Number(summary.total || meta.mutation_variants || 0);
      if (!total) return job.running ? 18 : (job.exit_code === 0 ? 100 : 0);
      return Math.max(0, Math.min(100, Math.round((Number(summary.completed || 0) / total) * 100)));
    }
    function renderScriptTaskBoard(status) {
      const board = document.getElementById('scriptTaskBoard');
      const meta = document.getElementById('scriptTaskBoardMeta');
      if (!board) return;
      const jobs = (status.jobs || []).slice(-8).reverse();
      const activeCount = Number(status.active_count || 0);
      const queueCount = Number(status.queue_count || 0);
      const apiMax = status.max_api_concurrent || '-';
      if (meta) meta.textContent = activeCount || queueCount
        ? `${activeCount} 组运行 / ${queueCount} 组排队 / API并发 ${apiMax}`
        : `最近 ${jobs.length} 个任务 / API并发 ${apiMax}`;
      if (!jobs.length) {
        board.innerHTML = '<div class="empty">暂无任务</div>';
        return;
      }
      board.innerHTML = jobs.map(job => {
        const summary = job.summary || {};
        const meta = job.metadata || {};
        const statusClass = job.queued ? 'queued' : (job.running ? 'running' : (job.exit_code === 0 ? 'done' : 'failed'));
        const percent = taskProgressPercent(job);
        const batchText = summary.current_batch ? `${summary.completed_batches || 0}/${summary.current_batch}` : '-';
        const outputText = summary.output_count ? `${summary.output_count} 个` : (job.running ? '待写入' : '0 个');
        const countText = meta.mutation_enabled ? `${meta.mutation_variants || summary.total || '-'} 条裂变` : '复刻';
        const sourcePath = summary.source_path || meta.reference_path || '';
        const lastLog = summary.last_log || (job.logs || []).slice(-1)[0] || '-';
        return `
          <div class="taskCard ${statusClass}">
            <div class="taskCardTop">
              <div class="taskName">${escapeHtml(job.task || '任务')} #${escapeHtml(job.id)}</div>
              <span class="taskBadge">${escapeHtml(taskStatusLabel(job))}</span>
            </div>
            <div class="progressTrack"><span class="progressFill" style="width:${percent}%"></span></div>
            <div class="taskStats">
              <div class="taskStat"><div class="taskStatLabel">进度</div><div class="taskStatValue">${escapeHtml(taskProgressText(job))}</div></div>
              <div class="taskStat"><div class="taskStatLabel">批次</div><div class="taskStatValue">${escapeHtml(batchText)}</div></div>
              <div class="taskStat"><div class="taskStatLabel">输出</div><div class="taskStatValue">${escapeHtml(outputText)}</div></div>
              <div class="taskStat"><div class="taskStatLabel">警告</div><div class="taskStatValue">${escapeHtml(summary.warning_count || 0)}</div></div>
            </div>
            <div class="taskMini">语言：${escapeHtml(meta.target_language || '-')}　数量：${escapeHtml(countText)}　排队：${escapeHtml(formatTaskTime(job.queued_at))}　开始：${escapeHtml(formatTaskTime(job.started_at))}　结束：${escapeHtml(formatTaskTime(job.finished_at))}</div>
            <div class="taskMini">最后日志：${escapeHtml(lastLog)}</div>
            ${sourcePath ? `<div class="taskMini">输入：${escapeHtml(sourcePath)}</div>` : ''}
          </div>
        `;
      }).join('');
    }
    function renderScriptTaskProgress(status) {
      const box = document.getElementById('scriptTaskProgress');
      if (!box) return;
      const logs = status.logs || [];
      const joined = logs.join('\n');
      let stage = '未运行';
      let detail = '点击生成脚本后，这里会显示当前阶段。';
      let percent = 0;
      let stateClass = 'idle';
      if (status.running) {
        stateClass = 'running';
        const activeCount = Number(status.active_count || 0);
        const queueCount = Number(status.queue_count || 0);
        if (activeCount > 1) {
          stage = `${activeCount} 组运行中${queueCount ? ` / ${queueCount} 组排队` : ''}`;
          percent = 64;
          const runningJobs = (status.jobs || []).filter(job => job.running).map(job => `${job.task} #${job.id}`).join(' / ');
          detail = runningJobs || '多个任务正在并发运行';
        } else {
          const batchMatch = joined.match(/累计\s+(\d+)\/(\d+)/g);
          if (batchMatch && batchMatch.length) {
          const latest = batchMatch[batchMatch.length - 1].match(/累计\s+(\d+)\/(\d+)/);
          const done = latest ? Number(latest[1]) : 0;
          const total = latest ? Number(latest[2]) : 0;
          stage = total ? `裂变生成中 ${done}/${total}` : '裂变生成中';
          percent = total ? Math.min(96, 58 + Math.round((done / total) * 36)) : 72;
          } else if (joined.includes('开始脚本裂变第') || joined.includes('开始脚本裂变请求')) {
          stage = '裂变生成中';
          percent = 72;
          } else if (joined.includes('已启用裂变')) {
          stage = '准备裂变';
          percent = 58;
          } else if (joined.includes('开始脚本产出请求')) {
          stage = '复刻生成中';
          percent = 34;
          } else {
          stage = `运行中：${status.task || '任务'}`;
          percent = 18;
          }
          detail = logs[logs.length - 1] || '任务正在运行';
        }
      } else if (status.exit_code === 0) {
        stateClass = 'done';
        stage = '已完成';
        percent = 100;
        detail = logs.find(line => line.includes('脚本产出成功')) || logs[logs.length - 1] || '任务已完成';
      } else if (status.exit_code !== null) {
        stateClass = 'failed';
        stage = `失败：${status.exit_code}`;
        percent = 100;
        detail = logs[logs.length - 1] || '任务失败';
      }
      box.className = `taskProgress ${stateClass}`;
      scriptTaskStage.textContent = stage;
      scriptTaskProgressFill.style.width = `${percent}%`;
      scriptTaskDetail.textContent = detail;
      renderScriptTaskBoard(status);
    }
    function currentReferenceCloneStatus() {
      const selectedPath = script_reference_analysis_path.value.trim();
      const hotScripts = currentFiles.hot_script_files || currentFiles.analysis_files || [];
      return hotScripts.find(file => file.path === selectedPath) || null;
    }
    function canRunScriptGeneration() {
      const selected = currentReferenceCloneStatus();
      if (selected && selected.clone_status === '已复刻' && !script_enable_mutation_rewrite.checked) {
        showToast('这个爆款脚本已经复刻过；如需继续生成，请勾选“是否裂变”。', true);
        return false;
      }
      if (script_enable_mutation_rewrite.checked && (!selected || selected.clone_status !== '已复刻')) {
        showToast('当前脚本还没有复刻稿，无法执行裂变。请先关闭“是否裂变”生成复刻稿。', true);
        return false;
      }
      return true;
    }
    function renderSelectedScriptName() {
      const el = document.getElementById('scriptSelectedReferenceName');
      if (!el) return;
      const selectedPath = script_reference_analysis_path.value.trim();
      if (!selectedPath) {
        el.textContent = '请从下方当前产品爆款脚本中选择';
        el.title = '';
        renderSelectedVideoPreview(null);
        return;
      }
      const hotScripts = currentFiles.hot_script_files || currentFiles.analysis_files || [];
      const matched = hotScripts.find(file => file.path === selectedPath);
      const name = matched ? matched.name : selectedPath.split('/').pop();
      el.textContent = name || selectedPath;
      el.title = selectedPath;
      renderSelectedVideoPreview(matched || null);
      updateCurrentScriptBatchCard();
    }
    function renderSelectedVideoPreview(file) {
      const el = document.getElementById('scriptSelectedVideoPreview');
      if (!el) return;
      if (!file) {
        if (el.dataset.previewKey === 'empty') return;
        el.dataset.previewKey = 'empty';
        el.innerHTML = '<div class="scriptVideoMissing">请选择脚本后显示对应 MP4 视频预览</div>';
        return;
      }
      const videoPath = file.source_video_path || '';
      if (!videoPath) {
        const missingKey = `missing:${file.path || file.name || ''}`;
        if (el.dataset.previewKey === missingKey) return;
        el.dataset.previewKey = missingKey;
        el.innerHTML = `
          <div class="scriptVideoMissing">
            未找到对应 MP4。<br>
            当前脚本：${escapeHtml(file.name || '')}
          </div>
        `;
        return;
      }
      const previewKey = `video:${videoPath}`;
      if (el.dataset.previewKey === previewKey) return;
      el.dataset.previewKey = previewKey;
      const src = `/api/video-preview?path=${encodeURIComponent(videoPath)}`;
      el.innerHTML = `
        <video controls preload="metadata" src="${src}"></video>
        <div class="scriptVideoMeta">
          <div><strong>视频：</strong>${escapeHtml(file.source_video_name || videoPath.split('/').pop())}</div>
          <div><strong>路径：</strong>${escapeHtml(videoPath)}</div>
        </div>
      `;
    }
    async function selectScriptReferencePath(path) {
      script_reference_analysis_path.value = path;
      renderSelectedScriptName();
      updateCurrentScriptBatchCard();
      await saveScriptDefaults(true);
      showToast('已选择参考爆款脚本');
    }
    function renderFiles(files) {
      currentFiles = files || {};
      renderSelectedScriptName();
      if (document.getElementById('csvFiles')) {
        csvFiles.innerHTML = files.csv_files.length ? files.csv_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无 CSV</div>';
      }
      if (document.getElementById('downloadDirs')) {
        downloadDirs.innerHTML = files.download_dirs.length ? files.download_dirs.map(f => `<div class="fileitem">${openButton(f)}<span class="filemeta">${f.count} 个 mp4</span></div>`).join('') : '<div class="empty">暂无下载目录</div>';
      }
      if (document.getElementById('analysisFiles')) {
        analysisFiles.innerHTML = files.analysis_files.length ? files.analysis_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无拆解结果</div>';
      }
      if (document.getElementById('scriptAnalysisFiles')) {
        const hotScripts = files.hot_script_files || files.analysis_files || [];
        if (document.getElementById('scriptHotScriptCount')) {
          scriptHotScriptCount.textContent = `${files.hot_script_count || hotScripts.length || 0} 个`;
        }
        if (document.getElementById('scriptHotScriptDir')) {
          scriptHotScriptDir.textContent = files.hot_script_dir ? `目录：${files.hot_script_dir}` : '未匹配到当前产品的爆款脚本目录';
          scriptHotScriptDir.title = files.hot_script_dir || '';
        }
        scriptAnalysisFiles.innerHTML = renderScriptReferencePicker(hotScripts);
        if (document.getElementById('scriptLibrarySearch')) {
          filterScriptLibrary(scriptLibrarySearch.value);
        }
      }
      if (document.getElementById('scriptFiles')) {
        if (document.getElementById('scriptOutputCount')) {
          scriptOutputCount.textContent = `${files.script_output_count || files.script_files.length || 0} 个`;
        }
        if (document.getElementById('scriptOutputDir')) {
          scriptOutputDir.textContent = files.script_output_dir ? `目录：${files.script_output_dir}` : '未匹配到脚本产出目录';
          scriptOutputDir.title = files.script_output_dir || '';
        }
        scriptFiles.innerHTML = renderScriptOutputBatches(files.script_files || []);
      }
      if (document.getElementById('adaptedScriptFiles')) {
        adaptedScriptFiles.innerHTML = files.adapted_script_files.length ? files.adapted_script_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无脚本适配结果</div>';
      }
      if (document.getElementById('adaptSourceScriptFiles')) {
        adaptSourceScriptFiles.innerHTML = files.script_files.length ? files.script_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无可选成品脚本</div>';
      }
      if (document.getElementById('assembledVideoFiles')) {
        assembledVideoFiles.innerHTML = files.assembled_video_files.length ? files.assembled_video_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无视频生成流程输出</div>';
      }
      if (document.getElementById('publishRecordFiles')) {
        publishRecordFiles.innerHTML = files.publish_record_files.length ? files.publish_record_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无发布记录</div>';
      }
      if (document.getElementById('metricsFiles')) {
        const summaryTables = files.metrics_summary_tables || [];
        metricsFiles.innerHTML = summaryTables.length ? summaryTables.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无数据归因结果</div>';
      }
      if (document.getElementById('optimizationFiles')) {
        optimizationFiles.innerHTML = files.optimization_files.length ? files.optimization_files.map(f => `<div class="fileitem">${openButton(f)}</div>`).join('') : '<div class="empty">暂无脚本优化结果</div>';
      }
    }
    async function refresh() {
      const st = await api('/api/status');
      dot.className = 'dot' + (st.running ? ' running' : '');
      statusText.textContent = st.running ? `运行中：${st.task}` : (st.exit_code === null ? '控制台在线' : `已结束：${st.exit_code}`);
      renderScriptTaskProgress(st);
      const logText = (st.logs || []).join('\n');
      document.querySelectorAll('pre').forEach(el => {
        if (el) {
          el.textContent = logText;
          el.scrollTop = el.scrollHeight;
        }
      });
      renderFiles(st.files);
      const attributionOutput = document.getElementById('data_attribution_output_table_path');
      if (attributionOutput) {
        const latest = (st.files.metrics_summary_tables || [])[0];
        setPathInputDisplay('data_attribution_output_table_path', latest ? latest.path : '');
      }
    }
    if (document.getElementById('script_generation_backend')) {
      script_generation_backend.addEventListener('change', updateScriptBackendControls);
      [
        script_generation_backend,
        script_enable_mutation_rewrite,
        script_mutation_variants,
        script_mutation_source,
        script_country,
        script_target_language,
        script_total_duration,
        script_reference_analysis_path
      ].forEach(el => {
        if (el) el.addEventListener('input', updateCurrentScriptBatchCard);
        if (el) el.addEventListener('change', updateCurrentScriptBatchCard);
      });
    }
    loadConfig().then(refresh);
    refreshAgentServices();
    setInterval(refresh, 2000);
    setInterval(refreshAgentServices, 5000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/collect":
                self.send_response(302)
                self.send_header("Location", LATEST_HOT_VIDEO_AGENT_URL)
                self.end_headers()
            elif path == "/analyze":
                self.send_response(302)
                self.send_header("Location", LATEST_VIDEO_TEARDOWN_AGENT_URL)
                self.end_headers()
            elif path == "/script":
                self.send_response(302)
                self.send_header("Location", LATEST_SCRIPT_PRODUCTION_AGENT_URL)
                self.end_headers()
            elif path == "/adapt":
                self.send_response(302)
                self.send_header("Location", LATEST_SCRIPT_ADAPTATION_AGENT_URL)
                self.end_headers()
            elif path == "/assemble":
                self.send_response(302)
                self.send_header("Location", LATEST_VIDEO_OUTPUT_AGENT_URL)
                self.end_headers()
            elif path == "/finished":
                self.send_response(302)
                self.send_header("Location", LATEST_FINISHED_VIDEO_MANAGER_URL)
                self.end_headers()
            elif path == "/rewrite":
                self.send_response(302)
                self.send_header("Location", LATEST_PRODUCT_SCRIPT_REWRITE_URL)
                self.end_headers()
            elif path == "/compose":
                self.send_response(302)
                self.send_header("Location", LATEST_VIDEO_ASSEMBLY_AGENT_URL)
                self.end_headers()
            elif path in (
                "/",
                "/product",
                "/publish",
                "/metrics",
                "/optimize",
            ):
                body = (
                    INDEX_HTML
                    .replace("__HOT_VIDEO_AGENT_URL__", LATEST_HOT_VIDEO_AGENT_URL)
                    .replace("__VIDEO_TEARDOWN_AGENT_URL__", LATEST_VIDEO_TEARDOWN_AGENT_URL)
                    .replace("__SCRIPT_PRODUCTION_AGENT_URL__", LATEST_SCRIPT_PRODUCTION_AGENT_URL)
                    .replace("__SCRIPT_ADAPTATION_AGENT_URL__", LATEST_SCRIPT_ADAPTATION_AGENT_URL)
                    .replace("__VIDEO_OUTPUT_AGENT_URL__", LATEST_VIDEO_OUTPUT_AGENT_URL)
                    .replace("__FINISHED_VIDEO_MANAGER_URL__", LATEST_FINISHED_VIDEO_MANAGER_URL)
                    .replace("__PRODUCT_SCRIPT_REWRITE_URL__", LATEST_PRODUCT_SCRIPT_REWRITE_URL)
                    .replace("__VIDEO_ASSEMBLY_AGENT_URL__", LATEST_VIDEO_ASSEMBLY_AGENT_URL)
                    .replace("__PRODUCT_INFO_SOURCE_DIR__", PRODUCT_INFO_SOURCE_DIR.as_posix())
                    .replace("__SCRIPT_MISTAKE_BOOK_SOURCE_ROOT__", SCRIPT_MISTAKE_BOOK_SOURCE_ROOT.as_posix())
                    .encode("utf-8")
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/config":
                self._json(200, config_payload())
            elif path == "/api/fastmoss-category-tree":
                self._json(200, fastmoss_category_tree_payload())
            elif path == "/api/product-profile":
                self._json(200, load_unified_console_config().get("product_profile", DEFAULT_PRODUCT_PROFILE))
            elif path == "/api/status":
                payload = JOBS.status()
                payload["files"] = cached_file_listing()
                self._json(200, payload)
            elif path == "/api/agent-services":
                self._json(200, agent_services_payload())
            elif path == "/api/video-preview":
                raw_path = query.get("path", [""])[0]
                if not raw_path:
                    raise ValueError("缺少 path")
                send_local_video(self, raw_path)
            elif path == "/api/open-path":
                raw_path = query.get("path", [""])[0]
                if not raw_path:
                    raise ValueError("缺少 path")
                open_local_path(raw_path)
                name = html.escape(Path(unquote(raw_path)).name)
                send_html(self, 200, f"<!doctype html><meta charset='utf-8'><title>已打开</title><body style='font:14px -apple-system,BlinkMacSystemFont,sans-serif;padding:24px'>已打开：{name}</body>")
            else:
                self._json(404, {"error": "Not found"})
        except Exception as exc:
            self._json(500, {"error": public_error_message(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                self._json(200, save_collect_config(self._read_json()))
            elif path == "/api/product-profile":
                self._json(200, save_product_profile(self._read_json()))
            elif path == "/api/product-project/select":
                self._json(200, select_product_project(self._read_json()))
            elif path == "/api/teardown-defaults":
                self._json(200, save_teardown_defaults(self._read_json()))
            elif path == "/api/script-defaults":
                self._json(200, save_script_defaults(self._read_json()))
            elif path == "/api/content-workflow-defaults":
                self._json(200, save_content_workflow_defaults(self._read_json()))
            elif path == "/api/run/full":
                config = load_unified_console_config()
                validate_collect_input(config)
                snapshot_path = write_unified_runtime_config("collect", config)
                command, env_extra, metadata, cwd = latest_hot_video_command(config)
                metadata["snapshot_path"] = display_path(snapshot_path)
                JOBS.start(
                    "视频采集（最新 tkfastmoss agent）",
                    command,
                    env_extra,
                    metadata,
                    cwd,
                )
                self._json(200, {"ok": True})
            elif path == "/api/run/analyze":
                config = load_unified_console_config()
                validate_analysis_input_path(config)
                snapshot_path = write_unified_runtime_config("analyze", config)
                command, env_extra, metadata, cwd = latest_video_teardown_command(config)
                metadata["snapshot_path"] = display_path(snapshot_path)
                JOBS.start(
                    "脚本解析（最新 video-teardown-agent）",
                    command,
                    env_extra,
                    metadata,
                    cwd,
                )
                self._json(200, {"ok": True})
            elif path == "/api/run/script":
                config = load_unified_console_config()
                validate_script_generation_input(config)
                snapshot_path = write_unified_runtime_config("script", config)
                job_id = JOBS.start(
                    "脚本产出",
                    module_cmd("opc_engine.features.script_generation.generate_product_script"),
                    {
                        "OPC_APP_CONFIG_PATH": snapshot_path,
                        "SCRIPT_GENERATION_INPUTS_PATH": snapshot_path,
                    },
                    {
                        "target_language": config.get("script_target_language", ""),
                        "country": config.get("script_country", ""),
                        "mutation_variants": config.get("script_mutation_variants", ""),
                        "mutation_enabled": bool(config.get("script_enable_mutation_rewrite")),
                        "mutation_mode": config.get("script_mutation_mode", "standard"),
                        "mutation_source": config.get("script_mutation_source", ""),
                        "reference_path": config.get("script_reference_analysis_path", ""),
                        "snapshot_path": display_path(snapshot_path),
                    },
                )
                self._json(200, {"ok": True, "job_id": job_id, "snapshot": display_path(snapshot_path)})
            elif path == "/api/run/adapt":
                config = load_unified_console_config()
                if not selected_product_doc_path(config):
                    raise ValueError("请先从产品信息 Markdown 中选择本次脚本适配对应的产品")
                if not str(config.get("script_adaptation_input_path", "") or "").strip():
                    raise ValueError("请先选择要适配的成品脚本 Markdown")
                snapshot_path = write_unified_runtime_config("adapt", config)
                command, env_extra, metadata, cwd = latest_script_adaptation_command(config)
                metadata["snapshot_path"] = display_path(snapshot_path)
                JOBS.start(
                    "脚本适配（最新 script-adaptation-agent）",
                    command,
                    env_extra,
                    metadata,
                    cwd,
                )
                self._json(200, {"ok": True})
            elif path == "/api/run/assemble":
                config = load_unified_console_config()
                if not selected_product_doc_path(config):
                    raise ValueError("请先从产品信息 Markdown 中选择本次视频产出对应的产品")
                snapshot_path = write_unified_runtime_config("assemble", config)
                command, env_extra, metadata, cwd = latest_video_output_command(config)
                metadata["snapshot_path"] = display_path(snapshot_path)
                JOBS.start(
                    "视频产出（最新 Video-Generation agent）",
                    command,
                    env_extra,
                    metadata,
                    cwd,
                )
                self._json(200, {"ok": True})
            elif path == "/api/run/publish":
                config = load_unified_console_config()
                snapshot_path = write_unified_runtime_config("publish", config)
                JOBS.start("视频发布流程框架", module_cmd("opc_engine.features.script_adaptation.content_workflow_stage", "publish"), {"OPC_APP_CONFIG_PATH": snapshot_path}, {"snapshot_path": display_path(snapshot_path)})
                self._json(200, {"ok": True})
            elif path == "/api/run/metrics-download":
                config = load_unified_console_config()
                snapshot_path = write_unified_runtime_config("metrics-download", config)
                JOBS.start("数据归因阶段一：自动下载数据", module_cmd("opc_engine.features.script_adaptation.content_workflow_stage", "metrics_download"), {"OPC_APP_CONFIG_PATH": snapshot_path}, {"snapshot_path": display_path(snapshot_path)})
                self._json(200, {"ok": True})
            elif path == "/api/run/metrics-natural-download":
                config = load_unified_console_config()
                snapshot_path = write_unified_runtime_config("metrics-natural-download", config)
                JOBS.start("下载自然流数据", module_cmd("opc_engine.features.script_adaptation.content_workflow_stage", "metrics_natural_download"), {"OPC_APP_CONFIG_PATH": snapshot_path}, {"snapshot_path": display_path(snapshot_path)})
                self._json(200, {"ok": True})
            elif path == "/api/run/metrics-ads-download":
                config = load_unified_console_config()
                snapshot_path = write_unified_runtime_config("metrics-ads-download", config)
                JOBS.start("下载投放数据", module_cmd("opc_engine.features.script_adaptation.content_workflow_stage", "metrics_ads_download"), {"OPC_APP_CONFIG_PATH": snapshot_path}, {"snapshot_path": display_path(snapshot_path)})
                self._json(200, {"ok": True})
            elif path == "/api/run/metrics":
                config = load_unified_console_config()
                snapshot_path = write_unified_runtime_config("metrics", config)
                JOBS.start("数据归因阶段二：整理与分析", module_cmd("opc_engine.features.script_adaptation.content_workflow_stage", "metrics"), {"OPC_APP_CONFIG_PATH": snapshot_path}, {"snapshot_path": display_path(snapshot_path)})
                self._json(200, {"ok": True})
            elif path == "/api/run/optimize":
                config = load_unified_console_config()
                snapshot_path = write_unified_runtime_config("optimize", config)
                JOBS.start("脚本优化", module_cmd("opc_engine.features.script_adaptation.content_workflow_stage", "optimize"), {"OPC_APP_CONFIG_PATH": snapshot_path}, {"snapshot_path": display_path(snapshot_path)})
                self._json(200, {"ok": True})
            elif path == "/api/open-path":
                payload = self._read_json()
                raw_path = payload.get("path", "")
                if not raw_path:
                    raise ValueError("缺少 path")
                opened = open_local_path(raw_path)
                self._json(200, {"ok": True, "opened": opened, "path": display_path(raw_path), "name": Path(unquote(raw_path)).name})
            elif path == "/api/choose-analysis-path":
                payload = self._read_json()
                selected = choose_analysis_path(payload.get("kind", "folder"))
                self._json(200, {"path": display_path(selected)})
            elif path == "/api/choose-script-reference-path":
                selected = choose_script_reference_path()
                self._json(200, {"path": display_path(selected)})
            elif path == "/api/choose-path":
                payload = self._read_json()
                selected = choose_local_path(payload.get("kind", "file"), payload.get("prompt", "选择文件"))
                self._json(200, {"path": display_path(selected)})
            elif path == "/api/stop":
                self._json(200, {"stopped": JOBS.stop()})
            elif path == "/api/agent-services/start":
                payload = self._read_json()
                self._json(200, start_agent_service(str(payload.get("id", "") or "")))
            else:
                self._json(404, {"error": "Not found"})
        except Exception as exc:
            self._json(400, {"error": public_error_message(exc)})

    def log_message(self, *_):
        return


def main():
    KNOWLEDGE_BASE_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"OPC 内容量化增长引擎已启动: {url}")
    if os.environ.get("KESAI_APP_NO_OPEN") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
