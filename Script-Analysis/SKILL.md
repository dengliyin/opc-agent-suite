---
name: Script-Analysis
description: Self-contained short-video teardown agent for TikTok, Reels, and cross-border ecommerce videos. Use when Codex needs to analyze a user-provided MP4/MOV video with Gemini 3.0, using only this skill folder's local prompt, knowledge base, API settings, output contract, and scripts, then produce structured teardown Markdown for script generation.
---

# Video Teardown Agent

## Overview

Use this skill as a standalone video teardown agent. All configuration must live inside the `Script-Analysis` folder in the suite:

```text
opc-agent-suite/Script-Analysis/
```

Do not read prompt, knowledge-base, API, model, or output-contract configuration from OPC project folders, WeChat temp folders, or any other external project. The only normal external input is the user-provided video file or video directory.

## Folder Contract

```text
config/
  settings.json                    # shared API endpoint/model/runtime config
  settings.local.json              # local private API key only
  settings.local.example.json      # API key template
  video_teardown_prompt.md         # video teardown prompt
  hot_content_knowledge_base.md    # teardown knowledge base
references/
  teardown-output-contract.md      # required output format and acceptance checklist
scripts/
  analyze_video.py                 # standalone Gemini video teardown runner
  web_app.py                       # local visual web interface
web/
  index.html                       # browser UI
  app.css
  app.js
inputs/
  <uploaded_or_imported_videos>    # uploaded videos and copied local-path videos
outputs/
  <run_timestamp>/                 # default teardown outputs
```

`settings.local.json` is private and stores only the API key. Do not print its API key. Shared Base URL, model, and runtime settings belong in tracked `settings.json`.

## Operating Principles

- Use only files under the skill folder for configuration.
- Copy any user-provided prompt or knowledge-base file into `config/` before using it; never point config at a temporary external path.
- Keep the workflow narrow: video in, structured teardown Markdown out.
- Do not invent transcript, timecodes, price claims, performance data, or product claims.
- Use `[product]` as the generic product token unless the user explicitly wants product-specific wording.
- Verify with concrete artifacts: Markdown teardown, raw JSON response, and run summary.

## Running A Teardown

For the visual interface:

```bash
.venv/bin/python scripts/web_app.py --port 9992
```

Then open:

```text
http://127.0.0.1:9992
```

For one video:

```bash
.venv/bin/python scripts/analyze_video.py /absolute/path/to/video.mp4
```

In the web UI, any local path outside the skill folder must be copied into `inputs/` before the runner starts. Generated teardown files must stay under `outputs/`.

For a folder:

```bash
.venv/bin/python scripts/analyze_video.py /absolute/path/to/video_folder
```

The runner reads:

```text
config/settings.json
config/settings.local.json
config/video_teardown_prompt.md
config/hot_content_knowledge_base.md
references/teardown-output-contract.md
```

The default model is `gemini-3.5-flash`, configured in tracked `config/settings.json`.

The web UI must still call `scripts/analyze_video.py`; do not duplicate model-call logic in browser JavaScript.

## Config Rules

Before running, confirm internally that these files exist:

- `config/settings.json`
- `config/video_teardown_prompt.md`
- `config/hot_content_knowledge_base.md`
- `references/teardown-output-contract.md`
- `scripts/analyze_video.py`

If `settings.local.json` is missing, create it from `config/settings.local.example.json` and fill only the API key. Keep shared non-secret settings in `config/settings.json` so they synchronize through Git.

If the user says “this file is the prompt” or “this file is the knowledge base,” copy that file into the matching `config/` filename:

```text
config/video_teardown_prompt.md
config/hot_content_knowledge_base.md
```

If two provided files are identical or appear mislabeled, do not overwrite the prompt blindly. Tell the user what was detected and preserve the existing prompt unless they explicitly confirm replacement.

## Output Contract

When producing or evaluating teardown Markdown, use `references/teardown-output-contract.md`.

Minimum expected sections:

- Source summary.
- Full transcript and translation.
- Shot-by-shot table cut by actual shot changes.
- Conversion logic: audience, hook, pain/desire, trust, proof, offer, CTA, retention.
- Material framework match or new material type.
- Reusable SOP with separate visual and audio/copy tracks.
- Downstream notes for script generation.

## Output Paths

Default outputs stay inside this skill:

```text
outputs/<YYYYMMDD_HHMMSS>/
  <video_stem>_teardown.md
  <video_stem>_teardown.raw.json
  run_summary.json
```

If the user asks for a summary after a run, report the output paths, success/failure count, and high-level findings. Do not paste the full teardown unless requested.

## Verification

After running:

- Confirm each Markdown file exists and is non-empty.
- Confirm each raw JSON file exists.
- Confirm `run_summary.json` exists.
- Spot-check that the Markdown includes transcript, shot table, conversion logic, framework/SOP sections.

Classify failures as: missing config, missing API key, nonexistent input path, unsupported file type, model/API error, or output quality issue.
