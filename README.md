# AI+跨境电商 OPC 内容量化增长引擎

深圳科赛力量有限公司的跨境电商短视频内容生产系统。项目包含 8888 集合控制台和 9991–10005 共 15 个 Agent。

## 唯一运行方式：Docker Compose

本项目只支持 Docker，不再提供 macOS LaunchAgent、Windows 计划任务、本机 Python 虚拟环境或 Service-Runtime 启动方式。所有容器均使用 `restart: unless-stopped`，Docker Desktop 启动后会自动恢复。

8888 只负责显示状态、全局路径配置和打开各 Agent。Agent 的启动、停止和自动恢复全部由 Docker Compose 管理，所以卡片中只有“打开”按钮。

### 首次配置

1. 安装 Docker Desktop，并启用“登录时启动 Docker Desktop”。
2. 直接运行对应系统的启动脚本。首次启动会自动选择代码仓库所在盘，在仓库的上一级目录创建 `.env` 中的三个存储路径。例如代码位于 `/Volumes/seafer/opc-agent-suite`，则默认为：

```dotenv
OPC_VAULT_ROOT="/Volumes/seafer/Obsidian Vault"
OPC_DOCKER_DATA_ROOT="/Volumes/seafer/OPC-Data/docker"
VIDEO_ASSEMBLY_WORK_ROOT="/Volumes/seafer/OPC-Data/Video-Assembly-hd"
```

已有 `.env` 时启动脚本不会修改或覆盖。如需使用其他存储位置，再手动修改这三个值。

- `OPC_VAULT_ROOT`：业务资料库，容器内统一映射为 `/vault`。
- `OPC_DOCKER_DATA_ROOT`：Docker 持久配置和 Agent 数据。
- `VIDEO_ASSEMBLY_WORK_ROOT`：9998 的装配记录、缓存及运行资料。

启动脚本会在已挂载且可写的上一级目录或盘符下自动创建这三个根目录，并根据 `storage-template` 补齐空白业务资料库结构和根目录 `CLAUDE.md`。重复启动只补充缺失目录和缺失模板文件，不会覆盖已有文件。外置盘未挂载时脚本会拒绝创建和启动，避免误写回电脑内置盘。

### 启动、停止和检查

macOS/Linux：

```bash
./scripts/docker_up.sh
./scripts/docker_health.sh
./scripts/docker_stop.sh
```

Windows PowerShell：

```powershell
.\scripts\docker_up.ps1
.\scripts\docker_health.ps1
.\scripts\docker_stop.ps1
```

启动后打开 [http://127.0.0.1:8888/](http://127.0.0.1:8888/)。

代码更新后仍应再次执行对应系统的 `docker_up` 启动脚本，不要绕过脚本直接启动。脚本会在构建前扫描旧 Agent 的 API 地址、模型和 API Key，把无冲突且全局尚未配置的值迁移到 `OPC_DOCKER_DATA_ROOT/config/.env`。迁移前会在 `OPC_DOCKER_DATA_ROOT/config/ai-config-backups/` 自动备份；迁移完成后写入一次性标记，后续更新不会重复执行。若旧 Agent 配置彼此冲突，请打开 8888 的“全局 API / 模型”页面选择要保留的值。

停止和重建容器不会删除外置盘中的持久数据。不要执行 `docker compose down -v`，也不要手动删除 `OPC_DOCKER_DATA_ROOT`。

## 服务端口

| 端口 | 服务 |
|---:|---|
| 8888 | 集合控制台 |
| 9991 | 视频采集 |
| 9992 | 脚本解析 |
| 9993 | 脚本产出 |
| 9994 | 脚本适配 |
| 9995 | 片段产出 |
| 9996 | 成品管理 |
| 9997 | 产品脚本改写 |
| 9998 | 片段合成 |
| 9999 | 钩子与 CTA 脚本适配 |
| 10000 | AI＋实拍混剪 |
| 10001 | 混剪参考视频采集 |
| 10002 | 混剪参考视频解析 |
| 10003 | 钩子与 CTA 脚本复刻裂变 |
| 10004 | 配音 |
| 10005 | 自动发布流水线 |
| 15991 | 9991 可视浏览器 |
| 16001 | 10001 可视浏览器 |

9991 和 10001 勾选“显示浏览器”后，开始任务时会自动打开对应的 Docker 浏览器画面，可手动处理登录、验证码和滑块。未勾选时使用无头模式。

## 数据边界

- 业务输入输出：`OPC_VAULT_ROOT`
- 容器配置和 Agent 状态：`OPC_DOCKER_DATA_ROOT`
- 9998 旧装配记录：`VIDEO_ASSEMBLY_WORK_ROOT`
- 产品映射库：`Finished-Video-Manager/config/product_mappings.json`，属于本机数据，不应提交到 Git。
- Docker 镜像、构建缓存和容器层仍由 Docker Desktop 管理；如需迁移它们，请在 Docker Desktop 中修改磁盘映像位置。

## 常用排查

```bash
docker compose ps
./scripts/docker_health.sh
docker compose logs --tail=200 console
docker compose logs --tail=200 video-assembly
```

若外置盘盘符或挂载点变化，只修改 `.env` 中的三个宿主机路径，再重新执行启动命令。不要在 Agent 内保存旧的宿主机绝对路径。
