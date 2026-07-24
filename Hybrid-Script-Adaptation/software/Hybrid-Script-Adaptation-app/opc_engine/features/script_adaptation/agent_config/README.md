# 钩子与 CTA 脚本适配智能体本地配置

本目录是 `script_adaptation_agent.py` 的自包含能力目录。钩子与 CTA 脚本适配智能体默认只从这里读取自己的提示词、模型设置和本地密钥，不依赖 9994 的配置、运行状态或输出目录。

## 文件说明

- `agent_settings.json`：智能体主配置。保存模型名、目标视频模型、片段时长、内部归档项目和能力文件名；Web 界面不再重复确认产品信息。
- `agent_secrets.local.json`：本地 API Key。该文件已被 `.gitignore` 忽略，不要提交。
- `agent_secrets.example.json`：密钥文件模板，可用于重建 `agent_secrets.local.json`。
- `veo_script_adaptation_prompt.md`：脚本修改/适配提示词。

## 使用边界

- 提示词必须放在本目录内。
- `agent_settings.json` 里的文件路径按本目录解析。
- API Key 优先读取环境变量 `MODELMESH_API_KEY` 或 `GEMINI_API_KEY`，其次读取本目录的 `agent_secrets.local.json`。
- 输入只扫描 `AI实拍混剪/03复刻裂变脚本/混剪-钩子|混剪-CTA/<产品名>/<来源脚本>` 中的 Markdown 脚本，输出镜像到 `04适配脚本/<模型>/<类型>/<产品名>/<来源脚本>`。

## Web 界面

启动：

```bash
python3 -m opc_engine.features.script_adaptation.script_adaptation_agent_web --port 9999
```

打开：

```text
http://127.0.0.1:9999
```

页面会读取本目录内的配置、提示词和本地密钥，只扫描钩子与 CTA 两个脚本目录、调用 AI 文本模型适配，并查看输出文件。
