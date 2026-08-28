# Video Teardown Agent

自包含的视频拆解智能体，用于把本地 `MP4 / MOV / M4V` 短视频交给 Gemini 兼容接口拆解成 Markdown 结构稿。

## 功能

- 本地 Web 可视化界面
- 批量粘贴 TikTok URL，通过 Kolsprite 下载无水印 MP4
- 下载完成后自动刷新待拆解队列，不自动消耗模型额度
- 在同一页面切换“纯 AI 视频”与“AI＋实拍混剪”；混剪继续区分钩子和 CTA
- 两条线路共用产品选择，但分别使用各自固定的输入、输出目录
- 按产品文件夹扫描视频目录和脚本目录
- 通过视频 ID 查重，跳过已拆解视频
- 支持选择全部、单个产品、多个产品或单条视频处理
- 队列逐条处理，避免并发消耗和接口限流
- 调用 Gemini 兼容接口拆解视频
- 按产品文件夹输出 Markdown 脚本
- 输出文件名前缀包含国家代码，例如 `MY-xxx.md`
- 本地编辑拆解提示词

## 目录

```text
config/
  settings.json                # Base URL、模型和运行参数，提交到 Git
  settings.local.example.json
  settings.local.json          # 仅保存 API Key，本地私有配置，不提交
  paths.example.json
  paths.local.json             # 本地业务目录配置，不提交
  video_teardown_prompt.md
  hot_content_knowledge_base.md
references/
  teardown-output-contract.md
scripts/
  analyze_video.py
  url_downloader.py
  auto_runner.py
  start_background.sh
  stop_background.sh
  status_background.sh
  web_app.py
web/
  index.html
  app.css
  app.js
inputs/                        # 本地视频，不提交
outputs/                       # 拆解结果，不提交
logs/                          # 本地日志，不提交
```

## 配置

共享的 Base URL、模型和运行参数保存在 `config/settings.json`，随 Git 同步。每台电脑只需复制密钥配置并填写自己的 API Key：

```bash
cp config/settings.local.example.json config/settings.local.json
```

也可以直接在 Web 界面填写 API Key。`settings.local.json` 只保存在本地，不要提交；网页中修改的其他模型参数会写入 `settings.json`，应正常提交。

## 启动 Web 界面

推荐使用后台托管脚本：

```bash
bash scripts/start_background.sh
```

查看状态：

```bash
bash scripts/status_background.sh
```

停止服务：

```bash
bash scripts/stop_background.sh
```

也可以直接运行 Python 服务：

```bash
python3 scripts/web_app.py --host 127.0.0.1 --port 8789
```

打开：

```text
http://127.0.0.1:8789/
```

## 命令行拆解

```bash
python3 scripts/analyze_video.py /absolute/path/to/video.mp4
```

## 默认业务目录

在 OPC Agent Suite 中，Web 队列根据页面选择的内容线路读取固定的全局环境变量：

```text
纯 AI 视频：VIDEO_TEARDOWN_INPUT_ROOT → VIDEO_TEARDOWN_OUTPUT_ROOT
AI＋实拍混剪：HYBRID_VIDEO_TEARDOWN_INPUT_ROOT → HYBRID_VIDEO_TEARDOWN_OUTPUT_ROOT
```

纯 AI 线路未提供全局环境变量时，独立运行的 9992 会回退到 `config/paths.local.json`。复制示例配置：

```bash
cp config/paths.example.json config/paths.local.json
```

然后把 `video_dir` 和 `script_dir` 改成自己的本机目录。网页不展示也不接受临时目录输入，避免两条线路串目录。纯 AI 按 `<产品名>` 归档；混剪按 `<混剪-钩子|混剪-CTA>/<产品名>` 归档。`inputs/` 和 `outputs/` 只保存手动任务副本和处理中间文件，不属于需要人工维护的业务路径。

## 输出命名

队列模式下，输出文件命名规则：

```text
<国家代码>-<原视频文件名去扩展名>.md
```

例如：

```text
MY-mamaizzshop-7569257172798803221-#vividhaircolor #vividhair.md
```

## 安全

以下内容已被 `.gitignore` 排除：

- `config/settings.local.json`
- `config/paths.local.json`
- `inputs/`
- `outputs/`
- `logs/`
- `.DS_Store`
