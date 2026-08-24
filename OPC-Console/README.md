# OPC 集合控制台（8888）

8888 是 Docker Compose 部署的统一导航和路径设置页面。它读取 9991–10005 的业务健康接口显示运行状态，并提供各 Agent 的“打开”入口。

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
