#!/usr/bin/env python3
"""TikTok-style karaoke captions for any video — Whisper + ffmpeg, fully local.

What it does:
  1. Transcribes the video's audio with mlx-whisper (Apple Silicon native).
  2. (Optional) Aligns Whisper's word-level timestamps to a known script so
     the caption text comes from your script verbatim — zero typos.
  3. Splits captions into 1–3 word "chunks" at sentence/comma boundaries.
  4. Writes a karaoke-style ASS subtitle file: each chunk shows together,
     with the currently spoken word highlighted in yellow, others white.
  5. (Optional) Burns a persistent HEADLINE banner on top of the frame.
  6. Renders all of the above onto the video via ffmpeg in a single pass.

Three usage tiers (any combination):

    # 1. Pure auto-caption (no script)
    caption.py my_video.mp4

    # 2. Script-aligned (zero typos, recommended)
    caption.py my_video.mp4 --script-file script.txt

    # 3. Full TikTok package (aligned captions + persistent headline)
    caption.py my_video.mp4 --script-file script.txt --headline "MY HOOK"

Requires:
  - macOS on Apple Silicon (mlx-whisper is M-series only)
  - uv  (`brew install uv`) — the only system dependency

First run downloads (cached forever after, ~1.8 GB total):
  - mlx-whisper Python deps (~200 MB)
  - whisper-medium model (~1.5 GB) — default; small (~480 MB) via --model small
  - static-ffmpeg (~60 MB) — only if your system ffmpeg lacks libass

Output (alongside the input video, or in --out-dir):
  - <stem>.srt              line-level SRT (always written, useful for editing)
  - <stem>.ass              karaoke-style ASS (tiktok mode only)
  - <stem>-captioned.mp4    final video with text burned in
  - <stem>-whisper.json     raw Whisper word-level timestamps (debug)
"""
from __future__ import annotations

import argparse
import os
import urllib.error
import urllib.request
import difflib
import functools
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

SCRIPT_ROOT = Path(__file__).resolve().parent
FONTS_DIR = SCRIPT_ROOT / "fonts"

MODEL_MAP = {
    "tiny":   "mlx-community/whisper-tiny-mlx",
    "base":   "mlx-community/whisper-base-mlx",
    "small":  "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large":  "mlx-community/whisper-large-v3-mlx",
}

# Bundled fonts (see fonts/README.md for licenses)
HEADLINE_FONT_DEFAULT = str(FONTS_DIR / "ArchivoBlack-Regular.ttf")
CAPTION_FONT_NAME_DEFAULT = "Roboto Black"

# Classic-mode SRT styling (only used when --caption-mode classic)
CLASSIC_STYLE_DEFAULT = (
    "FontName=Roboto,FontSize=14,"
    "PrimaryColour=&Hffffff&,OutlineColour=&H000000&,"
    "Bold=1,Outline=1,Shadow=0,"
    "Alignment=2,MarginV=70"
)


# ────────────────────────────────────────────────────────────────────────────
# ffmpeg / ffprobe discovery
# ────────────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    """Return path to an ffmpeg with libass+libfreetype.

    Many Homebrew bottles ship a stripped ffmpeg without libass — the
    subtitles/drawtext filters are then unavailable. Prefer system ffmpeg
    when it has the filters; otherwise fall back to the static-ffmpeg
    PyPI binary (full features, no system changes).
    """
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        try:
            out = subprocess.run([sys_ff, "-filters"], capture_output=True,
                                 text=True, timeout=10).stdout
            if "subtitles " in out and "drawtext " in out:
                return sys_ff
        except (subprocess.SubprocessError, OSError):
            pass
    res = subprocess.run(
        ["uvx", "--from", "static-ffmpeg", "python3", "-c",
         "import static_ffmpeg.run as r; "
         "print(r.get_or_fetch_platform_executables_else_raise()[0])"],
        capture_output=True, text=True, check=True,
    )
    path = res.stdout.strip().splitlines()[-1]
    if not Path(path).exists():
        sys.exit(f"❌ static-ffmpeg binary not found at {path}")
    return path


@functools.lru_cache(maxsize=1)
def ffprobe_bin() -> str:
    ff = Path(ffmpeg_bin())
    candidate = ff.with_name("ffprobe")
    if candidate.exists():
        return str(candidate)
    sys_pb = shutil.which("ffprobe")
    if sys_pb:
        return sys_pb
    sys.exit("❌ ffprobe not found alongside ffmpeg")


def probe_dimensions(video: Path) -> tuple[int, int]:
    res = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(video)],
        capture_output=True, text=True, check=True,
    )
    w, h = res.stdout.strip().split("x")
    return int(w), int(h)


def probe_audio_duration(media: Path) -> float:
    res = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(media)],
        capture_output=True, text=True, check=True,
    )
    return float(res.stdout.strip())


# ────────────────────────────────────────────────────────────────────────────
# Whisper transcription
# ────────────────────────────────────────────────────────────────────────────

def extract_audio(video: Path, out_wav: Path) -> None:
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(video),
           "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
           str(out_wav)]
    subprocess.run(cmd, check=True)


def transcribe_json(audio: Path, out_dir: Path, out_stem: str,
                    model_key: str, language: str,
                    bias_prompt: str | None) -> dict:
    """Run mlx-whisper, return parsed JSON (with word-level timestamps)."""
    model = MODEL_MAP[model_key]
    cmd = [
        "uvx", "--from", "mlx-whisper", "mlx_whisper",
        str(audio),
        "--model", model,
        "--language", language,
        "--output-format", "json",
        "--output-dir", str(out_dir),
        "--output-name", out_stem,
        "--word-timestamps", "True",
    ]
    if bias_prompt:
        cmd += ["--initial-prompt", bias_prompt]
    print(f"   model: {model_key} ({model}) | language: {language}")
    if bias_prompt:
        snippet = bias_prompt[:80].replace("\n", " ")
        print(f"   biasing prompt: {snippet}...")
    subprocess.run(cmd, check=True)
    json_path = out_dir / f"{out_stem}.json"
    return json.loads(json_path.read_text(encoding="utf-8"))


MAX_WORD_DURATION = 1.2  # seconds — anything longer is Whisper attaching silence


def _clamp_word_durations(words: list[dict]) -> list[dict]:
    """Cap word durations to MAX_WORD_DURATION and prevent overlap with next.

    Whisper sometimes attaches long silence to the end of a word, e.g.
    `"have"  0.30 → 6.26` when there's a 5-second silence after "have".
    That makes karaoke highlight hang on one word forever. We clamp the
    effective end to a sane value so the rest stays silent (no caption).
    """
    for i, w in enumerate(words):
        max_end = w["start"] + MAX_WORD_DURATION
        if i + 1 < len(words):
            max_end = min(max_end, words[i + 1]["start"] - 0.05)
        w["end"] = max(w["start"] + 0.1, min(w["end"], max_end))
    return words


def flatten_whisper_words(whisper_json: dict) -> list[dict]:
    words = []
    for seg in whisper_json.get("segments", []):
        for w in seg.get("words", []) or []:
            if w.get("word") and w.get("start") is not None and w.get("end") is not None:
                words.append({"text": w["word"].strip(),
                              "start": float(w["start"]),
                              "end": float(w["end"])})
    return _clamp_word_durations(words)


def looks_broken(words: list[dict], audio_duration: float,
                 expected_word_count: int | None) -> tuple[bool, str]:
    """Heuristic: did Whisper produce a broken transcription?

    Returns (is_broken, reason). mlx-whisper occasionally outputs only a few
    garbage tokens (e.g. ' s s' on a perfectly normal 15-second clip). When
    that happens we want to auto-retry with a beefier model rather than emit
    captions misaligned with the audio.
    """
    if not words:
        return True, "Whisper produced 0 words"
    total_chars = sum(len(normalize_word(w["text"])) for w in words)
    # Very low bar: 1.5 real chars per second of audio. Normal speech is ~10.
    min_chars = 1.5 * audio_duration
    if total_chars < min_chars:
        return True, (f"only {total_chars} real chars in {audio_duration:.1f}s "
                      f"audio (expected ≥ {min_chars:.0f})")
    if expected_word_count and len(words) < 0.3 * expected_word_count:
        return True, (f"only {len(words)} words transcribed vs "
                      f"{expected_word_count} in script (< 30% recall)")
    return False, ""


# ────────────────────────────────────────────────────────────────────────────
# Deepgram cloud fallback (opt-in via DEEPGRAM_API_KEY env var)
# ────────────────────────────────────────────────────────────────────────────

def transcribe_via_deepgram(audio_wav: Path, language: str) -> list[dict]:
    """Cloud fallback for when local Whisper produces garbage.

    Uses Deepgram Nova-3 (different architecture from Whisper, so unlikely
    to fail on the same audio). Returns words in our standard
    `{text, start, end}` format. Returns `[]` if the call fails or the
    DEEPGRAM_API_KEY env var is not set.

    Opt-in: only triggers when DEEPGRAM_API_KEY is set in the environment.
    Cost: ~$0.0043/min of audio (a 15s clip = $0.001).
    Get a key + $200 free credit at https://console.deepgram.com/signup
    """
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        return []
    url = ("https://api.deepgram.com/v1/listen"
           f"?model=nova-3&punctuate=true&smart_format=true&language={language}")
    data = audio_wav.read_bytes()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": f"Token {key}",
                 "Content-Type": "audio/wav"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"   Deepgram request failed: {e}")
        return []
    try:
        alt = result["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError):
        return []
    out = []
    for w in alt.get("words", []) or []:
        text = w.get("punctuated_word") or w.get("word") or ""
        s, e = w.get("start"), w.get("end")
        if text and s is not None and e is not None:
            out.append({"text": text, "start": float(s), "end": float(e)})
    return _clamp_word_durations(out)


def wrap_words_as_whisper_json(words: list[dict]) -> dict:
    """Wrap a flat words list back into a fake whisper-style segments dict.

    Lets the no-script (raw-whisper) downstream path consume cloud output
    without a separate code path.
    """
    if not words:
        return {"segments": []}
    return {"segments": [{
        "text": " ".join(w["text"] for w in words),
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "words": [{"word": w["text"], "start": w["start"], "end": w["end"]}
                  for w in words],
    }]}


# ────────────────────────────────────────────────────────────────────────────
# Script parsing & alignment (forced alignment via difflib)
# ────────────────────────────────────────────────────────────────────────────

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WORD_NORMALIZE_RE = re.compile(r"[^a-zA-Z0-9一-鿿]+")
CHUNK_BREAK_RE = re.compile(r"[,，—–:;]$")


def normalize_word(w: str) -> str:
    return WORD_NORMALIZE_RE.sub("", w).lower()


def _split_keeping_punct(text: str, pattern: str, keep_left: bool = True) -> list[str]:
    """Split text on pattern, preserving the delimiter on the left or right side."""
    parts = re.split(f"({pattern})", text)
    out = []
    i = 0
    while i < len(parts):
        chunk = parts[i].strip()
        if i + 1 < len(parts):
            delim = parts[i + 1].strip()
            if keep_left and delim and delim not in ("—", "–"):
                chunk = (chunk + delim).strip()
            i += 2
        else:
            i += 1
        if chunk:
            out.append(chunk)
    return out


def _greedy_pack(pieces: list[str], max_chars: int) -> list[str]:
    out, buf = [], ""
    for p in pieces:
        cand = (buf + " " + p).strip() if buf else p
        if len(cand) <= max_chars:
            buf = cand
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def parse_script_segments(script_text: str, max_chars: int = 42) -> list[str]:
    """Split a free-form script into subtitle-friendly sentence chunks."""
    out = []
    for line in script_text.splitlines():
        clean = re.sub(r"^\s*\d+[\.\)]\s*", "", line).strip().strip('"').strip("'")
        if not clean:
            continue
        for sent in SENTENCE_SPLIT_RE.split(clean):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= max_chars:
                out.append(sent)
                continue
            dash_parts = _split_keeping_punct(sent, r"\s*[—–]\s*", keep_left=False)
            refined = []
            for part in dash_parts:
                if len(part) <= max_chars:
                    refined.append(part)
                else:
                    refined.extend(_split_keeping_punct(part, r",\s+", keep_left=True))
            out.extend(_greedy_pack(refined, max_chars))
    return out


def align_script_to_whisper(script_segs: list[str],
                            whisper_words: list[dict],
                            audio_duration: float | None = None) -> list[dict]:
    """Use difflib to map each script word -> whisper word timestamp.

    Returns list of {text, start, end, words: [{text, start, end}]}
    aligned with `script_segs`. Per-word timings come from Whisper anchors;
    unmatched words get linearly interpolated timing.

    `audio_duration` (from ffprobe) is used as the upper bound for tail
    interpolation. Without it, we fall back to Whisper's last word end —
    which is wrong when Whisper failed and only emitted garbage at t=1s
    while the real audio is 15s long.
    """
    script_flat: list[tuple[int, str]] = []
    for i, seg in enumerate(script_segs):
        for w in seg.split():
            script_flat.append((i, w))

    script_norm = [normalize_word(w) for _, w in script_flat]
    whisper_norm = [normalize_word(w["text"]) for w in whisper_words]

    sm = difflib.SequenceMatcher(a=script_norm, b=whisper_norm, autojunk=False)
    script_to_whisper: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                script_to_whisper[i1 + k] = j1 + k

    # Use real audio duration if available — Whisper's last word end can
    # be wildly wrong when the model failed (e.g. emitted just '!' at 1.5s
    # on a 15s clip). Falling back to that bad value crammed all captions
    # into the first 1.5 seconds.
    whisper_end = whisper_words[-1]["end"] if whisper_words else 0.0
    audio_end = max(audio_duration or 0.0, whisper_end)
    n_script = len(script_flat)

    # Forward-fill missing timings via linear interpolation
    script_word_times: list[tuple[float, float] | None] = [None] * n_script
    for k in range(n_script):
        if k in script_to_whisper:
            w = whisper_words[script_to_whisper[k]]
            script_word_times[k] = (float(w["start"]), float(w["end"]))

    last_known_i, last_known_end = -1, 0.0
    for k in range(n_script):
        if script_word_times[k] is not None:
            if k > last_known_i + 1:
                next_start = script_word_times[k][0]
                n_gap = k - last_known_i - 1
                step = (next_start - last_known_end) / (n_gap + 1)
                for gi in range(last_known_i + 1, k):
                    gs = last_known_end + step * (gi - last_known_i)
                    script_word_times[gi] = (gs, gs + step * 0.9)
            last_known_i = k
            last_known_end = script_word_times[k][1]

    if last_known_i < n_script - 1:
        n_gap = n_script - 1 - last_known_i
        step = (audio_end - last_known_end) / max(1, n_gap)
        for gi in range(last_known_i + 1, n_script):
            gs = last_known_end + step * (gi - last_known_i - 1)
            script_word_times[gi] = (gs, gs + step * 0.9)

    for k in range(n_script):
        if script_word_times[k] is None:
            ratio = k / max(1, n_script)
            script_word_times[k] = (ratio * audio_end, ratio * audio_end + 0.3)

    seg_to_idxs: list[list[int]] = [[] for _ in script_segs]
    for k, (seg_i, _) in enumerate(script_flat):
        seg_to_idxs[seg_i].append(k)

    # If Whisper completely failed (no anchors at all), don't skip every
    # segment — fall back to using the interpolated (evenly-distributed)
    # timing for the WHOLE script. Captions won't sync perfectly to audio
    # but at least the user sees something instead of a blank video.
    fully_unmatched = (len(script_to_whisper) == 0)

    out, last_end = [], 0.0
    skipped_segs: list[str] = []
    for seg_idx, seg_text in enumerate(script_segs):
        idxs = seg_to_idxs[seg_idx]
        n_matched = sum(1 for k in idxs if k in script_to_whisper)
        # Skip segments Whisper missed — UNLESS Whisper missed everything,
        # in which case we trust the script and distribute it evenly across
        # the audio duration (computed earlier via tail-fill interpolation).
        if n_matched == 0 and not fully_unmatched:
            skipped_segs.append(seg_text)
            out.append({"text": seg_text, "start": 0, "end": 0,
                        "words": [], "skipped": True})
            continue
        words = []
        for k in idxs:
            ws, we = script_word_times[k]  # type: ignore[misc]
            ws = max(ws, last_end)
            if we <= ws:
                we = ws + 0.2
            words.append({"text": script_flat[k][1], "start": ws, "end": we})
            last_end = we
        out.append({"text": seg_text, "start": words[0]["start"],
                    "end": words[-1]["end"], "words": words})

    if fully_unmatched:
        print(f"⚠️  Whisper heard NO recognizable words — captions are "
              f"distributed evenly across audio (timing won't match speech)")
    elif skipped_segs:
        print(f"⚠️  {len(skipped_segs)} script segment(s) not heard in audio — skipped:")
        for s in skipped_segs:
            print(f"     · {s}")
    return out


def segments_from_raw_whisper(whisper_json: dict) -> list[dict]:
    """When no script is provided, build segments straight from Whisper output."""
    out = []
    for seg in whisper_json.get("segments", []):
        words = []
        for w in seg.get("words", []) or []:
            if w.get("word") and w.get("start") is not None and w.get("end") is not None:
                words.append({"text": w["word"].strip(),
                              "start": float(w["start"]),
                              "end": float(w["end"])})
        words = _clamp_word_durations(words)
        out.append({"text": seg.get("text", "").strip(),
                    "start": float(seg.get("start", 0)),
                    "end": float(seg.get("end", 0)),
                    "words": words})
    return out


# ────────────────────────────────────────────────────────────────────────────
# Subtitle file writers (SRT + ASS karaoke)
# ────────────────────────────────────────────────────────────────────────────

def format_srt_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    ms = min(999, int(round((t - int(t)) * 1000)))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_ass_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_srt(segments: list[dict], out: Path) -> None:
    lines = []
    idx = 0
    for seg in segments:
        # Skip segments with no audio match (script said but model never spoke)
        if seg.get("skipped") or not seg.get("words"):
            continue
        idx += 1
        lines.append(str(idx))
        lines.append(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def chunk_for_tiktok(segments: list[dict], max_words: int = 3) -> list[list[dict]]:
    """Split segments into 1-to-max_words karaoke chunks at soft punctuation."""
    chunks: list[list[dict]] = []
    for seg in segments:
        current: list[dict] = []
        for word in seg["words"]:
            current.append(word)
            tail = word["text"].rstrip("\"'")
            soft_break = bool(CHUNK_BREAK_RE.search(tail))
            if soft_break or len(current) >= max_words:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)
    return chunks


def write_ass_tiktok(chunks: list[list[dict]], out: Path,
                     video_w: int, video_h: int,
                     uppercase: bool = True,
                     font_name: str = CAPTION_FONT_NAME_DEFAULT,
                     fontsize_ratio: float = 0.04,
                     highlight_bgr: str = "&H0000FFFF&",
                     position_y_ratio: float = 0.58) -> None:
    """Write TikTok-style karaoke ASS captions with per-word color highlighting.

    For each chunk we emit N Dialogue events (N = words in chunk). Each event
    shows the full chunk with one word colored yellow — the one currently
    being spoken. As Whisper's word timestamps advance, the highlight moves.
    """
    font_size = max(16, int(video_h * fontsize_ratio))
    position_x = video_w // 2
    position_y = int(video_h * position_y_ratio)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_w}\n"
        f"PlayResY: {video_h}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,"
        "100,100,0,0,"
        "1,4,1,"
        "5,40,40,0,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    events: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        words_disp = [(w["text"].upper() if uppercase else w["text"]) for w in chunk]
        for i, word in enumerate(chunk):
            evt_start = word["start"]
            evt_end = chunk[i + 1]["start"] if i + 1 < len(chunk) else word["end"]
            if evt_end <= evt_start:
                evt_end = evt_start + 0.15
            parts = []
            for j, txt in enumerate(words_disp):
                if j == i:
                    parts.append(f"{{\\c{highlight_bgr}}}{txt}{{\\c&H00FFFFFF&}}")
                else:
                    parts.append(txt)
            events.append(
                f"Dialogue: 0,{format_ass_time(evt_start)},"
                f"{format_ass_time(evt_end)},Default,,0,0,0,,"
                f"{{\\an5\\pos({position_x},{position_y})}}{' '.join(parts)}"
            )

    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


# ────────────────────────────────────────────────────────────────────────────
# Headline wrapping (open-source font, multi-line, auto-fit)
# ────────────────────────────────────────────────────────────────────────────

def wrap_headline(text: str, max_chars_per_line: int) -> list[str]:
    """Wrap headline into balanced lines, preferring natural separators."""
    text = text.strip()
    if len(text) <= max_chars_per_line:
        return [text]

    for sep in [r" · ", r" — ", r" – ", r" / ", r" \| "]:
        parts = [p.strip() for p in re.split(sep, text) if p.strip()]
        if len(parts) >= 2 and all(len(p) <= max_chars_per_line for p in parts):
            return parts

    words = text.split()
    n_lines_target = max(2, (len(text) + max_chars_per_line - 1) // max_chars_per_line)
    target_chars = len(text) / n_lines_target
    lines, buf = [], ""
    for w in words:
        cand = (buf + " " + w).strip() if buf else w
        if not buf or len(cand) <= max(max_chars_per_line, int(target_chars * 1.15)):
            buf = cand
            if len(buf) >= target_chars * 0.9 and len(lines) < n_lines_target - 1:
                lines.append(buf)
                buf = ""
        else:
            if buf:
                lines.append(buf)
            buf = w
    if buf:
        lines.append(buf)
    return lines


# ────────────────────────────────────────────────────────────────────────────
# Burn-in: drawbox + drawtext (headline) + subtitles (captions)
# ────────────────────────────────────────────────────────────────────────────

def burn_overlay(video: Path, subtitle: Path, out: Path,
                 sub_style: str | None,
                 headline: str | None, headline_font: str) -> None:
    """One-pass ffmpeg burn: optional headline pill + subtitle file (SRT/ASS)."""
    is_ass = subtitle.suffix.lower() == ".ass"
    sub_local = "sub.ass" if is_ass else "sub.srt"

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        safe_video = td_path / "in.mp4"
        safe_sub = td_path / sub_local
        shutil.copy(video, safe_video)
        shutil.copy(subtitle, safe_sub)
        # Stage bundled fonts so libass can resolve FontName=… via fontsdir=.
        if FONTS_DIR.is_dir():
            for f in FONTS_DIR.glob("*.ttf"):
                shutil.copy(f, td_path / f.name)
        safe_out = td_path / "out.mp4"

        filters: list[str] = []

        if headline:
            video_w, video_h = probe_dimensions(video)

            if "Condensed" in headline_font:
                char_width_ratio = 0.42
            elif "Black" in headline_font or "Heavy" in headline_font:
                char_width_ratio = 0.62
            else:
                char_width_ratio = 0.55

            pill_w_px = video_w * 0.88
            text_len = len(headline)
            best_lines: list[str] = [headline]
            best_font_size = 0
            for n_lines in range(1, 4):
                approx_chars_per_line = max(
                    1, text_len // n_lines + (1 if text_len % n_lines else 0)
                )
                size_by_width = int(pill_w_px / (approx_chars_per_line * char_width_ratio))
                size_by_height_per_line = int(video_h / (12 * n_lines + 4))
                candidate_size = min(size_by_width, size_by_height_per_line)
                if candidate_size > best_font_size:
                    best_font_size = candidate_size
                    best_lines = wrap_headline(headline, approx_chars_per_line)
                    actual_max = max(len(l) for l in best_lines)
                    actual_size = int(pill_w_px / (actual_max * char_width_ratio))
                    best_font_size = min(actual_size, size_by_height_per_line)

            font_size = max(16, best_font_size)
            n_lines = len(best_lines)

            head_path = td_path / "head.txt"
            head_path.write_text("\n".join(best_lines), encoding="utf-8")

            line_h_px = int(font_size * 1.15)
            pill_h_px = n_lines * line_h_px + int(font_size * 0.55)
            pill_top_px = int(video_h * 0.10)

            print(f"   headline: {' / '.join(best_lines)}  ({n_lines} line(s), {font_size}px)")

            filters.append(
                f"drawbox=x=iw*0.06:y={pill_top_px}:w=iw*0.88:h={pill_h_px}:"
                "color=black@0.72:t=fill"
            )
            filters.append(
                f"drawtext=fontfile={headline_font}:textfile=head.txt:"
                f"fontsize={font_size}:fontcolor=white:line_spacing=4:"
                f"borderw=1:bordercolor=black@0.6:"
                f"x=(w-text_w)/2:y={pill_top_px}+({pill_h_px}-text_h)/2"
            )

        if is_ass:
            filters.append(f"subtitles={sub_local}:fontsdir=.")
        else:
            style = sub_style or CLASSIC_STYLE_DEFAULT
            style_escaped = style.replace(",", r"\,")
            filters.append(
                f"subtitles={sub_local}:fontsdir=.:force_style={style_escaped}"
            )

        cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
               "-i", str(safe_video),
               "-vf", ",".join(filters),
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "copy",
               str(safe_out)]
        subprocess.run(cmd, check=True, cwd=td)
        shutil.move(safe_out, out)


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("video", help="path to input video file (mp4, mov, etc.)")
    ap.add_argument("--script-file", default=None,
                    help="path to a .txt/.md file containing the spoken script. "
                         "When provided, captions are forced-aligned to the "
                         "script (text 100% accurate, timing from Whisper).")
    ap.add_argument("--script", default=None,
                    help="inline script text (alternative to --script-file)")
    ap.add_argument("--headline", default=None,
                    help="persistent top-banner text (e.g. 'BLACK FRIDAY · 50%% OFF')")
    ap.add_argument("--headline-font", default=HEADLINE_FONT_DEFAULT,
                    help=f"TTF file for headline (default: bundled Archivo Black)")
    ap.add_argument("--caption-mode", default="tiktok",
                    choices=["tiktok", "classic"],
                    help="tiktok = karaoke ASS with per-word yellow highlight (default); "
                         "classic = static line-level SRT")
    ap.add_argument("--max-words-per-chunk", type=int, default=3,
                    help="tiktok: max words shown together per chunk (default 3)")
    ap.add_argument("--no-uppercase", action="store_true",
                    help="tiktok: keep original casing instead of forcing ALL CAPS")
    ap.add_argument("--max-chars-per-line", type=int, default=42,
                    help="when splitting script: soft cap per segment (default 42)")
    ap.add_argument("--model", default="medium",
                    choices=list(MODEL_MAP.keys()),
                    help="whisper model size (default: medium — more robust than "
                         "small; pass --model small for faster startup if you "
                         "don't mind the occasional retry)")
    ap.add_argument("--prefer-local", action="store_true",
                    help="even with DEEPGRAM_API_KEY set, try local mlx-whisper "
                         "first and only use Deepgram as a fallback. By default, "
                         "when the env var is set, Deepgram is tried first because "
                         "it's faster (~2s vs ~10s) and more reliable.")
    ap.add_argument("--language", default="en",
                    help="audio language code (default: en)")
    ap.add_argument("--style", default=None,
                    help="(classic mode only) ffmpeg ASS force_style string")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: same as input video)")
    ap.add_argument("--out-name", default=None,
                    help="output video filename (default: <stem>-captioned.mp4)")
    ap.add_argument("--srt-only", action="store_true",
                    help="generate subtitle files but skip burning into video")
    args = ap.parse_args()

    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        sys.exit(f"❌ video not found: {video}")

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else video.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = video.stem
    srt_path = out_dir / f"{stem}.srt"
    ass_path = out_dir / f"{stem}.ass"
    out_video = out_dir / (args.out_name or f"{stem}-captioned.mp4")

    # Resolve script source
    bias: str | None = None
    if args.script:
        bias = args.script.strip()
    elif args.script_file:
        sf = Path(args.script_file).expanduser().resolve()
        if not sf.exists():
            sys.exit(f"❌ script file not found: {sf}")
        bias = sf.read_text(encoding="utf-8").strip()

    print(f"📹 video:  {video}")
    print(f"📂 outdir: {out_dir}")
    if args.headline:
        print(f"🏷  headline: {args.headline}")
    if bias:
        print(f"📜 script-aligned mode ({len(bias)} chars)")
    else:
        print(f"📜 raw-Whisper mode (no script)")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = Path(f.name)
    try:
        print("🎵 extracting audio...")
        extract_audio(video, tmp_wav)

        audio_dur = probe_audio_duration(tmp_wav)
        expected_words = len(bias.split()) if bias else None
        has_deepgram = bool(os.environ.get("DEEPGRAM_API_KEY"))

        # Build the recovery chain. Each entry is (label, callable returning
        # (words, whisper_json_dict)). We iterate until one returns non-broken
        # output, OR we exhaust everything and fall through to even-distribute.
        #
        # When DEEPGRAM_API_KEY is set, Deepgram goes FIRST by default because
        # it's empirically faster (~2s vs ~10s) and more accurate than local
        # mlx-whisper. Use --prefer-local to flip this to "local first, cloud
        # fallback" (the previous default).
        def _local(model: str):
            def _run():
                # mlx-whisper strips chars after the first "." in --output-name
                # → use a hyphen-separated stem
                wj = transcribe_json(tmp_wav, out_dir, f"{stem}-whisper",
                                     model, args.language, bias)
                return flatten_whisper_words(wj), wj
            return _run

        def _cloud():
            cw = transcribe_via_deepgram(tmp_wav, args.language)
            return cw, wrap_words_as_whisper_json(cw)

        chain: list[tuple[str, callable]] = []
        if has_deepgram and not args.prefer_local:
            chain.append(("Deepgram Nova-3 (cloud)", _cloud))
            chain.append((f"local Whisper medium", _local("medium")))
            chain.append((f"local Whisper large", _local("large")))
        else:
            chain.append((f"local Whisper {args.model}", _local(args.model)))
            if args.model in ("tiny", "base", "small"):
                chain.append(("local Whisper medium", _local("medium")))
            if has_deepgram:  # --prefer-local set: cloud as mid-step fallback
                chain.append(("Deepgram Nova-3 (cloud)", _cloud))
            if args.model != "large" and "large" not in (c[0] for c in chain):
                chain.append(("local Whisper large", _local("large")))

        print(f"🗣  transcribing...")
        words: list[dict] = []
        whisper_json: dict = {"segments": []}
        broken, reason = True, "no backend run yet"
        tried_labels: list[str] = []
        for label, runner in chain:
            print(f"   → {label}")
            tried_labels.append(label)
            try:
                words, whisper_json = runner()
            except Exception as e:
                print(f"     {label} raised: {e}")
                continue
            broken, reason = looks_broken(words, audio_dur, expected_words)
            if not broken:
                print(f"     ✅ {len(words)} words")
                break
            print(f"     ⚠️  broken — {reason}")

        if broken:
            print(f"⚠️  every backend tried ({' → '.join(tried_labels)}) "
                  f"produced broken output")
            if not has_deepgram:
                print(f"   tip: set DEEPGRAM_API_KEY env var to enable cloud fallback")
                print(f"        (free $200 credit at https://console.deepgram.com/signup)")
            print(f"   falling back to even script timing across {audio_dur:.1f}s audio")

        if bias:
            script_segs = parse_script_segments(bias, args.max_chars_per_line)
            print(f"   aligned: {len(script_segs)} segments ↔ {len(words)} whisper words")
            segments = align_script_to_whisper(script_segs, words, audio_dur)
        else:
            segments = segments_from_raw_whisper(whisper_json)
            print(f"   raw segments: {len(segments)}")

        write_srt(segments, srt_path)
        print(f"✅ SRT: {srt_path}")

        if args.caption_mode == "tiktok":
            video_w, video_h = probe_dimensions(video)
            chunks = chunk_for_tiktok(segments, max_words=args.max_words_per_chunk)
            write_ass_tiktok(chunks, ass_path, video_w, video_h,
                             uppercase=not args.no_uppercase)
            print(f"✅ ASS: {ass_path}  ({len(chunks)} chunks)")

        if args.srt_only:
            return 0

        sub_for_burn = ass_path if args.caption_mode == "tiktok" else srt_path
        print(f"🔥 burning {'headline + ' if args.headline else ''}"
              f"captions ({args.caption_mode})...")
        burn_overlay(video, sub_for_burn, out_video, args.style,
                     args.headline, args.headline_font)
        print(f"✅ output: {out_video}")
    finally:
        tmp_wav.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
