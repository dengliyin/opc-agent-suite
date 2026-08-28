from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
ASSEMBLY_RUNTIME = WORKSPACE_ROOT / "Video-Generation" / "assembly" / "runtime"
DEFAULT_SPEED = 1.2
SUPPORTED_VOICES = (
    {"id": "ef_dora", "name": "Dora · 女声", "language": "es", "markets": ["ES"]},
    {"id": "bf_emma", "name": "Emma · 女声", "language": "en-gb", "markets": ["IE"]},
    {"id": "bm_george", "name": "George · 男声", "language": "en-gb", "markets": ["IE"]},
    {"id": "if_sara", "name": "Sara · 女声", "language": "it", "markets": ["IT"]},
    {"id": "im_nicola", "name": "Nicola · 男声", "language": "it", "markets": ["IT"]},
    {"id": "af_nova", "name": "Nova · 女声", "language": "en-us", "markets": ["US", "PH"]},
    {"id": "am_michael", "name": "Michael · 男声", "language": "en-us", "markets": ["US", "PH"]},
)


@dataclass(frozen=True)
class AudioPaths:
    vault_root: Path
    copy_root: Path
    audio_root: Path


@dataclass(frozen=True)
class AudioEntry:
    id: str
    market: str
    country: str
    title: str
    filename: str
    text: str
    output_path: str
    generated: bool


def detect_vault_root() -> Path:
    configured = os.environ.get("OPC_VAULT_ROOT", "").strip()
    if not configured:
        raise RuntimeError("OPC_VAULT_ROOT 未配置，拒绝回退到旧资料库")
    vault = Path(configured).expanduser().resolve()
    if not vault.is_dir():
        raise RuntimeError(f"OPC_VAULT_ROOT 不存在或外接盘未挂载：{vault}")
    return vault


def audio_paths() -> AudioPaths:
    vault = detect_vault_root()
    hybrid = vault / "wiki/视频/AI实拍混剪"
    return AudioPaths(
        vault_root=vault,
        copy_root=Path(
            os.environ.get("HYBRID_AUDIO_COPY_ROOT", hybrid / "06音频文案")
        ).expanduser().resolve(),
        audio_root=Path(
            os.environ.get("HYBRID_PRODUCT_AUDIO_ROOT", hybrid / "06音频文件")
        ).expanduser().resolve(),
    )


def product_name(path: Path, text: str) -> str:
    front_matter = re.search(r'(?m)^product:\s*["\']?([^"\'\n]+)', text)
    if front_matter:
        value = front_matter.group(1).strip()
        if value:
            return value
    name = path.stem
    for suffix in ("-原创文案", "-逐字稿", "原创音频文案", "音频逐字稿"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip(" -·")


def _country_header(line: str) -> tuple[str, str] | None:
    match = re.match(r"^##\s+(.+?)\s*(?:\(([A-Z]{2})\)|\b([A-Z]{2}))\s*$", line)
    if not match:
        return None
    return match.group(1).strip(), match.group(2) or match.group(3)


def _entry_text(section: str) -> str:
    marker = re.search(r"(?m)^音频文案[：:]\s*$", section)
    if not marker:
        return ""
    body = section[marker.end() :]
    body = re.split(r"(?m)^中文校对[：:]\s*$", body, maxsplit=1)[0]
    lines = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(">"):
            value = stripped[1:].strip()
            if value:
                lines.append(value)
        elif stripped and lines:
            break
    return " ".join(lines).strip()


def parse_document(path: Path, paths: AudioPaths | None = None) -> dict:
    paths = paths or audio_paths()
    text = path.read_text(encoding="utf-8")
    product = product_name(path, text)
    headings = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", text))
    countries: list[tuple[int, str, str]] = []
    for match in re.finditer(r"(?m)^##\s+.+$", text):
        parsed = _country_header(match.group(0))
        if parsed:
            countries.append((match.start(), parsed[0], parsed[1]))

    entries = []
    for index, heading in enumerate(headings):
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end() : section_end]
        filename_match = re.search(
            r"建议音频文件名[：:]\s*`?([^`\n]+\.(?:m4a|mp3|wav))`?",
            section,
            re.IGNORECASE,
        )
        speech = _entry_text(section)
        if not filename_match or not speech:
            continue
        active_country = next(
            ((country, market) for position, country, market in reversed(countries) if position < heading.start()),
            ("未标注", ""),
        )
        heading_text = heading.group(1).strip()
        entry_id = re.split(r"[｜|.、\s]", heading_text, maxsplit=1)[0].strip()
        market = active_country[1] or entry_id.split("-", 1)[0].upper()
        title_parts = re.split(r"[｜|]", heading_text, maxsplit=1)
        title = title_parts[1].strip() if len(title_parts) > 1 else heading_text
        filename = Path(filename_match.group(1).strip()).name
        output_path = paths.audio_root / product / filename
        entries.append(
            AudioEntry(
                id=entry_id,
                market=market,
                country=active_country[0],
                title=title,
                filename=filename,
                text=speech,
                output_path=str(output_path),
                generated=output_path.is_file(),
            )
        )

    return {
        "id": path.name,
        "name": path.name,
        "product": product,
        "path": str(path),
        "entries": [asdict(entry) for entry in entries],
    }


def scan_library(paths: AudioPaths | None = None) -> dict:
    paths = paths or audio_paths()
    documents = []
    if paths.copy_root.is_dir():
        for path in sorted(paths.copy_root.glob("*.md"), key=lambda value: value.name.lower()):
            document = parse_document(path, paths)
            if document["entries"]:
                documents.append(document)
    return {
        "copy_root": str(paths.copy_root),
        "audio_root": str(paths.audio_root),
        "speed": DEFAULT_SPEED,
        "voices": list(SUPPORTED_VOICES),
        "documents": documents,
    }


def find_document(document_id: str, paths: AudioPaths | None = None) -> dict:
    library = scan_library(paths)
    document = next((item for item in library["documents"] if item["id"] == document_id), None)
    if not document:
        raise ValueError("未找到所选音频文案")
    return document


def runtime_paths() -> tuple[Path, Path, Path]:
    node_name = "node.exe" if os.name == "nt" else "node"
    ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    node = Path(os.environ.get("HYPERFRAMES_NODE_BIN", ASSEMBLY_RUNTIME / "bin" / node_name)).expanduser()
    cli = Path(
        os.environ.get(
            "HYPERFRAMES_CLI_PATH",
            ASSEMBLY_RUNTIME / "hyperframes/package/dist/cli.js",
        )
    ).expanduser()
    ffmpeg = Path(os.environ.get("FFMPEG_BIN", ASSEMBLY_RUNTIME / "bin" / ffmpeg_name)).expanduser()
    if not node.is_file():
        raise RuntimeError(f"未找到 Node.js：{node}")
    if not cli.is_file():
        raise RuntimeError(f"未找到 HyperFrames CLI：{cli}")
    if not ffmpeg.is_file():
        direct = shutil.which("ffmpeg")
        if not direct:
            raise RuntimeError(f"未找到 FFmpeg：{ffmpeg}")
        ffmpeg = Path(direct)
    return node, cli, ffmpeg


def voice_config(voice_id: str, market: str) -> dict:
    voice = next((item for item in SUPPORTED_VOICES if item["id"] == voice_id), None)
    if not voice:
        raise ValueError("不支持所选声音")
    if market not in voice["markets"]:
        raise ValueError(f"{market} 文案与所选声音语言不匹配")
    return voice


def run_checked(command: list[str], *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=3600)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(detail)


def generate_entries(
    document_id: str,
    entry_ids: list[str],
    voice_id: str,
    *,
    overwrite: bool = False,
    paths: AudioPaths | None = None,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    paths = paths or audio_paths()
    document = find_document(document_id, paths)
    selected = [entry for entry in document["entries"] if entry["id"] in entry_ids]
    if not selected:
        raise ValueError("请至少选择一条可生成的音频文案")
    missing = set(entry_ids) - {entry["id"] for entry in selected}
    if missing:
        raise ValueError(f"音频文案不存在：{sorted(missing)[0]}")

    node, cli, ffmpeg = runtime_paths()
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise RuntimeError("配音智能体虚拟环境不存在")
    outputs = []
    for index, entry in enumerate(selected, start=1):
        voice = voice_config(voice_id, entry["market"])
        output = Path(entry["output_path"])
        if output.is_file() and not overwrite:
            if log:
                log(f"[{index}/{len(selected)}] 已存在，跳过：{output.name}")
            outputs.append({"path": str(output), "status": "skipped", "entry": entry["id"]})
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        if log:
            log(f"[{index}/{len(selected)}] 正在配音：{entry['id']} · {entry['title']}")
        with tempfile.TemporaryDirectory(prefix="hybrid-audio-") as temporary:
            temporary_root = Path(temporary)
            source_text = temporary_root / "script.txt"
            wave = temporary_root / "speech.wav"
            encoded = temporary_root / "speech.m4a"
            source_text.write_text(entry["text"] + "\n", encoding="utf-8")
            env = os.environ.copy()
            env["HYPERFRAMES_PYTHON"] = str(python)
            run_checked(
                [
                    str(node),
                    str(cli),
                    "tts",
                    str(source_text),
                    "--voice",
                    voice["id"],
                    "--lang",
                    voice["language"],
                    "--speed",
                    str(DEFAULT_SPEED),
                    "--output",
                    str(wave),
                    "--json",
                ],
                env=env,
            )
            run_checked(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wave),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    str(encoded),
                ]
            )
            shutil.move(encoded, output)
        if log:
            log(f"[{index}/{len(selected)}] 已保存：{output}")
        outputs.append({"path": str(output), "status": "generated", "entry": entry["id"]})
    return outputs
