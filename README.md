# AI+跨境电商 OPC 内容量化增长引擎

深圳科赛力量有限公司的跨境电商短视频内容生产系统。项目包含 8888 集合控制台和 9991–10005 共 15 个 Agent。

## 唯一运行方式：Docker Compose

本项目只支持 Docker，不再提供 macOS LaunchAgent、Windows 计划任务、本机 Python 虚拟环境或 Service-Runtime 启动方式。所有容器均使用 `restart: unless-stopped`，Docker Desktop 启动后会自动恢复。

8888 只负责显示状态、全局路径配置和打开各 Agent。Agent 的启动、停止和自动恢复全部由 Docker Compose 管理，所以卡片中只有“打开”按钮。

### 首次配置

1. 安装 Docker Desktop，并启用“登录时启动 Docker Desktop”。
2. 复制 `.env.docker.example` 为 `.env`。
3. 设置三个宿主机目录：

```dotenv
OPC_VAULT_ROOT="/Volumes/seafer/Obsidian Vault"
OPC_DOCKER_DATA_ROOT="/Volumes/seafer/OPC-Data/docker"
VIDEO_ASSEMBLY_WORK_ROOT="/Volumes/seafer/OPC-Data/Video-Assembly-hd"
```

- `OPC_VAULT_ROOT`：业务资料库，容器内统一映射为 `/vault`。
- `OPC_DOCKER_DATA_ROOT`：Docker 持久配置和 Agent 数据。
- `VIDEO_ASSEMBLY_WORK_ROOT`：9998 的装配记录、缓存及运行资料。

外置盘未挂载时不要启动。启动脚本会验证三个目录已经存在且可写，避免误写回电脑内置盘。

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

代码更新后再次执行 `docker compose up -d --build`。停止和重建容器不会删除外置盘中的持久数据。不要执行 `docker compose down -v`，也不要手动删除 `OPC_DOCKER_DATA_ROOT`。

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
