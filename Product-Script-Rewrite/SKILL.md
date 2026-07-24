---
name: Product-Script-Rewrite
description: Independent local agent that rewrites an existing viral product script for a different target product using DeepSeek and local Obsidian product information.
---

# Product Script Rewrite Agent

Run the local web UI with:

```bash
bash scripts/start_web.sh
```

Open `http://127.0.0.1:9997/`.

The source scripts are read from the configured `纯AI视频/02参考脚本` product folders. The rewritten Markdown is written into the selected target product folder under the same root.

This agent is separate from 脚本适配. It rewrites product content while preserving the source video's viral structure; it does not generate Veo, Omni, or Grok delivery formats.

Do not print or package `agent_config/agent_secrets.local.json`.

Validate code and naming behavior with:

```bash
bash scripts/validate_app.sh
```
