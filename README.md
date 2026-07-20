# OPC Agent Suite

这是 OPC 独立本地控制台和 8 个独立 Agent 的可迁移副本。控制台运行在 `8888`，Agent 运行在 `9991` 到 `9998`。

本目录是迁移改造区。原运行目录 `/Users/kesai1/Documents/带货视频产出` 没有被安装脚本修改，仍可继续提供当前服务。

## 组件

| 端口 | 目录 | 功能 |
|---|---|---|
| 8888 | `OPC-Console` | OPC 集合控制台 |
| 9991 | `Video-Collection` | 视频采集 |
| 9992 | `Script-Analysis` | 脚本解析 |
| 9993 | `Script-Generation` | 脚本产出 |
| 9994 | `Script-Adaptation` | 脚本适配 |
| 9995 | `Video-Generation` | 视频产出 |
| 9996 | `Finished-Video-Manager` | 成品管理 |
| 9997 | `Product-Script-Rewrite` | 产品脚本改写 |
| 9998 | `Video-Assembly-hd` | 片段合成 |

## 新 Mac 安装

前置条件：

- macOS Apple Silicon。
- Python 3.12。推荐 `brew install python@3.12`。
- Vault 已通过 Syncthing 或其他方案同步到本机。
- 9998 的离线运行时已从 NAS、私有云盘或其他受控位置下载。

安装步骤：

```bash
git clone <PRIVATE_REPOSITORY_URL> opc-agent-suite
cd opc-agent-suite
cp .env.example .env
```

编辑 `.env`，至少确认：

```bash
OPC_VAULT_ROOT="$HOME/Documents/Obsidian Vault"
```

然后执行：

```bash
export OPC_VIDEO_ASSEMBLY_RUNTIME_SOURCE="/path/to/Video-Assembly-hd/runtime"
./scripts/bootstrap_macos.sh
./scripts/start_console.sh
```

打开 `http://127.0.0.1:8888/`。其余 Agent 由控制台上的“启动/检测”按钮按需启动。

### 让控制台在 macOS 常驻

控制台需要调用宿主机上的 8 个独立 Agent，因此不单独放入 Docker。安装后，`8888` 会在用户登录时自动启动并在异常退出后自动拉起；`9991` 到 `9998` 各自注册为独立 LaunchAgent，但保持按需启动：

```bash
./scripts/install_console_launchagent.sh
```

8888 的“启动”按钮通过 `launchctl kickstart -k` 恢复对应 Agent，并持续检测最多 30 秒，健康检查成功后才显示“已启动”。Agent 不再是控制台子进程，因此重启 8888 不会带走已运行的 Agent；未点击启动的 Agent 也不会在登录时自动运行。
LaunchAgent 的标准输出和错误日志位于 `~/Library/Logs/OPC-Agent-Suite/`，避免 macOS 阻止 launchd 在 `Documents` 下创建日志文件。

取消常驻：

```bash
./scripts/uninstall_console_launchagent.sh
./scripts/uninstall_agent_launchagents.sh
```

LaunchAgent 直接通过控制台的 Python 环境启动，不依赖 `/bin/bash` 读取 `Documents` 中的脚本。

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

## 依赖策略

- 控制台和所有 Agent 统一使用 Python 3.12。
- `OPC-Console` 和每个 Agent 均保留独立 `.venv`，避免控制台、Playwright、FastAPI 和视频工具相互污染。
- 每个目录的 `requirements.lock.txt` 固定直接依赖和传递依赖版本。
- `requirements.txt` 只转发到对应锁文件，旧安装命令也会得到相同版本。
- `bootstrap_macos.sh` 负责一次性创建并验证全部环境。

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

Vault 根目录统一由 `OPC_VAULT_ROOT` 提供。代码中不再依赖固定用户名路径。

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
