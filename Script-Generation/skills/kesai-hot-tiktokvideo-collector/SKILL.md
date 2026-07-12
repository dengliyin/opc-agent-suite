---
name: kesai-hot-tiktokvideo-collector
description: Run and maintain the local "OPC 内容量化增长引擎" app for current product project storage, FastMoss TikTok product/video collection, Kolsprite video downloads, Gemini/ModelMesh video teardown, product script generation, script adaptation, video generation, publishing records, data attribution, and script optimization. Use when the user asks to collect FastMoss product-linked TikTok video data, export TikTok video URLs, download videos from collected URLs, analyze downloaded TikTok videos into scripts, generate product sales scripts from teardown results and product information, adapt scripts for video generation models, generate full videos from produced clips, prepare TikTok publishing records, attribute video metrics, optimize scripts from performance data, adjust the app workflow, update saved task parameters, or troubleshoot this specific collector.
---

# OPC 内容量化增长引擎

## Overview

Use the local collector project to manage the current product project, search FastMoss products by keyword, country/region, and a three-level category path, collect product-linked video metrics and TikTok URLs, download the corresponding no-watermark MP4 files through Kolsprite, tear down downloaded videos with Gemini/ModelMesh, generate new product sales scripts from competitor teardown results plus the saved product profile, adapt scripts for video generation models, generate full videos from produced clips, record publishing plans, attribute performance metrics, and optimize scripts from data.

The project root is the `Script-Generation` directory in the suite:

```text
opc-agent-suite/Script-Generation
```

If the current workspace contains `kesai_app.py`, prefer the current workspace as the project root.

## Required Parameters

Collect or confirm these values before running a new task:

- FastMoss phone number and password.
- Optional keyword value provided by the user at runtime. Leave it empty when the task should use only country, category, and filters. Do not store real keyword examples in committed files.
- Country/region label exactly as FastMoss displays it, such as `马来西亚`.
- Three-level category path, separated with `>`, such as `美妆个护 > 头部护理与造型 > 染发用品`.
- Optional FastMoss product search filters: shop type, product type, product status, creator conversion rate, total sales, total GMV, 7-day sales, 7-day GMV, creator count, commission rate, and shipping method.
- Product link count.
- Video count per product.
- For script generation: use a selected product information Markdown file plus a selected competitor hot-script/teardown Markdown reference. The only optional creative parameters are target video total duration and the post-generation mutation rewrite toggle with variant count. When duration is omitted, follow the reference video's original total duration. Do not ask for target country/region, target language, golden-hook duration, audio emotion notes, a manual material framework, or a separate reference case; extract language, rhythm, emotion, framework, and hook structure from the selected competitor reference and product context. If post-generation mutation rewrite is enabled, first generate the product script, then rewrite only people, setting, costume/props, and surface visuals while preserving camera language, emotional tension, visual spectacle, narrative structure, product facts, and CTA placement; the final saved `.md` is the rewritten result.
- For the content distribution loop: an output script, target video generation model, generated clip folder, publishing account alias/caption/tags, the latest processed attribution CSV, and the script to optimize.

The app stores current runtime state in `app_config.json`, and mirrors each workflow's own inputs into `workflow_configs/<workflow>/config/inputs.json`. These files may contain local credentials and business context and must not be committed or printed back verbatim.

All generated assets are organized under one local product project folder:

```text
projects/<product_project_slug>/
```

The product project folder is the asset spine. Collection runs go under `collection_runs/`; every source/competitor video gets its own `hot_sources/<source_id>/` folder; downstream teardown, scripts, adaptations, generated videos, publish records, and optimization notes for that source stay inside that same source folder. Product-level raw data and attribution reports live under `raw_data/` and `product_level_reports/`.

The active product project is mandatory before every workflow stage. The user must first open the Product Info page and save at least a product name or English name so the app can create `projects/<product_project_slug>/`. Every workflow page should let the user select an existing product project from the local `projects/` library before running. Switching products must update the active `product_project_slug`, load that product's saved profile, refresh file listings, and write new outputs into the selected product folder. Do not run collection, teardown, script generation, adaptation, video generation, publishing records, data attribution, or script optimization unless an active product project is selected. This prevents outputs from being written into a generic or wrong project folder.

The Web UI should display project-local paths as project-relative paths, such as `projects/<product>/...` or `knowledge_base/...`. External files outside the project may remain absolute. Opening a displayed relative path must resolve it against the app root.

Each workflow must remain independently operable so the user can manually take over if one automation step fails. Local workflow inputs are stored by feature under ignored workflow config folders:

```text
workflow_configs/product_info/config/inputs.json
workflow_configs/hot_collection/config/inputs.json
workflow_configs/video_teardown/config/inputs.json
opc_engine/features/script_generation/config/inputs.json
workflow_configs/script_adaptation/config/inputs.json
workflow_configs/video_generation/config/inputs.json
workflow_configs/video_publish/config/inputs.json
workflow_configs/data_attribution/config/inputs.json
workflow_configs/script_optimization/config/inputs.json
```

Local editable prompts are also stored by feature:

```text
workflow_configs/video_teardown/config/video_teardown_prompt.md
opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md
workflow_configs/script_adaptation/config/script_adaptation_prompt.md
```

Feature pages should show their own input config path and prompt file path where applicable, write prompt edits back to that file, and avoid storing large prompt bodies inline in `app_config.json`. Command-line entry points should merge the corresponding workflow `inputs.json` before execution so each workflow remains independently runnable outside the Web UI. Legacy `knowledge_base/*_prompt.md` files may be read as a fallback only.

## Code Organization

The real implementation is organized by workflow under `opc_engine/`:

```text
opc_engine/core/                         # product project and asset path helpers
opc_engine/features/hot_collection/      # FastMoss collection and TikTok video downloads
opc_engine/features/video_teardown/      # Gemini/ModelMesh video teardown
opc_engine/features/script_generation/   # product sales script generation
opc_engine/features/script_adaptation/   # script adaptation plus scaffold stages
opc_engine/features/data_attribution/    # natural-flow and paid-data downloads
opc_engine/tools/                        # migration and maintenance tools
```

Do not keep old flat `scripts/*.py` entry points. UI actions, README commands, and internal subprocess calls should use `python3 -m opc_engine...` module entry points directly. New production logic belongs in `opc_engine`.

## Main Workflow

1. Open or update the relevant `workflow_configs/<workflow>/config/inputs.json` with the requested parameters, and let the app mirror current runtime state into `app_config.json`. Use `app_config.example.json` as the broad schema if the config file does not exist.
2. Ensure a product project exists first: save the product profile on `/product`, with at least `product_name` or `english_name`.
3. Keep `show_browser` as `false` by default. The automation opens Chrome for Testing and minimizes it so the user mainly watches logs.
4. Run the local web app when the user wants a visible control panel:

```bash
./run_kesai_app.sh
```

5. The app opens at:

```text
http://127.0.0.1:8765
```

6. The root path `/` is the overview cover page. It explains the OPC content growth loop and links to the separate workflow pages in order: `/product`, `/collect`, `/analyze`, `/script`, `/adapt`, `/assemble` (labeled 视频生成), `/publish`, `/metrics`, and `/optimize`.
7. For a direct command-line run, execute the full pipeline only after the product project is confirmed:

```bash
python3 -m opc_engine.features.hot_collection.run_collection_pipeline
```

The full pipeline first runs `opc_engine.features.hot_collection.collect_fastmoss_product_videos`, then `opc_engine.features.hot_collection.download_tiktok_videos_kolsprite`.

## Change Management

When the user asks to adjust one workflow step, always audit and update related surfaces in the same turn where practical: Web UI labels and inputs, saved config schema, command scripts, local prompt files, README, this skill file, and downstream workflow stages that consume the changed output. For example, if script generation stops asking for a manually entered material framework, also update the rewrite prompt and generation script so the framework is extracted from the selected teardown Markdown.

## What The Collector Does

The FastMoss collection phase:

- Checks whether the program is already logged in.
- If the saved FastMoss phone number or password changed, clears the old browser login state and forces a fresh login for the new account.
- Logs in automatically when the login state has expired.
- Closes the entry popup on the FastMoss dashboard.
- Searches by keyword when provided; if the keyword is empty, skips keyword search and uses country/region, category, and filters only.
- Selects country/region from the saved option.
- Selects category from the saved option path. Third-level paths should be preferred when available; `全部` means no category filter. The collector expands the FastMoss category area before selecting, so hidden top-level categories can be used.
- The Web UI loads FastMoss category dropdowns from `data/fastmoss_category_tree.json`. Regenerate it with `python3 -m opc_engine.features.hot_collection.scrape_fastmoss_category_tree` when FastMoss category options change; the scraper scrolls the cascader menus to collect second- and third-level categories.
- Applies saved product search filters where configured: shop type, product type, product status, and the dropdown filters in the FastMoss filter row. Dropdown filters should use the exact FastMoss option labels, and the collector confirms filters that require a confirmation click.
- Opens the top product detail pages according to `product_limit`.
- Enters `商品关联视频`.
- Collects up to `videos_per_product` videos per product, paging every 5 rows.
- Records video title, creator name, 28-day sales, 28-day GMV, 28-day ad spend, 28-day ROAS, views, likes, comments, interaction rate, publish time, and `tiktok_video_url`.

The download phase:

- Reads the newest CSV in `projects/<product>/collection_runs/**` that contains `tiktok_video_url`.
- Opens `https://dl.kolsprite.com/tools/video-download`.
- Submits each TikTok URL.
- Clicks the high-quality no-watermark MP4 download option.
- Saves each video under `projects/<product>/hot_sources/<source_id>/source/` using the TikTok video ID, for example `7622175051634314497.mp4`.

The Gemini teardown test phase:

- Reads `modelmesh_api_key`, `modelmesh_base_url`, `video_analysis_model`, `analysis_input_path`, `video_analysis_prompt_path`, and the shared content knowledge base path from local `app_config.json` or environment variables.
- Calls the Shengsuanyun/ModelMesh Gemini-compatible endpoint with a local MP4 as base64 inline video.
- Uses `google/gemini-3-flash` by default.
- Writes Markdown and raw JSON results to `projects/<product>/hot_sources/<source_id>/teardown/`.
- The Web UI has a separate "视频拆解" page for editing and locally saving the API key, model, teardown prompt file, shared hot-content knowledge base path, and a manual video path. It must show the active product project so the user knows which product the teardown belongs to and where results will be archived. The teardown prompt defaults to `workflow_configs/video_teardown/config/video_teardown_prompt.md`. The path can be a directory of MP4 files or a single MP4 file; directories are analyzed in full, single files are analyzed alone, and the path is required. The teardown page does not automatically use collection download folders. The UI only shows the shared knowledge base path; edit the knowledge base text by opening the local file.
- The first local shared content knowledge base is stored at `knowledge_base/hot_content_knowledge_base.md`. It is local-only and ignored by Git. Use it for competitor/video teardown methodology and script adaptation methodology; script generation now keeps its own module-local knowledge base at `opc_engine/features/script_generation/config/cross_border_ecommerce_knowledge_base.md`. Product profile context still lives separately inside the active product project. Legacy local files named `knowledge_base/video_teardown_knowledge_base.md` are read as a fallback only.

The product profile phase:

- The Web UI has a separate "产品信息" page for saving the user's product profile inside the current product project.
- Product profile data is stored under `product_profile` in `app_config.json` and mirrored to `projects/<product>/product_profile/current_product_profile.md`.
- Product profile fields follow the product Markdown structure: basic identification, pricing strategy, top 3 selling points, audience x pain matrix, pain/conversion talk tracks, TikTok marketing angles, market keywords, material type suggestions, and notes.
- Treat product profile content as local business context. Do not commit real product details unless the user explicitly provides sanitized examples for documentation.

The script generation phase:

- The Web UI has a separate "脚本产出" page for turning four inputs into a new product sales script: rewrite prompt, selected competitor teardown Markdown, saved product profile, and the script-generation module's own knowledge base. The selected teardown Markdown is the reference case; material framework and case rhythm are extracted from it automatically. The CLI also supports direct file mode with a product document Markdown and a competitor hot-script Markdown.
- The script generation page must use the same "当前产品项目" context card as the other downstream workflow pages, so the user can confirm which product project the script belongs to. Product information should be accessible from that card, but should not replace the product-project context label.
- It reads `product_profile`, `script_content_knowledge_base_path`, `script_generation_prompt_path`, `script_generation_mutation_prompt_path`, `script_reference_analysis_path`, `script_reference_script_path`, `script_product_document_path`, optional `script_total_duration`, optional `script_enable_mutation_rewrite`, and optional `script_mutation_variants` from `opc_engine/features/script_generation/config/inputs.json` or CLI overrides.
- The default rewrite prompt is stored at `opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md`. The optional post-generation mutation prompt is stored at `opc_engine/features/script_generation/config/script_generation_mutation_prompt.md`. The script generation command automatically injects the active product profile or `--product-doc`, selected teardown Markdown or `--reference-script`, module-local knowledge base, and optional target video total duration before appending the rewrite prompt. If duration is empty, the model must follow the reference video's original total duration. Golden-hook duration and audio emotion are not separate inputs; they are cloned from the competitor reference. If mutation rewrite is enabled, the generated script is injected into the mutation prompt and the final saved result is the rewritten script. Prompt files should contain only rules and output format instructions, not duplicate variable-import tables. The script generation knowledge base is stored at `opc_engine/features/script_generation/config/cross_border_ecommerce_knowledge_base.md`; this stage does not default to external `knowledge_base/` or `workflow_configs/script_generation/` files.
- Results are written to `projects/<product>/hot_sources/<source_id>/scripts/` as `<source_id>_<product>.md`, with raw model responses in `<source_id>_<product>.raw.json`. If the same product/reference pair is generated again and the base filename already exists, append `_002`, `_003`, etc. to both Markdown and raw JSON so previous results are never overwritten.

The script adaptation phase:

- The Web UI has a separate "脚本适配" page for turning a finished product sales script into a complete handoff prompt package for external video-generation large models.
- It reads `script_adaptation_input_path`, `script_adaptation_prompt_path`, `modelmesh_api_key`, `modelmesh_base_url`, `video_analysis_model`, `video_teardown_knowledge_base_path`, `script_adaptation_target_model`, `script_adaptation_segment_seconds`, and `script_adaptation_notes` from local config and `workflow_configs/script_adaptation/config/inputs.json`.
- The default script adaptation prompt is stored at `workflow_configs/script_adaptation/config/script_adaptation_prompt.md`. The adaptation command automatically injects the selected finished script, target video generation model, segment duration limit, adaptation notes, and shared knowledge base before appending the adaptation prompt, so the prompt file should contain only adaptation rules and output format instructions, not a duplicate user-input section or script placeholder. The shared content knowledge base is stored at `knowledge_base/hot_content_knowledge_base.md`. Both are local-only and ignored by Git. Legacy `knowledge_base/script_adaptation_prompt.md` is read as fallback only.
- This stage calls the configured ModelMesh / Gemini text model to adapt the finished script into model-specific first-frame/grid prompts plus a video-model input CSV. The CSV module must have one row per segment, and each row's `video_model_input_text` should be directly usable as input text for the selected video generation model. In the CSV, `time_range` means the segment's own duration, not its absolute position in the full video; `shot_reference` should contain only the source shot number, while continuation status belongs in `segment_type`. It does not call Veo, Kling, or any real video generation provider. It writes exactly three output types: the complete model response as Markdown, module one as `*_image_prompts.json`, and module two as `*_video_prompts.csv`. Results go to `projects/<product>/hot_sources/<source_id>/adaptations/` when an input script belongs to a source, otherwise under `projects/<product>/product_level_reports/script_adaptations/`.

The content distribution loop:

- `/adapt` calls the configured text model to turn a finished script into video-model-ready segment copy, camera/action instructions, and first-frame image prompts. Results are source-scoped under `hot_sources/<source_id>/adaptations/` when possible.
- `/assemble` is the 视频生成 page, but it is currently a workflow scaffold only. It does not call Veo/Kling or any real video generation provider, and it is not a complete automated editing pipeline. It writes a video generation manifest for existing clips and may optionally merge existing clips with `ffmpeg`. Results are source-scoped under `hot_sources/<source_id>/generated_videos/` when possible.
- `/publish` is the 视频发布 page, but it is currently a workflow scaffold only. It does not log in to TikTok, authorize accounts, or auto-publish. It creates publishing plans/records for TikTok accounts. Records are source-scoped under `hot_sources/<source_id>/publish_records/` when possible.
- `/metrics` is the 数据归因 page. It has two stages: stage 1 has two direct buttons, one for natural traffic data by account group and one for paid performance data for yesterday; stage 2 automatically reads the newest raw natural/paid files from `projects/<product>/raw_data/natural_flow/` and `projects/<product>/raw_data/ad_performance/`, merges natural `作品ID` = paid `Video ID`, then writes a work-level attribution CSV with Chinese headers to `projects/<product>/product_level_reports/data_attribution/`. The frontend should only show the processed attribution CSV path, not raw input paths.
- Natural traffic data uses `opc_engine.features.data_attribution.login_natural_flow_assisted` for assisted login and `opc_engine.features.data_attribution.download_natural_flow_data` for download. Paid performance data uses `opc_engine.features.data_attribution.download_ad_performance_data` as the local entry point around the user's existing exporter. These entry points must use project-local automation profiles; do not attach them to the user's everyday Chrome profile. Credentials must be passed through environment variables or local ignored config, never committed. The UI should label these as 自然流数据 and 投放数据 and should not expose source platform names.
- `/optimize` uses the source script plus attributed metrics to create weighted evaluation and optimization suggestions. Results are source-scoped under `hot_sources/<source_id>/optimizations/` when possible.
- `/assemble`, `/publish`, `/metrics`, and `/optimize` currently provide runnable scaffolds through `opc_engine.features.script_adaptation.content_workflow_stage`; treat them as framework entry points until the user asks to wire a specific video generation, publishing, or analytics provider.

Run a single-video minimal test with:

```bash
python3 -m opc_engine.features.video_teardown.analyze_video_teardown /path/to/video.mp4
```

Run batch teardown for the saved `analysis_input_path` with:

```bash
python3 -m opc_engine.features.video_teardown.analyze_video_teardown_batch
```

Generate a product script from the saved script settings with:

```bash
python3 -m opc_engine.features.script_generation.generate_product_script
```

Run the script generation agent web UI with:

```bash
python3 -m opc_engine.features.script_generation.script_generation_agent_web --port 8790
```

Generate directly from a product document and competitor hot script with:

```bash
python3 -m opc_engine.features.script_generation.generate_product_script \
  --product-doc /path/to/product.md \
  --reference-script /path/to/hot_competitor_script.md \
  --total-duration 40s
```

Run a content distribution scaffold stage with:

```bash
python3 -m opc_engine.features.script_adaptation.content_workflow_stage adapt
python3 -m opc_engine.features.script_adaptation.content_workflow_stage assemble
python3 -m opc_engine.features.script_adaptation.content_workflow_stage publish
python3 -m opc_engine.features.script_adaptation.content_workflow_stage metrics_download
python3 -m opc_engine.features.script_adaptation.content_workflow_stage metrics
python3 -m opc_engine.features.script_adaptation.content_workflow_stage optimize
```

## Outputs

CSV files are written to:

```text
projects/<product>/collection_runs/<run_name>/<run_name>.csv
```

CSV filename format:

```text
关键词_国家_完整三级类目_年月日_商品链接数量_视频URL数量.csv
```

When the keyword is empty, the filename prefix is `无关键词`.

Downloaded videos are written to:

```text
projects/<product>/hot_sources/<source_id>/source/
```

Video filename format:

```text
TikTok视频ID.mp4
```

## Troubleshooting

- If FastMoss shows a CAPTCHA, slider, security block, or the login page cannot be detected, set `show_browser` to `true`, rerun, and ask the user to complete the visible browser step manually.
- If category selection seems wrong, inspect the log for the confirmed category string. The third-level category must be clicked, not only hovered.
- If login fails in minimized mode, rerun with the browser visible once so the persistent browser profile can refresh its session.
- If the downloader skips a video, check whether an MP4 with the same TikTok video ID already exists in the target download directory.

## Safety Rules

- Never commit `app_config.json`, `fastmoss_config.json`, `projects/`, `browser-profile/`, `app.log`, or generated MP4/CSV files.
- Never commit `knowledge_base/`, model API keys, or the user's proprietary teardown/script prompts, teardown knowledge base, product profile, generated scripts, generated clips, publishing records, or performance data.
- Never commit real task keywords in examples, defaults, docs, or skill text. Use an empty value or a generic placeholder.
- Do not print the saved FastMoss password in final responses or logs beyond what the app already masks in its UI.
- Prefer the app and existing scripts over ad hoc browser automation unless debugging a selector failure.
- When changing the app, keep the user-facing title as `OPC 内容量化增长引擎`.
