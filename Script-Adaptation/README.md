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

## Repository Safety

The repository intentionally excludes runtime data and private configuration:

- generated/adapted scripts under `software/Script-Adaptation-app/projects/`
- local output folders
- `agent_secrets.local.json`
- local logs, caches, and Python bytecode

Keep product scripts and API keys outside Git. Use `agent_secrets.example.json` as the template for local credentials.
