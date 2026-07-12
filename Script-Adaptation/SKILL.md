---
name: Script-Adaptation
description: Portable self-contained script adaptation workflow for finished product-video scripts. Use when Codex needs to run, install, package, or maintain the bundled 脚本适配智能体 skill; open its web UI; adapt a Markdown product script with Gemini/ModelMesh; manage its prompt or knowledge base; or produce Markdown, NanoBananaPro storyboard JSON, and Veo batch-generation CSV outputs from a finished script.
---

# Script Adaptation Agent

## Overview

Use this skill to operate the bundled 脚本适配智能体. The runnable app is packaged inside this skill:

```text
software/Script-Adaptation-app/
```

The skill is portable: another user can copy the whole `Script-Adaptation/` folder into their own `~/.codex/skills/` directory and run it there. Do not rely on the original author's local absolute paths, WeChat temp folders, old OPC project folders, or external workflow config folders.

## Folder Contract

```text
software/Script-Adaptation-app/
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
http://127.0.0.1:9994
```

Validate the bundled app without calling Gemini:

```bash
bash scripts/validate_app.sh
```

For code changes, edit files under:

```text
software/Script-Adaptation-app/opc_engine/features/script_adaptation/
```

After code or prompt changes, restart the web UI from `scripts/start_web.sh`.

## Install For Another Computer

Send the entire `Script-Adaptation/` folder or a zip made from it. The recipient should place it at:

```text
~/.codex/skills/Script-Adaptation/
```

Then they should add their own API key by either:

```bash
cp software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.example.json \
  software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.local.json
```

or by setting:

```bash
export MODELMESH_API_KEY="their_key"
```

Python 3 is required. `requirements.txt` is included in the bundled app; the core web UI and Gemini-compatible call path use the Python standard library.

## Adaptation Rules

Input must be a finished product-video script in `.md` format. The web UI copies it into the active product project before running.

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
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9994/api/state
```

Do not call Gemini just to verify UI, naming, prompt-file, or CSV-format changes.
