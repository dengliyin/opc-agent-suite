---
name: Hybrid-Script-Adaptation
description: Portable self-contained hybrid script adaptation workflow copied from the 9994 agent structure. Use when Codex needs to run, install, package, or maintain the bundled 钩子与 CTA 脚本适配智能体; adapt parsed hook or CTA Markdown; manage its prompt or knowledge base; or produce model-ready Markdown, storyboard JSON, and video prompt outputs.
---

# Hybrid Script Adaptation Agent

## Overview

Use this skill to operate the bundled 钩子与 CTA 脚本适配智能体. It is independent from 9994 and uses the same code structure and output contract. The runnable app is packaged inside this skill:

```text
software/Hybrid-Script-Adaptation-app/
```

The skill is portable: another user can copy the whole `Hybrid-Script-Adaptation/` folder into their own `~/.codex/skills/` directory and run it there. Do not rely on the original author's local absolute paths, WeChat temp folders, old OPC project folders, or external workflow config folders.

## Folder Contract

```text
software/Hybrid-Script-Adaptation-app/
  opc_engine/features/script_adaptation/agent_config/
    agent_settings.json
    agent_secrets.example.json
    agent_secrets.local.json
    veo_script_adaptation_prompt.md
    cross_border_ecommerce_hot_content_knowledge_base.md
  opc_engine/features/script_adaptation/
    script_adaptation_agent.py
    script_adaptation_agent_web.py
    content_workflow_stage.py
  projects/
    <product_project>/hot_sources/<source_id>/scripts/
    <product_project>/hot_sources/<source_id>/adaptations/
scripts/
  start_web.sh
  validate_app.sh
references/
  output-contract.md
```

`agent_secrets.local.json` is private and is intentionally not included in the shared package. Do not print API keys.

## Common Actions

Start or restart the visual web UI from this skill folder:

```bash
bash scripts/start_web.sh
```

Open:

```text
http://127.0.0.1:9999
```

Validate the bundled app without calling Gemini:

```bash
bash scripts/validate_app.sh
```

For code changes, edit files under:

```text
software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/
```

After code or prompt changes, restart the web UI from `scripts/start_web.sh`.

## Install For Another Computer

Send the entire `Hybrid-Script-Adaptation/` folder or a zip made from it. The recipient should place it at:

```text
~/.codex/skills/Hybrid-Script-Adaptation/
```

Then they should add their own API key by either:

```bash
cp software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.example.json \
  software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.local.json
```

or by setting:

```bash
export MODELMESH_API_KEY="their_key"
```

Python 3 is required. `requirements.txt` is included in the bundled app; the core web UI and Gemini-compatible call path use the Python standard library.

## Adaptation Rules

Input must be a `.md` hook or CTA script from one of the two configured libraries: `混剪-钩子` or `混剪-CTA`. The web UI copies the selected script into the active product project before running.

The output base name must be:

```text
模型名-原脚本文件名stem
```

Expected output:

```text
<base>.md
```

## Config Rules

- Keep prompt and knowledge files inside the bundled `agent_config/`.
- Keep `script_adaptation_input_dirs` limited to the `混剪-钩子` and `混剪-CTA` libraries.
- If the user supplies a new prompt or knowledge-base file, copy its contents into the matching `agent_config/` file instead of pointing to an external path.
- The script adaptation page should not ask for product name, product project, or adaptation notes; the Markdown script itself is the product context.
- Use the bundled `projects/` only for local runtime inputs and outputs. Do not include real product output data in a shared package unless the user explicitly asks.

## Verification

After changes:

```bash
bash scripts/validate_app.sh
```

If the web UI is running:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9999/api/state
```

Do not call Gemini just to verify UI, naming, prompt-file, or CSV-format changes.
