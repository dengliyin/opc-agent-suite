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

The right-side run panel contains the always-visible text sticker controls; the finished-file list is not shown. The confirmation dialog only summarizes the selected sticker settings. Stickers are off by default, and a batch uses the same text and settings for every selected item. Sticker settings are persisted in `data/latest-scan.json` and must not create sidecar files in pending-media folders.

Sticker rules:

- manual text only, up to 36 characters and two rendered lines
- three styles: `dark` (黑底白字), `highlight` (黄底黑字), and `outline` (白字描边)
- positions: top, center, or bottom within the TikTok-safe center column
- timing: full video or a custom range of at least 0.4 seconds
- dynamic font sizing and a short deterministic GSAP entrance/exit animation
- no subtitles, automatic script extraction, or remote text generation

Cleanup is owned by this agent, not Video Generation. It must never run automatically. Before deletion, verify each finished MP4 with FFprobe and require positive duration plus video and audio streams. Delete only source media and `.product-lock.json` files in the pending script directory. Preserve the Markdown script, `.exported.json` marker, and finished MP4, then set the marker status to `已清理`.

## CLI

```bash
python3 app/video_assembly.py scan --write-report
python3 app/video_assembly.py assemble --all-missing
```

## Offline Runtime

Runtime dependencies are stored under `runtime/` and `vendor/`. The app disables HyperFrames update checks, automatic installation, and telemetry. It never falls back to `npx` or `pnpm dlx`, and generated compositions load GSAP from the local project.

Validate the packaged app:

```bash
bash scripts/validate_app.sh
```
