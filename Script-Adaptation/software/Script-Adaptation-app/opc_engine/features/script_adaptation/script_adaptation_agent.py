#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from opc_shared.global_ai import load_profile

from opc_engine.core.project_assets import (
    ensure_project_dirs,
    product_project_ready,
    product_project_root,
    require_product_project,
    source_stage_dir,
)
from opc_engine.features.script_adaptation import content_workflow_stage as workflow


ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_DIR = AGENT_DIR / "agent_config"
AGENT_SETTINGS_PATH = AGENT_CONFIG_DIR / "agent_settings.json"
AGENT_SECRETS_PATH = AGENT_CONFIG_DIR / "agent_secrets.local.json"


@dataclass(frozen=True)
class StageSpec:
    name: str
    label: str
    purpose: str
    workflow_inputs: tuple[str, ...]
    runner: Callable[[dict[str, Any]], None]
    side_effect: str
    config_keys: tuple[str, ...] = ()
    path_keys: tuple[str, ...] = ()
    needs_text_model: bool = False


STAGES: dict[str, StageSpec] = {
    "adapt": StageSpec(
        name="adapt",
        label="脚本适配",
        purpose="把成品脚本适配成文生图 JSON、视频片段 CSV 和完整 Markdown 交付包。",
        workflow_inputs=("script_adaptation",),
        runner=workflow.run_adapt,
        side_effect="会在输入脚本和提示词齐全时调用文本模型，不调用真实视频生成模型。",
        config_keys=("script_adaptation_target_model", "script_adaptation_segment_seconds"),
        path_keys=("script_adaptation_input_path", "script_adaptation_prompt_path"),
        needs_text_model=True,
    ),
    "assemble": StageSpec(
        name="assemble",
        label="视频生成流程框架",
        purpose="读取已有视频片段目录，生成 manifest / plan，检测到 ffmpeg 时可尝试本地合并。",
        workflow_inputs=("video_generation",),
        runner=workflow.run_assemble,
        side_effect="只处理本地已有片段；不会调用 Veo、可灵或其他视频生成服务。",
        config_keys=("clip_assembly_output_name", "clip_assembly_notes"),
        path_keys=("clip_assembly_input_dir",),
    ),
    "publish": StageSpec(
        name="publish",
        label="视频发布记录",
        purpose="根据待发布视频、账号别名、文案和标签生成本地发布计划/记录。",
        workflow_inputs=("video_publish",),
        runner=workflow.run_publish,
        side_effect="只写本地发布记录；不会登录 TikTok、上传视频或改变远程账号状态。",
        config_keys=("video_publish_account", "video_publish_caption", "video_publish_tags", "video_publish_mode"),
        path_keys=("video_publish_input_path",),
    ),
    "metrics_download": StageSpec(
        name="metrics_download",
        label="数据归因下载",
        purpose="分别下载自然流数据和投放数据，写入当前产品项目 raw_data。",
        workflow_inputs=("data_attribution",),
        runner=workflow.run_metrics_download,
        side_effect="可能启动下载自动化并访问外部平台。",
        config_keys=(
            "data_attribution_download_script_path",
            "data_attribution_ads_download_script_path",
            "natural_flow_account_group",
        ),
    ),
    "metrics_natural_download": StageSpec(
        name="metrics_natural_download",
        label="自然流数据下载",
        purpose="下载自然流数据，供数据归因阶段使用。",
        workflow_inputs=("data_attribution",),
        runner=workflow.run_metrics_natural_download,
        side_effect="可能启动下载自动化并访问外部平台。",
        config_keys=("data_attribution_download_script_path", "natural_flow_account_group"),
    ),
    "metrics_ads_download": StageSpec(
        name="metrics_ads_download",
        label="投放数据下载",
        purpose="下载投放表现数据，供数据归因阶段使用。",
        workflow_inputs=("data_attribution",),
        runner=workflow.run_metrics_ads_download,
        side_effect="可能启动下载自动化并访问外部平台。",
        config_keys=("data_attribution_ads_download_script_path",),
    ),
    "metrics": StageSpec(
        name="metrics",
        label="数据归因整理",
        purpose="读取自然流和投放原始表，按作品维度合并并输出归因汇总。",
        workflow_inputs=("data_attribution",),
        runner=workflow.run_metrics,
        side_effect="只读取本地表格并写入归因结果。",
        config_keys=("data_recovery_manual_metrics",),
        path_keys=("data_recovery_input_path", "data_recovery_natural_input_path", "data_recovery_ads_input_path"),
    ),
    "optimize": StageSpec(
        name="optimize",
        label="脚本优化",
        purpose="读取原脚本和归因数据，生成下一轮脚本优化建议框架。",
        workflow_inputs=("script_optimization",),
        runner=workflow.run_optimize,
        side_effect="只写本地优化建议，不自动改写原脚本。",
        config_keys=("script_optimization_notes",),
        path_keys=("script_optimization_input_path", "script_optimization_metrics_path"),
    ),
}


STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "adapt": ("适配", "分镜", "视频提示词", "首帧", "文生图", "image", "csv", "video_model_input_text"),
    "assemble": ("合并", "拼接", "片段", "视频生成", "assemble", "ffmpeg", "manifest"),
    "publish": ("发布", "账号", "标题", "文案", "标签", "publish", "caption"),
    "metrics_download": ("下载数据", "下载自然", "下载投放", "自然流下载", "投放下载", "metrics download"),
    "metrics": ("归因", "数据分析", "指标整理", "作品归因", "metrics", "roas", "gmv"),
    "optimize": ("优化", "迭代", "复盘", "改脚本", "optimize"),
}


def display_path(path: Path | str) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def resolve_config_path(value: Any) -> Path | None:
    text = os.path.expandvars(str(value or "").strip())
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def require_markdown_path(path: Path) -> None:
    if path.suffix.lower() != ".md":
        raise SystemExit(f"产品视频脚本输入必须是 .md 文件: {path}")


def has_api_key(config: dict[str, Any]) -> bool:
    return bool(workflow.get_api_key(config))


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"配置文件不是有效 JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"配置文件顶层必须是 JSON object: {path}")
    return data


def visible_items(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if not key.startswith("_")
    }


def expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {key: expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_environment(item) for item in value]
    return value


def resolve_agent_config_file(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise SystemExit("agent_settings.json 缺少能力文件路径")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = AGENT_CONFIG_DIR / path
    path = path.resolve()
    try:
        path.relative_to(AGENT_CONFIG_DIR.resolve())
    except ValueError as exc:
        raise SystemExit(f"能力文件必须放在智能体配置目录内: {path}") from exc
    return path


def load_local_agent_config() -> dict[str, Any]:
    settings = read_json_object(AGENT_SETTINGS_PATH)
    if not settings:
        raise SystemExit(f"缺少智能体主配置: {AGENT_SETTINGS_PATH}")

    config: dict[str, Any] = {}
    for section_name in ("product_project", "model", "adaptation"):
        section = settings.get(section_name, {})
        if isinstance(section, dict):
            config.update(expand_environment(visible_items(section)))

    files = settings.get("files", {})
    if isinstance(files, dict):
        prompt_paths = files.get("script_adaptation_prompt_paths")
        if isinstance(prompt_paths, dict):
            config["script_adaptation_prompt_paths"] = {
                str(key): str(resolve_agent_config_file(value))
                for key, value in visible_items(prompt_paths).items()
                if value
            }
        target_model = str(config.get("script_adaptation_target_model") or "veo").strip()
        prompt_value = (
            config.get("script_adaptation_prompt_paths", {}).get(target_model)
            if isinstance(config.get("script_adaptation_prompt_paths"), dict)
            else ""
        ) or files.get("script_adaptation_prompt_path")
        prompt_path = resolve_agent_config_file(prompt_value)
        config["script_adaptation_prompt_path"] = str(prompt_path)

    secrets = read_json_object(AGENT_SECRETS_PATH)
    if secrets:
        for key, value in visible_items(secrets).items():
            if value:
                config[key] = value

    profile = load_profile("text")
    config["modelmesh_base_url"] = profile["base_url"]
    config["video_analysis_model"] = profile["model"]
    config["script_adaptation_text_model"] = profile["model"]
    config["modelmesh_api_key"] = profile["api_key"]

    return config


class ScriptAdaptationAgent:
    name = "脚本适配智能体"

    def infer_stage(self, task: str) -> tuple[str | None, list[tuple[str, int]]]:
        text = task.lower()
        if "下载" in text and "自然" in text:
            return "metrics_natural_download", [("metrics_natural_download", 2)]
        if "下载" in text and ("投放" in text or "广告" in text or "ads" in text):
            return "metrics_ads_download", [("metrics_ads_download", 2)]

        scores: list[tuple[str, int]] = []
        for stage, keywords in STAGE_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword.lower() in text)
            if score:
                scores.append((stage, score))
        scores.sort(key=lambda item: item[1], reverse=True)
        if not scores:
            return None, []
        if len(scores) == 1 or scores[0][1] > scores[1][1]:
            return scores[0][0], scores
        return None, scores

    def load_stage_config(self, stage: str) -> dict[str, Any]:
        _ = STAGES[stage]
        return load_local_agent_config()

    def inspect(self, stage: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = STAGES[stage]
        config = self.load_stage_config(stage)
        if overrides:
            config.update(overrides)
        checks: list[dict[str, str]] = []

        def check(level: str, message: str, detail: str = "") -> None:
            checks.append({"level": level, "message": message, "detail": detail})

        if product_project_ready(config):
            check("ok", "当前产品项目可用", display_path(product_project_root(config)))
        else:
            check("error", "当前产品项目未就绪", "请先在「产品信息」页面保存产品项目。")

        inputs: dict[str, str] = {}
        for key in spec.config_keys:
            value = config.get(key, "")
            inputs[key] = str(value or "")
            if str(value or "").strip():
                check("ok", f"配置已填写: {key}", str(value))
            else:
                check("warn", f"配置为空: {key}", "会使用代码默认值或生成待补充内容。")

        for key in spec.path_keys:
            path = resolve_config_path(config.get(key))
            inputs[key] = display_path(path) if path else ""
            if path and path.exists():
                check("ok", f"路径存在: {key}", display_path(path))
            elif path:
                check("warn", f"路径不存在: {key}", display_path(path))
            else:
                check("warn", f"路径未填写: {key}", "该阶段可能回退到默认值、最新文件或本地框架。")

        if stage == "adapt":
            prompt = workflow.get_script_adaptation_prompt(config)
            source_path = resolve_config_path(config.get("script_adaptation_input_path"))
            source_text = workflow.read_text(source_path) if source_path else ""
            if prompt:
                check("ok", "脚本适配提示词可读取", f"{len(prompt)} 字符")
            else:
                check("warn", "脚本适配提示词为空", "执行时会生成本地占位框架。")
            if source_text and prompt and has_api_key(config):
                check("ok", "文本模型调用条件已满足", "可执行完整脚本适配。")
            elif source_text and prompt:
                check("error", "缺少文本模型 API Key", "请设置 MODELMESH_API_KEY 或在本地配置保存 modelmesh_api_key。")

        ready_to_run = not any(item["level"] == "error" for item in checks)
        command = f"python3 -m opc_engine.features.script_adaptation.script_adaptation_agent --stage {stage} --execute"
        return {
            "agent": self.name,
            "stage": spec.name,
            "label": spec.label,
            "purpose": spec.purpose,
            "side_effect": spec.side_effect,
            "ready_to_run": ready_to_run,
            "inputs": inputs,
            "checks": checks,
            "execute_command": command,
        }

    def run(self, stage: str, overrides: dict[str, Any] | None = None) -> None:
        spec = STAGES[stage]
        config = self.load_stage_config(stage)
        if overrides:
            config.update(overrides)
        require_product_project(config, f"执行{spec.label}")
        ensure_project_dirs(config)
        spec.runner(config)

    def save_stdin_script(self, config: dict[str, Any]) -> Path:
        text = sys.stdin.read().strip()
        if not text:
            raise SystemExit("未从 stdin 读取到脚本文本。")
        require_product_project(config, "保存待适配脚本")
        ensure_project_dirs(config)
        source_id = f"manual_script_{workflow.timestamp()}"
        script_dir = source_stage_dir(source_id, "scripts", config)
        script_path = script_dir / f"{source_id}.md"
        script_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        return script_path


def print_stage_list() -> None:
    print("可用阶段:")
    for stage, spec in STAGES.items():
        print(f"- {stage}: {spec.label} - {spec.purpose}")


def print_report(report: dict[str, Any]) -> None:
    print(f"{report['agent']} / {report['label']}")
    print(f"阶段: {report['stage']}")
    print(f"目标: {report['purpose']}")
    print(f"边界: {report['side_effect']}")
    print("")
    print("检查:")
    for item in report["checks"]:
        marker = {"ok": "OK", "warn": "WARN", "error": "ERROR"}.get(item["level"], item["level"].upper())
        detail = f" - {item['detail']}" if item.get("detail") else ""
        print(f"- [{marker}] {item['message']}{detail}")
    print("")
    if report["ready_to_run"]:
        print("状态: 可以执行。")
        print(f"执行: {report['execute_command']}")
    else:
        print("状态: 暂不建议执行，请先处理 ERROR 项。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OPC script adaptation workflow agent.")
    parser.add_argument("task", nargs="*", help="自然语言任务描述，例如：适配脚本、整理数据归因、生成发布记录")
    parser.add_argument("--stage", choices=sorted(STAGES), help="明确指定要处理的 workflow 阶段")
    parser.add_argument("--execute", action="store_true", help="真正执行阶段；默认只巡检和生成计划")
    parser.add_argument("--script-file", help="本次直接使用的成品脚本文件路径，仅用于 adapt 阶段")
    parser.add_argument("--target-model", choices=("omni", "grok"), help="本次脚本适配使用的视频模型")
    parser.add_argument("--target-language", help="本次适配只使用的目标语言；留空时从脚本文件名国家代码推断")
    parser.add_argument("--output-stem", help="本次适配输出的固定文件名，不含扩展名")
    parser.add_argument("--script-stdin", action="store_true", help="从 stdin 读取成品脚本文本并保存到当前产品项目后适配")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出巡检结果")
    parser.add_argument("--list", action="store_true", help="列出可用阶段")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    agent = ScriptAdaptationAgent()

    if args.list:
        print_stage_list()
        return 0

    task = " ".join(args.task).strip()
    stage = args.stage
    candidates: list[tuple[str, int]] = []
    if not stage and (args.script_file or args.script_stdin):
        stage = "adapt"

    if not stage and task:
        stage, candidates = agent.infer_stage(task)

    if not stage:
        if candidates:
            print("任务描述同时匹配多个阶段，请用 --stage 明确指定：")
            for candidate, score in candidates:
                print(f"- {candidate}: {STAGES[candidate].label} (score={score})")
        else:
            print("未能从任务描述识别阶段，请使用 --list 查看阶段，或用 --stage 指定。")
        return 2

    overrides: dict[str, Any] = {}
    if args.script_file:
        script_path = resolve_config_path(args.script_file)
        if script_path:
            require_markdown_path(script_path)
        overrides["script_adaptation_input_path"] = str(script_path or args.script_file)
    if args.target_model:
        overrides["script_adaptation_target_model"] = args.target_model
    if args.target_language:
        overrides["script_adaptation_target_language"] = args.target_language
    if args.output_stem:
        overrides["script_adaptation_output_stem"] = args.output_stem
    if args.script_stdin:
        if not args.execute:
            print("--script-stdin 会保存输入脚本；请同时加 --execute，或改用 --script-file 做无副作用巡检。")
            return 2
        config = agent.load_stage_config("adapt")
        if overrides:
            config.update(overrides)
        script_path = agent.save_stdin_script(config)
        overrides["script_adaptation_input_path"] = str(script_path)

    if (args.script_file or args.script_stdin) and stage != "adapt":
        print("--script-file / --script-stdin 只能用于 adapt 阶段。")
        return 2

    if args.execute:
        agent.run(stage, overrides)
        return 0

    report = agent.inspect(stage, overrides)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report["ready_to_run"] else 1


if __name__ == "__main__":
    sys.exit(main())
