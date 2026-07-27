---
name: video-assembly-hd
description: Completely offline local agent that scans pending product-video clips, assembles selected clips after confirmation, validates finished MP4s, and cleans source media only after a separate explicit confirmation.
---

# 片段合成智能体

The standalone application lives in this folder and runs without network access.

## Web UI

Start the app:

```bash
bash scripts/start_web.sh
```

Open:

```text
http://127.0.0.1:9998/
```

The UI workflow is fixed:

1. Scan the pending directory.
2. Review and select items in the pending queue.
3. Confirm again in the confirmation dialog.
4. Run the local assembly job.
5. Verify the refreshed scan has no remaining selected items.
6. Review assembled items under "已有成品".
7. Clean source media only when the user explicitly selects items and confirms the finished videos are usable.

The confirmation dialog includes only the selected caption mode and assembly summary. The app does not provide text stickers or text-preset libraries.

Caption rules:

- expose exactly two choices: `none` (不生成字幕) and `karaoke` (TikTok 卡拉 OK 逐词高亮)
- default to `none`
- render the assembled video first, then burn karaoke captions only when `karaoke` is selected
- use the sales-country code in the filename to select the language and use local Whisper's actual transcript as the caption copy
- when every Segment's `[音频文案]` explicitly says there is no voiceover, narration, or dialogue, skip captions
- use the vendored `tiktok-karaoke-captions` implementation and fonts
- never use Deepgram or another remote transcription API

Cleanup is owned by this agent, not Video Generation. It must never run automatically. Before deletion, verify each finished MP4 with FFprobe and require positive duration plus video and audio streams. Delete only source media and `.product-lock.json` files in the pending script directory. Preserve the Markdown script, `.exported.json` marker, and finished MP4, then set the marker status to `已清理`.

Finished videos are written to `成品视频/产品/脚本同名.mp4`. Scanning and cleanup validation must continue to recognize legacy outputs inside that root at `模型/日期/产品/脚本同名.mp4`, preferring the new path when both exist.

## CLI

```bash
python3 app/video_assembly.py scan --write-report
python3 app/video_assembly.py assemble --all-missing
```

## Offline Runtime

Runtime dependencies are stored under `runtime/` and `vendor/`. The app disables HyperFrames update checks, automatic installation, and telemetry. It never falls back to `npx` or `pnpm dlx`, and generated compositions load GSAP from the local project.

Install and prewarm the optional local karaoke runtime once before first use:

```bash
bash scripts/install_caption_runtime.sh
```

Validate the packaged app:

```bash
bash scripts/validate_app.sh
```
