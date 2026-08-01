# Script Generation Config

本目录保存 `opc_engine/features/script_generation` 的提示词和本地输入配置。脚本生成的错题本默认从 `$OPC_VAULT_ROOT/wiki/视频/共享知识库/脚本错题本` 按当前产品匹配同名 `.md`。

## 文件说明

- `script_generation_rewrite_prompt.md`：脚本产出复刻提示词，只维护复刻规则和输出格式。
- `script_generation_mutation_prompt.md`：裂变提示词；勾选页面里的「是否裂变」时，会在脚本产出后按这份提示词和当前产品错题本执行单一裂变流程，并只保存裂变后的最终结果。
- `inputs.example.json`：脚本生成输入配置示例，不放真实产品资料、竞品脚本路径或密钥。
- `model_defaults.json`：旧版共享模型配置；当前版本首次运行时会在 Application Support 中自动创建运行配置。

## 本地私有文件

运行配置统一保存在 `~/Library/Application Support/OPC-Agent-Suite/Script-Generation/`，不再从项目目录读取：

- `inputs.json`：本机当前要跑的产品文档、竞品脚本和裂变选项等输入；总时长与逐镜时间码始终取自竞品参考。
- `model_defaults.json`：默认 Base URL、模型和运行参数。
- `model_settings.json`：保存本机模型设置及 ModelMesh/Gemini API Key，并覆盖默认值。
- `imported_inputs/`：可视化界面选择本机 Markdown 后自动导入的任务输入副本，避免手动填写路径出错。
- `*.local.json`：临时实验配置。

API Key 也可以通过环境变量 `MODELMESH_API_KEY` 或 `GEMINI_API_KEY` 提供。
