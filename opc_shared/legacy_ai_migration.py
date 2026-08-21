from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MIGRATION_VERSION = 1
REPORT_NAME = "legacy_ai_migration.json"
PRIVATE_NAME = "legacy_ai_migration.private.json"
MARKER_NAME = f"legacy_ai_migration_v{MIGRATION_VERSION}.done"

FIELD_LABELS = {
    "OPC_VIDEO_ANALYSIS_API_BASE_URL": "视频解析 API 地址",
    "OPC_VIDEO_ANALYSIS_MODEL": "视频解析模型",
    "OPC_VIDEO_ANALYSIS_API_KEY": "视频解析 API Key",
    "OPC_TEXT_API_BASE_URL": "文本生成 API 地址",
    "OPC_TEXT_MODEL": "文本生成模型",
    "OPC_TEXT_API_KEY": "文本生成 API Key",
    "OTU_BASE_URL": "Omni API 地址",
    "IMAGE_MODEL": "Omni 图像模型",
    "OMNI_MODEL": "Omni 视频模型",
    "OTU_API_KEY": "Omni API Key",
    "GROK_BASE_URL": "Grok API 地址",
    "GROK_IMAGE_MODEL": "Grok 图像模型",
    "GROK_VIDEO_MODEL": "Grok 视频模型",
    "GROK_API_KEY": "Grok API Key",
}
SECRET_FIELDS = {
    "OPC_VIDEO_ANALYSIS_API_KEY",
    "OPC_TEXT_API_KEY",
    "OTU_API_KEY",
    "GROK_API_KEY",
}


def _json_value(data: dict[str, Any], dotted_key: str) -> str:
    current: Any = data
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return str(current or "").strip() if not isinstance(current, (dict, list)) else ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return values
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    return values


ENV_SOURCES = (
    (
        ".env",
        {
            "OPC_VIDEO_ANALYSIS_API_BASE_URL": ("OPC_VIDEO_ANALYSIS_API_BASE_URL", "MODELMESH_BASE_URL"),
            "OPC_VIDEO_ANALYSIS_MODEL": ("OPC_VIDEO_ANALYSIS_MODEL", "VIDEO_ANALYSIS_MODEL"),
            "OPC_VIDEO_ANALYSIS_API_KEY": ("OPC_VIDEO_ANALYSIS_API_KEY", "VIDEO_TEARDOWN_AGENT_API_KEY", "MODELMESH_API_KEY", "GEMINI_API_KEY"),
            "OPC_TEXT_API_BASE_URL": ("OPC_TEXT_API_BASE_URL", "MODELMESH_BASE_URL", "DEEPSEEK_BASE_URL"),
            "OPC_TEXT_MODEL": ("OPC_TEXT_MODEL", "SCRIPT_GENERATION_MODEL", "DEEPSEEK_MODEL"),
            "OPC_TEXT_API_KEY": ("OPC_TEXT_API_KEY", "DEEPSEEK_API_KEY", "MODELMESH_API_KEY", "GEMINI_API_KEY"),
            "OTU_BASE_URL": ("OTU_BASE_URL",),
            "IMAGE_MODEL": ("IMAGE_MODEL",),
            "OMNI_MODEL": ("OMNI_MODEL",),
            "OTU_API_KEY": ("OTU_API_KEY",),
            "GROK_BASE_URL": ("GROK_BASE_URL",),
            "GROK_IMAGE_MODEL": ("GROK_IMAGE_MODEL",),
            "GROK_VIDEO_MODEL": ("GROK_VIDEO_MODEL",),
            "GROK_API_KEY": ("GROK_API_KEY",),
        },
    ),
    (
        "Video-Generation/.env",
        {
            "OTU_BASE_URL": ("OTU_BASE_URL",),
            "IMAGE_MODEL": ("IMAGE_MODEL",),
            "OMNI_MODEL": ("OMNI_MODEL",),
            "OTU_API_KEY": ("OTU_API_KEY",),
            "GROK_BASE_URL": ("GROK_BASE_URL",),
            "GROK_IMAGE_MODEL": ("GROK_IMAGE_MODEL", "GROK_CHARACTER_API_MODEL"),
            "GROK_VIDEO_MODEL": ("GROK_VIDEO_MODEL", "GROK_VIDEO_API_MODEL"),
            "GROK_API_KEY": ("GROK_API_KEY",),
        },
    ),
    (
        "Video-Generation/agent_settings.env",
        {
            "OTU_BASE_URL": ("OTU_BASE_URL",),
            "IMAGE_MODEL": ("IMAGE_MODEL",),
            "OMNI_MODEL": ("OMNI_MODEL",),
            "GROK_BASE_URL": ("GROK_BASE_URL",),
            "GROK_IMAGE_MODEL": ("GROK_IMAGE_MODEL", "GROK_CHARACTER_API_MODEL"),
            "GROK_VIDEO_MODEL": ("GROK_VIDEO_MODEL", "GROK_VIDEO_API_MODEL"),
        },
    ),
)

JSON_SOURCES = (
    ("Script-Analysis/config/settings.json", {"OPC_VIDEO_ANALYSIS_API_BASE_URL": ("base_url",), "OPC_VIDEO_ANALYSIS_MODEL": ("model",), "OPC_VIDEO_ANALYSIS_API_KEY": ("api_key",)}),
    ("Script-Analysis/config/settings.local.json", {"OPC_VIDEO_ANALYSIS_API_BASE_URL": ("base_url",), "OPC_VIDEO_ANALYSIS_MODEL": ("model",), "OPC_VIDEO_ANALYSIS_API_KEY": ("api_key",)}),
    ("Hybrid-Script-Analysis/config/settings.json", {"OPC_VIDEO_ANALYSIS_API_BASE_URL": ("base_url",), "OPC_VIDEO_ANALYSIS_MODEL": ("model",), "OPC_VIDEO_ANALYSIS_API_KEY": ("api_key",)}),
    ("Hybrid-Script-Analysis/config/settings.local.json", {"OPC_VIDEO_ANALYSIS_API_BASE_URL": ("base_url",), "OPC_VIDEO_ANALYSIS_MODEL": ("model",), "OPC_VIDEO_ANALYSIS_API_KEY": ("api_key",)}),
    ("Script-Generation/app_config.json", {"OPC_TEXT_API_BASE_URL": ("ai_model.modelmesh_base_url", "modelmesh_base_url"), "OPC_TEXT_MODEL": ("ai_model.video_analysis_model", "ai_model.script_generation_model", "video_analysis_model", "script_generation_model"), "OPC_TEXT_API_KEY": ("ai_model.modelmesh_api_key", "modelmesh_api_key")}),
    ("Script-Generation/opc_engine/features/script_generation/config/model_settings.json", {"OPC_TEXT_API_BASE_URL": ("modelmesh_base_url",), "OPC_TEXT_MODEL": ("script_generation_model", "video_analysis_model"), "OPC_TEXT_API_KEY": ("modelmesh_api_key",)}),
    ("Script-Generation/runtime/model_settings.json", {"OPC_TEXT_API_BASE_URL": ("modelmesh_base_url",), "OPC_TEXT_MODEL": ("script_generation_model", "video_analysis_model"), "OPC_TEXT_API_KEY": ("modelmesh_api_key",)}),
    ("Hybrid-Script-Generation/app_config.json", {"OPC_TEXT_API_BASE_URL": ("ai_model.modelmesh_base_url", "modelmesh_base_url"), "OPC_TEXT_MODEL": ("ai_model.video_analysis_model", "ai_model.script_generation_model", "video_analysis_model", "script_generation_model"), "OPC_TEXT_API_KEY": ("ai_model.modelmesh_api_key", "modelmesh_api_key")}),
    ("Hybrid-Script-Generation/opc_engine/features/script_generation/config/model_settings.json", {"OPC_TEXT_API_BASE_URL": ("modelmesh_base_url",), "OPC_TEXT_MODEL": ("script_generation_model", "video_analysis_model"), "OPC_TEXT_API_KEY": ("modelmesh_api_key",)}),
    ("Hybrid-Script-Generation/runtime/model_settings.json", {"OPC_TEXT_API_BASE_URL": ("modelmesh_base_url",), "OPC_TEXT_MODEL": ("script_generation_model", "video_analysis_model"), "OPC_TEXT_API_KEY": ("modelmesh_api_key",)}),
    ("Script-Adaptation/software/Script-Adaptation-app/app_config.json", {"OPC_TEXT_API_BASE_URL": ("ai_model.modelmesh_base_url", "modelmesh_base_url"), "OPC_TEXT_MODEL": ("ai_model.script_adaptation_text_model", "ai_model.video_analysis_model", "script_adaptation_text_model", "video_analysis_model"), "OPC_TEXT_API_KEY": ("ai_model.modelmesh_api_key", "modelmesh_api_key")}),
    ("Script-Adaptation/software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_settings.json", {"OPC_TEXT_API_BASE_URL": ("model.modelmesh_base_url",), "OPC_TEXT_MODEL": ("model.script_adaptation_text_model", "model.video_analysis_model")}),
    ("Script-Adaptation/software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.local.json", {"OPC_TEXT_API_KEY": ("modelmesh_api_key", "gemini_api_key")}),
    ("Hybrid-Script-Adaptation/software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_settings.json", {"OPC_TEXT_API_BASE_URL": ("model.modelmesh_base_url",), "OPC_TEXT_MODEL": ("model.script_adaptation_text_model", "model.video_analysis_model")}),
    ("Hybrid-Script-Adaptation/software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.local.json", {"OPC_TEXT_API_KEY": ("modelmesh_api_key", "gemini_api_key")}),
    ("Hybrid-Script-Adaptation/software/Hybrid-Script-Adaptation-app/app_config.json", {"OPC_TEXT_API_BASE_URL": ("ai_model.modelmesh_base_url", "modelmesh_base_url"), "OPC_TEXT_MODEL": ("ai_model.script_adaptation_text_model", "ai_model.video_analysis_model", "script_adaptation_text_model", "video_analysis_model"), "OPC_TEXT_API_KEY": ("ai_model.modelmesh_api_key", "modelmesh_api_key")}),
    ("Product-Script-Rewrite/agent_config/agent_settings.json", {"OPC_TEXT_API_BASE_URL": ("model.deepseek_base_url",), "OPC_TEXT_MODEL": ("model.deepseek_model",)}),
    ("Product-Script-Rewrite/agent_config/agent_secrets.local.json", {"OPC_TEXT_API_KEY": ("deepseek_api_key",)}),
)


def _normalise_candidate(field: str, value: str) -> str:
    value = value.strip()
    if field in {"GROK_IMAGE_MODEL", "GROK_VIDEO_MODEL"} and ":" in value:
        value = value.split(":", 1)[1].strip()
    if field.endswith("BASE_URL"):
        value = value.rstrip("/")
    return value


def collect_candidates(repo_root: Path) -> tuple[dict[str, list[dict[str, str]]], list[Path]]:
    candidates: dict[str, list[dict[str, str]]] = {key: [] for key in FIELD_LABELS}
    source_files: list[Path] = []

    def add(field: str, value: str, source: str) -> None:
        value = _normalise_candidate(field, value)
        if not value:
            return
        candidate_id = hashlib.sha256(f"{field}\0{source}\0{value}".encode()).hexdigest()[:16]
        candidates[field].append({"id": candidate_id, "source": source, "value": value})

    for relative, mapping in ENV_SOURCES:
        path = repo_root / relative
        if not path.is_file():
            continue
        source_files.append(path)
        data = _read_env(path)
        for field, aliases in mapping.items():
            for alias in aliases:
                value = str(data.get(alias) or "").strip()
                if value:
                    add(field, value, f"{relative} · {alias}")
                    break

    for relative, mapping in JSON_SOURCES:
        path = repo_root / relative
        if not path.is_file():
            continue
        source_files.append(path)
        data = _read_json(path)
        for field, aliases in mapping.items():
            for alias in aliases:
                value = _json_value(data, alias)
                if value:
                    add(field, value, f"{relative} · {alias}")
                    break
    return candidates, source_files


def _write_env_updates(env_file: Path, updates: dict[str, str]) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    remaining = set(updates)
    output: list[str] = []
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else ""
        if key in updates:
            output.append(f"{key}={json.dumps(updates[key], ensure_ascii=False)}")
            remaining.discard(key)
        else:
            output.append(line)
    for key in FIELD_LABELS:
        if key in remaining:
            output.append(f"{key}={json.dumps(updates[key], ensure_ascii=False)}")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, delete=False) as handle:
        handle.write("\n".join(output) + "\n")
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, env_file)


def _backup_sources(repo_root: Path, config_dir: Path, source_files: list[Path], env_file: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = config_dir / "ai-config-backups" / stamp
    for source in source_files:
        relative = source.relative_to(repo_root)
        target = backup_dir / "legacy" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if env_file.is_file():
        target = backup_dir / "global" / ".env"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(env_file, target)
    for path in backup_dir.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
    return str(backup_dir)


def _public_candidate(field: str, candidate: dict[str, str]) -> dict[str, str]:
    if field in SECRET_FIELDS:
        fingerprint = hashlib.sha256(candidate["value"].encode()).hexdigest()[:8]
        display_value = f"已配置 · 指纹 {fingerprint}"
    else:
        display_value = candidate["value"]
    return {"id": candidate["id"], "source": candidate["source"], "display_value": display_value}


def _write_json_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def run_migration(repo_root: Path, config_dir: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    config_dir.mkdir(parents=True, exist_ok=True)
    report_path = config_dir / REPORT_NAME
    private_path = config_dir / PRIVATE_NAME
    marker_path = config_dir / MARKER_NAME
    if marker_path.is_file() or private_path.is_file():
        return load_report(config_dir)

    env_file = config_dir / ".env"
    existing = _read_env(env_file)
    candidates, source_files = collect_candidates(repo_root)
    backup_dir = _backup_sources(repo_root, config_dir, source_files, env_file)
    updates: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    private_conflicts: dict[str, list[dict[str, str]]] = {}
    preserved: list[str] = []

    for field, entries in candidates.items():
        if str(existing.get(field) or "").strip():
            preserved.append(field)
            continue
        unique: dict[str, dict[str, str]] = {}
        for entry in entries:
            unique.setdefault(entry["value"], entry)
        choices = list(unique.values())
        if len(choices) == 1:
            updates[field] = choices[0]["value"]
        elif len(choices) > 1:
            private_conflicts[field] = choices
            conflicts.append(
                {
                    "field": field,
                    "label": FIELD_LABELS[field],
                    "secret": field in SECRET_FIELDS,
                    "candidates": [_public_candidate(field, item) for item in choices],
                }
            )

    if updates:
        _write_env_updates(env_file, updates)
    status = "pending" if conflicts else "complete"
    report = {
        "version": MIGRATION_VERSION,
        "status": status,
        "migrated_fields": list(updates),
        "preserved_fields": preserved,
        "conflicts": conflicts,
        "backup_dir": backup_dir,
        "message": "请选择冲突配置后完成迁移。" if conflicts else "旧 Agent 配置迁移已完成。",
    }
    _write_json_private(report_path, report)
    if conflicts:
        _write_json_private(private_path, {"version": MIGRATION_VERSION, "conflicts": private_conflicts})
    else:
        _write_json_private(marker_path, {"version": MIGRATION_VERSION, "completed_at": datetime.now(timezone.utc).isoformat()})
    return report


def load_report(config_dir: Path) -> dict[str, Any]:
    report = _read_json(config_dir / REPORT_NAME)
    if report:
        return report
    return {"version": MIGRATION_VERSION, "status": "not_run", "migrated_fields": [], "preserved_fields": [], "conflicts": [], "message": "尚未运行旧配置迁移。"}


def resolve_conflicts(config_dir: Path, choices: dict[str, str]) -> dict[str, Any]:
    report_path = config_dir / REPORT_NAME
    private_path = config_dir / PRIVATE_NAME
    report = load_report(config_dir)
    private = _read_json(private_path)
    conflicts = private.get("conflicts") if isinstance(private.get("conflicts"), dict) else {}
    if report.get("status") != "pending" or not conflicts:
        return report
    existing = _read_env(config_dir / ".env")
    pending_fields = [field for field in conflicts if not str(existing.get(field) or "").strip()]
    missing = [field for field in pending_fields if not str(choices.get(field) or "").strip()]
    if missing:
        raise ValueError(f"请先选择 {FIELD_LABELS.get(missing[0], missing[0])}")
    updates: dict[str, str] = {}
    for field in pending_fields:
        entries = conflicts[field]
        selected = next((entry for entry in entries if entry.get("id") == choices[field]), None)
        if not selected:
            raise ValueError(f"{FIELD_LABELS.get(field, field)} 的选择无效")
        updates[field] = selected["value"]
    _write_env_updates(config_dir / ".env", updates)
    report["status"] = "complete"
    report["resolved_fields"] = list(updates)
    report["preserved_fields"] = list(
        dict.fromkeys([*report.get("preserved_fields", []), *sorted(set(conflicts) - set(pending_fields))])
    )
    report["conflicts"] = []
    report["message"] = "旧 Agent 配置冲突已处理，迁移完成。"
    _write_json_private(report_path, report)
    _write_json_private(config_dir / MARKER_NAME, {"version": MIGRATION_VERSION, "completed_at": datetime.now(timezone.utc).isoformat()})
    private_path.unlink(missing_ok=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="一次性迁移旧 Agent API 与模型配置")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run_migration(args.repo_root, args.config_dir)
    print(f"旧 AI 配置迁移状态: {report['status']}；自动迁移 {len(report.get('migrated_fields', []))} 项；冲突 {len(report.get('conflicts', []))} 项")


if __name__ == "__main__":
    main()
