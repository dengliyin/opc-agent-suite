# 脚本产出 Agent

独立本地 Agent，根据产品信息 Markdown 和竞品爆款脚本或拆解稿生成产品带货视频脚本。

本目录只负责脚本产出，不再承载 OPC 总控制台、视频采集、视频拆解、脚本适配、发布、数据归因或脚本优化。

## 启动

```bash
./run_kesai_app.sh
```

打开：

```text
http://127.0.0.1:9993/
```

也可以直接运行：

```bash
python3 -m opc_engine.features.script_generation.script_generation_agent_web --port 9993
```

## 输入

- 产品信息 Markdown。
- 竞品爆款脚本或视频拆解 Markdown。
- 视频总时长和逐镜时间码严格跟随爆款参考。
- 可选裂变改写及裂变数量。
- ModelMesh/Gemini 兼容模型配置。

语言、节奏、情绪、钩子结构和镜头框架从竞品参考及产品资料中提取，不要求重复填写。

## 配置

首次使用时复制本地配置：

```bash
cp opc_engine/features/script_generation/config/inputs.example.json \
  opc_engine/features/script_generation/config/inputs.json
```

Base URL、模型和运行参数保存在受 Git 跟踪的 `config/model_defaults.json`。真实产品路径和 API Key 只保存在本机，不提交 Git；API Key 可以在 Web 页面填写，也可以通过以下环境变量提供：

```bash
export MODELMESH_API_KEY="your_key"
```

配置文件说明见：

```text
opc_engine/features/script_generation/config/README.md
```

## 命令行生成

读取本地配置：

```bash
python3 -m opc_engine.features.script_generation.generate_product_script
```

直接指定文件：

```bash
python3 -m opc_engine.features.script_generation.generate_product_script \
  --product-doc /path/to/product.md \
  --reference-script /path/to/competitor.md
```

## 输出

默认写入：

```text
$OPC_VAULT_ROOT/wiki/视频/纯AI视频/03产品脚本/<产品名>/
```

每次生成保存 Markdown 和原始模型响应 JSON。未勾选裂变时，同一参考脚本和国家版本已有复刻稿会默认复用，不再重复调用模型；裂变结果自动追加 `_002`、`_003`，不会覆盖已有裂变脚本。裂变请求每批最多 3 条，失败时按更小批次只补缺失编号。

爆款脚本列表可以勾选一个或多个参考脚本并点击“清除裂变脚本”，永久删除这些参考脚本产生的全部 `裂变-*.md`。删除不会影响复刻母稿、下游适配结果或视频，也不会删除同名原始响应 JSON；原始响应继续用于保留“已裂变”、累计裂变次数和历史编号，因此以后再次裂变会接着原序号生成，不会从 1 重新开始。Agent 有生成或排队任务时禁止删除。

## 代码边界

```text
opc_engine/features/script_generation/
  generate_product_script.py
  modelmesh_client.py
  script_generation_agent_web.py
  config/
```

OPC 总控制台位于相邻的 `OPC-Console`，默认端口为 `8888`。

## 统一脚本创作与适配（10006）

同一 Docker 镜像还提供新的统一入口：

```bash
python3 -m opc_engine.features.unified_script_agent.web --host 0.0.0.0 --port 10006
```

10006 只读取根目录唯一提示词 `opc_shared/prompts/unified_script_generation_adaptation_prompt.md`，按任务组合公共、复刻、裂变、产品改写和 Omni 区块。它覆盖线路 1、线路 2、线路 3，并直接写入 9995 的 Omni 适配脚本目录，不保存 `03产品脚本` 或混剪 `03复刻裂变脚本` 中间稿。当前只开放已经封版的 Omni；Grok 与 Veo 保持禁用。

首次进入页面不会自动扫描资料库。点击“扫描资料库”建立持久化索引后再选择来源脚本。复刻结果已存在且通过下游格式校验时默认复用；裂变每批最多执行 3 条，每条独立校验，失败条目缩小为单条补跑。裂变编号保存在 Docker 私有数据目录，即使删除输出文件也不会从 1 重新开始。
