# OPC 集合控制台（8888）

8888 是 Docker Compose 部署的统一导航和路径设置页面。它读取当前已编排业务服务的健康接口显示运行状态，并提供各 Agent 的“打开”入口。纯 AI 与混剪线路均从 9992 的视频下载与脚本解析入口开始，三条手动生产线路统一进入 10006 完成脚本创作与 Omni 适配。

10006 直接把最终 Markdown 写入纯 AI 或混剪的 `04适配脚本/omni`，9995 无需转换即可继续生成人物图、故事板和视频片段。10006 首屏只读取持久化索引，用户点击“扫描资料库”时才刷新来源脚本，避免在 Windows Docker 挂载的大资料库上自动逐文件扫描。

首页卡片只负责导航，不提供 Agent 启停控制。Agent 的常驻和自动恢复统一交给 Docker Compose 的 `restart: unless-stopped`；全局 API / 模型页面可以通过独立 Docker 控制服务重启对应 Agent，使新配置立即生效。

## 运行

在仓库根目录执行：

```bash
./scripts/docker_up.sh
```

然后打开 [http://127.0.0.1:8888/](http://127.0.0.1:8888/)。

全局路径设置保存在容器的 `/config/.env`，宿主机对应 `${OPC_DOCKER_DATA_ROOT}/config/.env`。业务文件仍存放在 `${OPC_VAULT_ROOT}`。

## 健康检查

```bash
./scripts/docker_health.sh
docker compose logs --tail=200 console
```
