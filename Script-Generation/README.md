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
