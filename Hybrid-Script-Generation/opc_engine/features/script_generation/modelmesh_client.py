#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def get_api_key(config: dict) -> str:
    return (
        os.environ.get("MODELMESH_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or config.get("modelmesh_api_key")
        or config.get("gemini_api_key")
        or ""
    )


def extract_text(response: dict) -> str:
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


def post_json(url: str, headers: dict, payload: dict, timeout: int):
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


def endpoint_variants(base_url: str, model: str) -> list[tuple[str, str]]:
    base_url = base_url.rstrip("/")
    encoded_model = urllib.parse.quote(model, safe="")
    raw_model = model.strip("/")
    return [
        (f"{base_url}/v1beta/models/{encoded_model}:generateContent", "encoded-model"),
        (f"{base_url}/v1beta/models/{raw_model}:generateContent", "raw-model"),
    ]
