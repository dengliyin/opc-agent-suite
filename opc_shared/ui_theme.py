from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from pathlib import Path


THEME_PATH = Path(__file__).resolve().parent / "ui" / "opc-theme.css"


def theme_css() -> str:
    return THEME_PATH.read_text(encoding="utf-8")


def send_theme_css(handler: BaseHTTPRequestHandler) -> None:
    body = THEME_PATH.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/css; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
