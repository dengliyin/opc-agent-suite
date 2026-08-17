# OPC Agent Suite

这是 OPC 独立本地控制台和 15 个独立 Agent 的可迁移副本。控制台运行在 `8888`，Agent 使用 `9991–10005`。

本目录是迁移改造区。原运行目录 `/Users/kesai1/Documents/带货视频产出` 没有被安装脚本修改，仍可继续提供当前服务。

## Docker Compose 部署

Docker 部署会把控制台和 15 个 Agent 分别放入独立容器，默认只监听本机回环地址。所有容器共享同一个 Vault 挂载，但依赖和进程互相隔离。

1. 安装 Docker Desktop（或 Linux Docker Engine + Compose 插件）。
2. 从 `.env.docker.example` 复制或补全仓库根目录的 `.env`，至少把 `OPC_VAULT_ROOT` 改成宿主机上 Obsidian Vault 的绝对路径，并填写需要的 API Key。
3. 构建并启动：

```bash
docker compose up -d --build
docker compose ps
```

打开 `http://127.0.0.1:8888/`。查看日志和停止服务：

```bash
docker compose logs -f console
docker compose down
```

容器模式下，Agent 的启停由 Compose 管理，所以控制台中的启停按钮显示为“Compose 管理”。代码更新后再次执行 `docker compose up -d --build` 即可；Vault、控制台本机配置、成品管理数据和片段合成状态不会因重建容器而丢失。

`Finished-Video-Manager/config/product_mappings.json` 不会打进镜像，而是从本机以文件形式挂载，继续作为本地产品映射库使用。

9998 和 10005 镜像会固定安装 Linux Node.js 22、HyperFrames 0.7.44、FFmpeg/FFprobe 和 Playwright Chrome，并为 Chrome 分配 512MB 共享内存。构建阶段会检查四项命令；容器运行时通过 `VIDEO_ASSEMBLY_HYPERFRAMES` 和 `HYPERFRAMES_BROWSER_PATH` 使用镜像内版本，不依赖仓库里的 macOS 离线运行时。

BitBrowser 继续运行在宿主机。容器默认通过 `http://host.docker.internal:54345` 连接；如端口或地址不同，在 `.env` 中修改 `BITBROWSER_API_URL`。Docker Desktop 可直接使用该主机名，Linux Docker Engine 由 Compose 的 `host-gateway` 映射解析；同时需要确保 BitBrowser API 允许来自 Docker 网桥的连接。

成品视频管理服务（9996）也包含 FFmpeg，用于在容器内生成视频缩略图。

如果宿主机的标准端口已被本机进程占用，可用独立验证端口启动整套容器：

```bash
docker compose -f docker-compose.yml -f docker-compose.verify.yml up -d --no-build
```

验证配置把控制台映射到 `18888`，其余服务依次映射到 `19991`–`20005`，只监听本机 `127.0.0.1`。验证完成后使用相同的两个 `-f` 参数执行 `docker compose down -v`。

如需从其他电脑访问，将 `.env` 中的 `OPC_DOCKER_BIND` 设为 `0.0.0.0`，并把 `OPC_PUBLIC_HOST` 设为服务器 IP 或域名。服务本身没有统一登录保护，公网部署前应使用防火墙或带认证的反向代理限制访问。

## 组件

| 端口 | 目录 | 功能 |
|---|---|---|
| 8888 | `OPC-Console` | OPC 集合控制台 |
| 9991 | `Video-Collection` | 视频采集 |
| 9992 | `Script-Analysis` | 脚本解析 |
| 9993 | `Script-Generation` | 脚本产出 |
| 9994 | `Script-Adaptation` | 脚本适配 |
| 9995 | `Video-Generation` | 片段产出 |
| 9996 | `Finished-Video-Manager` | 成品管理 |
| 9997 | `Product-Script-Rewrite` | 产品脚本改写 |
| 9998 | `Video-Assembly-hd` | 片段合成 |
| 9999 | `Hybrid-Script-Adaptation` | 钩子与 CTA 脚本适配 |
| 10000 | `Hybrid-Video-Mixer` | AI＋实拍混剪 |
| 10001 | `Hybrid-Video-Collection` | 混剪参考视频采集 |
| 10002 | `Hybrid-Script-Analysis` | 混剪参考视频解析 |
| 10003 | `Hybrid-Script-Generation` | 钩子与 CTA 脚本复刻裂变 |
| 10004 | `Hybrid-Audio-Generation` | 配音 |
| 10005 | `Auto-Publish-Pipeline` | 自动发布流水线 |

## 新 Mac 安装

前置条件：

- macOS Apple Silicon。
- Python 3.12。推荐 `brew install python@3.12`。
- Vault 已通过 Syncthing 或其他方案同步到本机。
- 9998 的离线运行时已从 NAS、私有云盘或其他受控位置下载。

安装步骤：

```bash
git clone https://github.com/dengliyin/opc-agent-suite.git opc-agent-suite
cd opc-agent-suite
cp .env.example .env
```

编辑仓库 `.env`，至少确认以下初始值。首次安装后，实际运行配置统一保存到 `~/Library/Application Support/OPC-Agent-Suite/.env`：

```bash
OPC_VAULT_ROOT="/path/to/Obsidian Vault"
```

仓库内的 `storage-template/` 只保存空目录结构，不包含任何业务数据。首次安装时会建立这些目录；之后每次启动控制台或任一 Agent，也会根据统一运行配置中的 `OPC_VAULT_ROOT` 自动补齐新增目录，只创建缺失目录，不覆盖已有文件。

需要主动补建输入/输出目录时，也可以单独执行：

```bash
./scripts/create_storage_layout.sh
```

首次安装时 `bootstrap_macos.sh` 会执行这一步。运行期自动补齐要求 `OPC_VAULT_ROOT` 已存在且可写；如果外接盘未挂载或路径配置错误，程序会停止并明确报错，避免在错误位置创建空目录。

然后执行：

```bash
export OPC_VIDEO_ASSEMBLY_RUNTIME_SOURCE="/path/to/Video-Assembly-hd/runtime"
./scripts/bootstrap_macos.sh
./scripts/start_console.sh
```

`bootstrap_macos.sh` 会创建全部 Python 环境，并自动安装 15 个按需运行的 Agent LaunchAgent 配置；`start_console.sh` 每次启动时也会检查并补齐这些配置。打开 `http://127.0.0.1:8888/` 后，其余 Agent 可由控制台上的“启动/检测”按钮按需启动。

如果旧副本已经完成环境安装，但曾出现“Agent LaunchAgent 配置不存在”，可单独执行一次：

```bash
./scripts/install_agent_launchagents.sh
```

### 让控制台在 macOS 常驻

控制台需要调用宿主机上的 15 个独立 Agent，因此不单独放入 Docker。安装后，`8888` 会在用户登录时自动启动并在异常退出后自动拉起；15个Agent各自注册为独立LaunchAgent，但保持按需启动：

```bash
./scripts/install_console_launchagent.sh
```

8888 的“启动”按钮通过 `launchctl kickstart -k` 恢复对应 Agent，并持续检测最多 30 秒，健康检查成功后才显示“已启动”。Agent 不再是控制台子进程，因此重启 8888 不会带走已运行的 Agent；未点击启动的 Agent 也不会在登录时自动运行。
安装器会把控制台和 Agent 的运行副本同步到 `~/Library/Application Support/OPC-Agent-Suite/Service-Runtime/`。LaunchAgent 只从这里读取程序和 Python 环境，避免 macOS 间歇性阻止后台进程读取 `Documents`。业务输入输出仍全部指向 `OPC_VAULT_ROOT`；每个 Agent 在运行副本内产生的本机配置和状态会在后续更新时保留。

LaunchAgent 的标准输出和错误日志位于 `~/Library/Logs/OPC-Agent-Suite/`。

取消常驻：

```bash
./scripts/uninstall_console_launchagent.sh
./scripts/uninstall_agent_launchagents.sh
```

LaunchAgent 直接通过各自运行副本中的 Python 环境启动，不依赖 `/bin/bash`，也不读取 `Documents` 中的程序文件。

检查服务：

```bash
./scripts/healthcheck.sh --console-only
./scripts/healthcheck.sh --all
```

停止本副本启动的控制台和 Agent：

```bash
./scripts/stop_all.sh
```

停止脚本只终止命令行中包含当前副本绝对路径的进程，不会终止其他目录运行的同端口程序。

## Windows 安装

Windows 与 macOS 共用同一套 Agent 业务代码，但各自使用独立的本机配置、Python 环境和服务管理方式。当前 Windows 安装目标为 Windows 10/11 x64、PowerShell 5.1 或更高版本；暂不支持 Windows ARM64。

在 Windows 上通过 Git 克隆或更新代码，不要从 Mac 复制 `.venv`、`.env`、`Video-Assembly-hd/runtime` 或浏览器目录。首次安装请打开普通用户 PowerShell，在仓库根目录执行：

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -VaultRoot "D:\Obsidian Vault"
```

安装器会在需要时通过 `winget` 安装 Python 3.12，并完成以下工作：

- 将服务运行副本放到 `%LOCALAPPDATA%\OPC-Agent-Suite\Service-Runtime`。
- 为控制台和 15 个 Agent 创建 16 个互相隔离的 Python 环境。
- 安装 Playwright Chromium，以及 9998 使用的 Windows x64 Node.js、FFmpeg、FFprobe、HyperFrames、浏览器和 `faster-whisper` 字幕环境。
- 在 Windows 任务计划程序的 `\OPC-Agent-Suite\` 目录注册 16 个任务。
- 让 `console-8888` 登录后自动启动，异常退出后自动恢复；9991–10005 不设置登录触发器，只能由 8888 或任务计划程序按需启动。

Windows 的真实配置文件是 `%LOCALAPPDATA%\OPC-Agent-Suite\.env`，日志目录是 `%LOCALAPPDATA%\OPC-Agent-Suite\Logs`。外置盘盘符或资料库位置变化后，只修改这份 `.env` 或进入 8888 的“全局路径设置”，不要修改代码中的默认值。控制台和 Agent 启动前都会验证 `OPC_VAULT_ROOT` 可读写；外置盘暂时断开时会等待恢复，不会回退到旧路径创建资料。

安装完成后可使用：

```powershell
# 启动或恢复 8888，并打开控制台
PowerShell -ExecutionPolicy Bypass -File .\scripts\start_console_windows.ps1

# 只检查 8888
PowerShell -ExecutionPolicy Bypass -File .\scripts\healthcheck_windows.ps1 -ConsoleOnly

# 检查 8888 和当前应当已启动的所有 Agent
PowerShell -ExecutionPolicy Bypass -File .\scripts\healthcheck_windows.ps1

# 移除 16 个计划任务，默认保留配置、日志和运行副本
PowerShell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows.ps1

# 连同运行副本和本机配置一起删除
PowerShell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows.ps1 -RemoveRuntime -RemoveConfiguration
```

如果只想安装基础程序、稍后再下载体积较大的浏览器或 Whisper 模型，可在首次安装时使用 `-SkipPlaywrightBrowserInstall`、`-SkipHyperFramesBrowserInstall` 或 `-SkipWhisperModelDownload`；相应功能在补装运行环境前不可用。

更新 Windows 程序时先拉取 Git 代码，再重新运行同一条 `bootstrap_windows.ps1` 命令。它会更新服务运行副本和依赖，同时保留 `%LOCALAPPDATA%\OPC-Agent-Suite\.env`、日志以及各 Agent 的本机状态。Mac 继续使用 LaunchAgent，Windows 使用计划任务，两套系统互不覆盖本机配置和业务资料。

## 依赖策略

- 控制台和所有 Agent 统一使用 Python 3.12。
- `OPC-Console` 和每个 Agent 均保留独立 `.venv`，避免控制台、Playwright、FastAPI 和视频工具相互污染。
- 每个目录的 `requirements.lock.txt` 固定直接依赖和传递依赖版本。
- `requirements.txt` 只转发到对应锁文件，旧安装命令也会得到相同版本。
- `bootstrap_macos.sh` 和 `bootstrap_windows.ps1` 分别负责一次性创建并验证本机环境。

Playwright 默认安装与锁定版本匹配的 Chromium。网络较慢、且本机确定有可用浏览器时，可临时跳过：

```bash
OPC_SKIP_PLAYWRIGHT_BROWSER_INSTALL=1 ./scripts/bootstrap_macos.sh
```

## 配置与数据边界

可以进入 Git：

- Python、HTML、CSS、JavaScript 源码。
- 提示词、知识库和不含密钥的共享配置，包括 Base URL、模型、端口和运行参数。
- `requirements.lock.txt`、安装脚本和文档。
- `Video-Assembly-hd/vendor/gsap.min.js`。

不能进入 Git：

- `.env`、API Key、Token、登录账号密码和本机 `*.local.json`。
- Vault 内容、视频、图片、日志、SQLite、浏览器 profile 和运行输出。
- 各 Agent 的 `.venv`。
- `Video-Assembly-hd/runtime`。该目录约 832 MB，并包含超过 GitHub 单文件限制的二进制。

Vault 根目录统一由本机配置中的 `OPC_VAULT_ROOT` 提供：macOS 位于 `~/Library/Application Support/OPC-Agent-Suite/.env`，Windows 位于 `%LOCALAPPDATA%\OPC-Agent-Suite\.env`。代码中不再依赖固定用户名或盘符，也不会在配置缺失时猜测旧目录。

模型配置统一规则：视频拆解使用 `Script-Analysis/config/settings.json`，脚本产出使用 `Script-Generation/opc_engine/features/script_generation/config/model_defaults.json`，脚本适配和产品脚本改写使用各自的 `agent_settings.json`，视频生成使用 `Video-Generation/agent_settings.env`。这些文件随 Git 同步；另一台电脑只需填写各 Agent 的 API Key 和本机路径。

## 9998 离线运行时

运行时不放 Git。安装目录或压缩包：

```bash
./scripts/install_video_assembly_runtime.sh /path/to/runtime
./scripts/install_video_assembly_runtime.sh /path/to/runtime.tar.gz
```

安装器会验证 Node、FFmpeg、FFprobe、HyperFrames 和离线 Chrome，拒绝与当前 Mac 架构不匹配的二进制，并要求 FFmpeg/FFprobe 版本一致。

## 验证

重复运行以下命令不会覆盖 `.env`，并会重新检查锁定依赖：

```bash
./scripts/bootstrap_macos.sh
./scripts/verify_install.sh
```

完整审计结果见 [DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md)。
