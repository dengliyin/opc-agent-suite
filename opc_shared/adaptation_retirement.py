from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


REGISTRY_RELATIVE_PATH = Path(".opc") / "adaptation_retirements.json"
_WRITE_LOCK = threading.Lock()


def retirement_registry_path(product_script_root: Path) -> Path:
    return product_script_root.expanduser().resolve() / REGISTRY_RELATIVE_PATH


def load_adaptation_retirements(product_script_root: Path) -> dict[str, Any]:
    path = retirement_registry_path(product_script_root)
    if not path.is_file():
        return {"schema_version": 1, "scripts": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "scripts": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("scripts"), dict):
        return {"schema_version": 1, "scripts": {}}
    return payload


def source_script_key(product_script_root: Path, source_script_path: Path) -> str:
    root = product_script_root.expanduser().resolve()
    source = source_script_path.expanduser().resolve()
    try:
        return source.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"产品脚本不属于当前资料库：{source}") from exc


def retired_model_record(
    product_script_root: Path,
    source_script_path: Path,
    model: str,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = registry if registry is not None else load_adaptation_retirements(product_script_root)
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, dict):
        return {}
    script = scripts.get(source_script_key(product_script_root, source_script_path))
    models = script.get("models") if isinstance(script, dict) else None
    record = models.get(str(model or "").strip().lower()) if isinstance(models, dict) else None
    return record if isinstance(record, dict) else {}


def retire_adaptation_model(
    product_script_root: Path,
    source_script_path: Path,
    model: str,
    reason: str,
) -> dict[str, Any]:
    root = product_script_root.expanduser().resolve()
    source = source_script_path.expanduser().resolve()
    key = source_script_key(root, source)
    target_model = str(model or "").strip().lower()
    if not target_model:
        raise ValueError("适配模型不能为空")

    record = {
        "retired_at": time.time(),
        "reason": str(reason or "").strip() or "已淘汰",
    }
    with _WRITE_LOCK:
        payload = load_adaptation_retirements(root)
        scripts = payload.setdefault("scripts", {})
        script = scripts.setdefault(key, {"source_script": source.name, "models": {}})
        script["source_script"] = source.name
        models = script.setdefault("models", {})
        models[target_model] = record

        path = retirement_registry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    return {"key": key, "model": target_model, **record}
