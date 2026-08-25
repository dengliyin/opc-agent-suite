# Script-Adaptation

Portable Codex skill for adapting finished product-video Markdown scripts into:

- full adaptation Markdown
- NanoBananaPro storyboard-grid JSON
- Veo batch-generation CSV
- a local web UI for batch script adaptation across Veo / Omni / Sora / Grok

## Install

Copy this folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R Script-Adaptation ~/.codex/skills/
```

## Configure API Key

Create a local secrets file:

```bash
cd ~/.codex/skills/Script-Adaptation
cp software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.example.json \
  software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.local.json
```

Then fill `modelmesh_api_key`, or set:

```bash
export MODELMESH_API_KEY="your_key"
```

`agent_secrets.local.json` is ignored by Git.

## Run With Docker

```bash
cd software/Script-Adaptation-app
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:8788
```

The bundled `docker-compose.yml` mounts the app into the container and also mounts the local product-script workspace used by this machine. If you run it on another machine, update these paths first:

- `software/Script-Adaptation-app/docker-compose.yml`
- `software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_settings.json`

## Run Without Docker

```bash
cd ~/.codex/skills/Script-Adaptation
bash scripts/start_web.sh
```

Open:

```text
http://127.0.0.1:8788
```

## Validate

```bash
bash scripts/validate_app.sh
```

## Token And Retry Policy

- Existing valid adaptations are reused by default when the source script, target model, prompt, language, facts, and segment settings have not changed.
- Veo, Omni, and Grok load only their own prompt file. Only the current target-language rule is injected.
- Optional product context is reduced locally to a compact fact card; the full product document is not duplicated in the request.
- Adaptation and repair requests disable DeepSeek thinking mode and cap output at 32K tokens.
- Any number of selected scripts is accepted. Work is scheduled in batches of at most three, for example five scripts run as `3 + 2`.
- Valid scripts are retained immediately. Only failed scripts are retried, with retry batches shrinking from three to two to one.
- Once a model response exists, quality-control failures use exact local JSON replacements instead of asking the model to rewrite the full adaptation.

## Repository Safety

The repository intentionally excludes runtime data and private configuration:

- generated/adapted scripts under `software/Script-Adaptation-app/projects/`
- local output folders
- `agent_secrets.local.json`
- local logs, caches, and Python bytecode

Keep product scripts and API keys outside Git. Use `agent_secrets.example.json` as the template for local credentials.
