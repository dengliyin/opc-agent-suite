# Hybrid-Script-Adaptation

独立的混剪脚本适配 Agent，以现有 `Script-Adaptation` 为完整母版复制，用于把同时包含钩子和 CTA 的参考脚本适配成 Omni 等视频模型可直接使用的片段指令。

- full adaptation Markdown
- NanoBananaPro storyboard-grid JSON
- Veo batch-generation CSV
- a local web UI for batch script adaptation across Veo / Omni / Sora / Grok

默认输入和输出：

```text
输入 1：$OPC_VAULT_ROOT/wiki/视频/04爆款视频脚本/混剪-钩子
输入 2：$OPC_VAULT_ROOT/wiki/视频/04爆款视频脚本/混剪-CTA
输出：$OPC_VAULT_ROOT/wiki/视频/混剪适配后的脚本/<目标模型>
```

本 Agent 与 9994 使用相同的代码结构和输出契约，但拥有独立目录、配置、密钥、日志、虚拟环境和 9999 端口。

## Install

Copy this folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R Hybrid-Script-Adaptation ~/.codex/skills/
```

## Configure API Key

Create a local secrets file:

```bash
cd ~/.codex/skills/Hybrid-Script-Adaptation
cp software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.example.json \
  software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.local.json
```

Then fill `modelmesh_api_key`, or set:

```bash
export MODELMESH_API_KEY="your_key"
```

`agent_secrets.local.json` is ignored by Git.

## Run With Docker

```bash
cd software/Hybrid-Script-Adaptation-app
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:9999
```

The bundled `docker-compose.yml` mounts the app into the container and also mounts the local hybrid-script workspace used by this machine. If you run it on another machine, update these paths first:

- `software/Hybrid-Script-Adaptation-app/docker-compose.yml`
- `software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_settings.json`

## Run Without Docker

```bash
cd ~/.codex/skills/Hybrid-Script-Adaptation
bash scripts/start_web.sh
```

Open:

```text
http://127.0.0.1:9999
```

## Validate

```bash
bash scripts/validate_app.sh
```

## Repository Safety

The repository intentionally excludes runtime data and private configuration:

- generated/adapted scripts under `software/Hybrid-Script-Adaptation-app/projects/`
- local output folders
- `agent_secrets.local.json`
- local logs, caches, and Python bytecode

Keep hybrid scripts and API keys outside Git. Use `agent_secrets.example.json` as the template for local credentials.
