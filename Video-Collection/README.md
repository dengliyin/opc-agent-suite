# 爆款视频收集智能体

这是一个独立的本地 CLI / Web 智能体，用于采集 FastMoss 商品关联视频并下载 TikTok 视频素材。

1. 登录 FastMoss。
2. 按国家、类目、关键词和筛选条件寻找商品。
3. 进入商品详情页的“商品关联视频”。
4. 采集视频指标和 TikTok 原始链接到 CSV。
5. 用 Kolsprite 下载无水印 MP4。
6. 按产品项目归档 CSV 和视频，并在程序日志目录保存运行报告。

## 快速开始

```bash
cd Video-Collection
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
./run_agent.sh init
```

然后编辑 `~/Library/Application Support/OPC-Agent-Suite/Video-Collection/config.json`，至少填写：

- 可选 `product.path`：手动指定产品项目目录。为空时默认使用软件目录下的 `product/`
- 可选 `product.name` 或 `product.slug`：填写后且未指定 `product.path` 时，使用 `projects/<product_slug>/`
- 可选 `output.result_folder_name`：手动指定本次结果文件夹名；默认使用 `results`
- `fastmoss.country`
- `fastmoss.category_path`
- `fastmoss.product_limit`
- `fastmoss.videos_per_product`

FastMoss 账号密码推荐用环境变量，避免写入配置文件：

```bash
export FASTMOSS_PHONE="你的手机号"
export FASTMOSS_PASSWORD="你的密码"
```

运行完整流程：

```bash
./run_agent.sh pipeline
```

只采集 CSV：

```bash
./run_agent.sh collect
```

只下载最新 CSV 里的 TikTok 视频：

```bash
./run_agent.sh download
```

检查环境和配置：

```bash
./run_agent.sh doctor
```

启动网页版可视化界面：

```bash
./run_agent.sh web
```

默认地址：

```text
http://127.0.0.1:9991
```

网页界面会在一个屏幕内展示产品项目、账号状态、采集条件、运行模式、巡检结果和实时日志。

## 输出目录

所有结果都会写入当前目录：

```text
product/
  collection_runs/<结果文件夹名>/
    <run_name>.csv
  runtime_state/
  diagnostics/
run_logs/
  <timestamp>_<mode>.md
$OPC_VAULT_ROOT/wiki/视频/纯AI视频/01来源素材/<产品名称>/
  <用户名-视频ID-标题>.mp4
  <用户名-视频ID-标题>.json
```

网页里的产品名称来自 `$OPC_VAULT_ROOT/wiki/产品/产品信息/` 下的 Markdown 文件名，自动去掉 `-产品信息`。

网页里的“结果文件夹名”可以手动填写；默认使用 `results`。采集 CSV 写入产品项目目录，下载视频写入 Obsidian 爆款视频目录。

如果在网页里填写了“产品路径”，结果会写入你手动指定的目录；路径可以是相对路径，也可以是绝对路径。未填写产品路径、产品名和 slug 时，默认写入软件所在目录的 `product/` 文件夹。

## 配置说明

首次运行 `./run_agent.sh init` 会从 `config.example.json` 创建 `~/Library/Application Support/OPC-Agent-Suite/Video-Collection/config.json`。如果软件目录中已有旧版 `config.json`，程序会在新文件不存在时自动复制一次并保留旧文件。可用 `OPC_VIDEO_COLLECTION_CONFIG_PATH` 覆盖默认位置。真实账号、产品资料和运行结果都不会提交到 Git。

`fastmoss.show_browser` 默认为 `false`，浏览器会尽量最小化运行。遇到验证码或滑块时，把它改成 `true`，手动完成验证后重跑。

类目路径支持一级、二级或三级，例如：

```json
["宠物用品", "猫狗食品"]
```

不使用类目筛选时：

```json
["全部"]
```
