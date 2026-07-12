# 依赖与可重复安装审计

审计日期：2026-07-12  
审计副本：`/Users/kesai1/Documents/opc-agent-suite`  
原运行目录：`/Users/kesai1/Documents/带货视频产出`（只读保留）

## 结论

本套程序不应合并成一个共享虚拟环境。正确的统一方式是：统一 Python 版本、统一安装入口、每个 Agent 独立锁定环境。

已确定 Python 3.12 为迁移基线，并为 8 个 Agent 建立独立 `requirements.lock.txt` 和 `.venv`。隔离安装、自动化测试、控制台启动 Agent 和 HTTP 健康检查均已通过。

## 依赖清单

| 端口 | Agent | Python 依赖 | 系统或外部依赖 |
|---|---|---|---|
| 9991 | 视频采集 | Playwright 1.60.0 | Chromium 或 Google Chrome、FastMoss、Kolsprite |
| 9992 | 脚本解析 | 标准库 | ModelMesh/Gemini 兼容 API；使用 `cgi`，暂不支持 Python 3.13 |
| 9993 | 脚本产出 | Playwright 1.60.0、openpyxl 3.1.5 | 模型 API；部分归因功能需要浏览器 |
| 9994 | 脚本适配 | openpyxl 3.1.5 | ModelMesh 兼容 API |
| 9995 | 视频产出 | FastAPI、Uvicorn、HTTPX、Pydantic、Pillow | OTU/Grok API |
| 9996 | 成品管理 | Playwright 1.60.0 | SQLite 标准库、比特浏览器 Local API、TikTok |
| 9997 | 产品脚本改写 | 标准库 | DeepSeek/ModelMesh 兼容 API |
| 9998 | 片段合成 | 标准库 | 离线 Node、FFmpeg、FFprobe、Chrome、HyperFrames、GSAP |

控制台 8888 使用 `Script-Generation/.venv`，启动 Agent 时会选择对应目录的 `.venv/bin/python`，不会借用控制台解释器。

## 已完成改造

- 新增顶层 `.env.example`，Vault 统一使用 `OPC_VAULT_ROOT`。
- 清理代码和文档中的固定用户名路径。
- 私密账号、商品 ID、日志和本机生成索引不进入迁移副本源码。
- 新增 `bootstrap_macos.sh`、`start_console.sh`、`stop_all.sh`、`healthcheck.sh` 和 `verify_install.sh`。
- 控制台根据 Agent URL 提取端口，因此可在不占用原服务端口的情况下做隔离联调。
- 8888 和 9991 到 9998 均使用各自副本内的解释器启动。
- 9998 运行时由独立安装器注入，不进入 Git。

## 验证记录

- Python：3.12.13 arm64。
- 8 个虚拟环境：全部通过 `pip check`。
- Playwright 1.60.0：已使用本机 Google Chrome 150 完成无头启动/关闭冒烟测试。
- Python 源码：全部通过 `compileall`。
- 成品管理：11 项测试通过。
- 视频产出：65 项测试通过。
- 片段合成：7 项测试通过。
- 隔离端口：18888、19991 到 19998 全部返回 HTTP 200。
- 进程检查：9 个服务均使用 `/Users/kesai1/Documents/opc-agent-suite/.../.venv/bin/python`。
- 原端口：8888、9991 到 9998 在隔离测试后仍全部返回 HTTP 200。
- Git 排除模拟：215 个候选源码文件，共 2.48 MiB；无超过 50 MiB 的候选文件。
- `.env`、SQLite、运行日志和 9998 runtime 均已确认被忽略。
- 必需提示词和本地 GSAP 文件均已确认不会被误忽略。
- 临时本地 Git 仓库完成真实 `git clone`；clone 中没有 `.env`、`.venv` 或 runtime。
- 在 clone 中重新创建全部环境、注入 runtime 并再次通过 83 项测试。
- clone 的 28888、29991 到 29998 全部返回 HTTP 200；测试进程和临时 clone 已清理。
- 9998 的 FFprobe 已替换为 7.1 arm64，并与现有 FFmpeg 7.1 的编译参数和库版本对齐。
- 新 FFprobe 已通过生成样本和真实成品视频探测，均正确返回时长、视频流和音频流。

## 风险与待办

### 1. FFprobe 架构不统一（已解决）

隔离副本当前 9998 运行时中：

- Node：arm64，约 114 MB。
- FFmpeg：7.1 arm64，约 47 MB。
- FFprobe：7.1 arm64，约 47 MB。
- Chrome Headless Shell：arm64，约 155 MB。

配套二进制来自 OSXExperts 的 [`ffmpeg71arm.zip`](https://www.osxexperts.net/ffmpeg71arm.zip) 和 [`ffprobe71arm.zip`](https://www.osxexperts.net/ffprobe71arm.zip)。下载的 FFmpeg SHA-256 与原运行时 FFmpeg 完全一致，因此采用同版本配套 FFprobe：

- FFmpeg：`6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617`
- FFprobe：`df2684842eca145bd72f4724ce9cecbf38558a4d64b2aef7846680f877702baa`

旧 4.4 x86_64 FFprobe 已保存在隔离副本的 `.runtime/backups/Video-Assembly-hd/`，不会进入 Git。原运行目录按隔离原则保持不变。

### 2. 运行时不能直接放 GitHub

9998 runtime 仍是独立大目录，Node 和 Chrome 单文件超过 GitHub 普通 Git 的 100 MB 限制。应放在 NAS、私有对象存储或独立云盘，并通过校验和或版本号管理。Git 仓库只保存安装器。

### 3. Playwright 浏览器下载

锁定版本的 Chromium 安装入口已经加入。此次审计中 CDN 下载速度异常，验证时使用 `OPC_SKIP_PLAYWRIGHT_BROWSER_INSTALL=1` 跳过完整下载；Python Playwright 包已安装并通过依赖检查。新电脑首次安装时应保持默认行为，等待 Chromium 安装完成，或明确配置系统 Chrome。

### 4. 外部业务链路未执行

本次没有调用付费模型、登录 FastMoss、发布 TikTok、修改 Vault 内容或执行真实视频拼接。验证范围是依赖安装、导入、自动化测试、页面启动、路径解析和服务编排。

### 5. 非 Git 数据仍需单独同步

Vault、浏览器登录状态、比特浏览器配置和 9998 runtime 不属于源码。Vault 可继续使用 Syncthing；浏览器状态和运行时应采用单独备份/分发策略。
