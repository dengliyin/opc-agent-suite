# OPC Console

OPC Agent Suite 的独立总控制台，默认运行在 `http://127.0.0.1:8888/`。

控制台只负责服务调度、状态检测、导航和总览，不读取或修改任何 Agent 的业务配置和产物。

## 启动

推荐从仓库根目录运行：

```bash
./scripts/start_console.sh
```

也可以直接运行：

```bash
./run_console.sh
```

## macOS 常驻运行

不建议只把控制台放入 Docker，因为控制台需要在宿主机启动 8 个独立 Agent。使用 macOS LaunchAgent 可以在用户登录后自动启动，并在控制台异常退出时自动拉起：

```bash
./scripts/install_console_launchagent.sh
```

停止本次登录会话中的控制台和全部 Agent：

```bash
./scripts/stop_all.sh
```

彻底取消控制台常驻并删除 LaunchAgent：

```bash
./scripts/uninstall_console_launchagent.sh
```

LaunchAgent 只常驻 `8888`，不会自动启动 `9991–9998`；Agent 仍由控制台按需启动。

如果仓库位于 macOS 受保护的 `Documents` 目录，需要先在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”中加入并允许 `/bin/bash`。否则 LaunchAgent 会收到 `Operation not permitted`，安装脚本会自动卸载失败服务，避免反复重启。

## 当前职责

- 展示 OPC 工作流总览。
- 启动并检测 8 个独立 Agent。
- 跳转到各 Agent 页面。
- 把所有业务操作交给对应 Agent 页面。

迁移记录见 [MIGRATION.md](MIGRATION.md)。
