# AI+跨境电商 OPC 内容量化增长引擎

深圳科赛力量有限公司的跨境电商短视频内容生产系统。项目包含 8888 集合控制台和 12 个独立业务服务；视频下载与脚本解析统一由 9992 负责，片段合成已并入 9995。

## 唯一运行方式：Docker Compose

本项目只支持 Docker，不再提供 macOS LaunchAgent、Windows 计划任务、本机 Python 虚拟环境或 Service-Runtime 启动方式。所有容器均使用 `restart: unless-stopped`，Docker Desktop 启动后会自动恢复。

8888 负责显示状态、全局配置、程序更新和打开各 Agent。Agent 的启动、停止和自动恢复全部由 Docker Compose 管理，所以卡片中只有“打开”按钮。

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
- `VIDEO_ASSEMBLY_WORK_ROOT`：9995 片段合成的装配记录、缓存及运行资料。

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

首次启动完成后，日常更新分为两步：先用 GitHub Desktop（或 Git）手动拉取 `main` 最新代码，再运行对应系统的 `docker_up` 脚本。脚本会迁移旧配置、使用最新代码重建 Docker，并等待全部服务恢复健康。只重启 Docker Desktop 或执行 `docker compose restart` 不会重新构建镜像。

启动脚本会扫描旧 Agent 的 API 地址、模型和 API Key，把无冲突且全局尚未配置的值迁移到 `OPC_DOCKER_DATA_ROOT/config/.env`。迁移前会在 `OPC_DOCKER_DATA_ROOT/config/ai-config-backups/` 自动备份；迁移完成后写入一次性标记，后续更新不会重复执行。若旧 Agent 配置彼此冲突，请打开 8888 的“全局 API / 模型”页面选择要保留的值。

修改全局 API 或模型后，在同一页面点击该配置组的“重启”按钮。系统只重启使用该组配置的 Agent，并等待它们恢复健康；不会删除任务、配置或业务文件。重启会清除 Agent 进程内的一次性覆盖，使其重新继承全局设置。

独立 Docker 控制服务不开放宿主机端口，只接受 8888 使用私有令牌调用，用于重启应用全局 AI 配置的对应 Agent。它需要挂载 Docker Socket，因此不要把服务端口暴露到局域网或公网。

停止和重建容器不会删除外置盘中的持久数据。不要执行 `docker compose down -v`，也不要手动删除 `OPC_DOCKER_DATA_ROOT`。

## 服务端口

| 端口 | 服务 |
|---:|---|
| 8888 | 集合控制台 |
| 9992 | 视频下载与脚本解析 |
| 9993 | 脚本产出 |
| 9994 | 脚本适配 |
| 9995 | 片段产出与片段合成 |
| 9996 | 成品管理 |
| 9997 | 产品脚本改写 |
| 9999 | 钩子与 CTA 脚本适配 |
| 10000 | AI＋实拍混剪 |
| 10002 | 混剪参考视频解析 |
| 10003 | 钩子与 CTA 脚本复刻裂变 |
| 10004 | 配音 |
| 10005 | 自动发布流水线 |
| 10006 | 脚本创作与适配（线路 1–3，当前开放 Omni） |

原 9991 与 10001 采集服务已停止编排，纯 AI 和混剪线路都从 9992 的 URL 下载与解析入口开始。`Video-Collection` 与 `Hybrid-Video-Collection` 源码目录仍保留，需要恢复 FastMoss 自动采集时可重新接入。

10006 是新的统一脚本入口：线路 1 完成复刻或裂变，线路 2 先做产品改写再复刻或裂变，线路 3 完成钩子或 CTA 的复刻或裂变；三条线路都直接输出 9995 可读取的 Omni 适配稿，不再落盘普通中间脚本。Grok 与 Veo 尚未完成提示词审核，页面中保持不可选。9993、9994、9997、9999、10003 暂时保留作回退，待 10006 的真实生产任务验证稳定后再移除。

## 数据边界

- 业务输入输出：`OPC_VAULT_ROOT`
- 容器配置和 Agent 状态：`OPC_DOCKER_DATA_ROOT`
- 9995 片段合成装配记录：`VIDEO_ASSEMBLY_WORK_ROOT`
- 产品映射库：`Finished-Video-Manager/config/product_mappings.json`，属于本机数据，不应提交到 Git。
- Docker 镜像、构建缓存和容器层仍由 Docker Desktop 管理；如需迁移它们，请在 Docker Desktop 中修改磁盘映像位置。

## 常用排查

```bash
docker compose ps
./scripts/docker_health.sh
docker compose logs --tail=200 console
docker compose logs --tail=200 video-generation
```

若外置盘盘符或挂载点变化，只修改 `.env` 中的三个宿主机路径，再重新执行启动命令。不要在 Agent 内保存旧的宿主机绝对路径。
