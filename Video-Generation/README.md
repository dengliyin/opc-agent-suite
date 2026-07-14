# Omni 片段产出 Agent

本地 Web agent，用按钮控制批量任务，并调用 OTU 的图片模型与 `omni_flash-10s` 生成图片和视频。图片默认优先尝试 `image-4k`，不可用时降级到 `image2`。

## 启动

### Docker 启动（推荐）

```bash
docker compose up -d --build
```

打开 `http://127.0.0.1:9995`。

同一片段产出 Agent 运行任务时仍可继续提交新功能。新任务按提交顺序进入队列，每个 Agent 同一时间只执行一个任务；强制重跑也遵循相同队列顺序。

停止服务：

```bash
docker compose down
```

Docker Compose 会读取本地 `.env`，并把 `OPC_VAULT_ROOT` 挂载到容器的 `/vault`。容器配置了 `restart: unless-stopped`，Docker 重启后会自动拉起服务。

### 其他 Mac 安装

分发给其他 Mac 时不要发送 `.env`。先打包：

```bash
./scripts/package_for_mac.sh
```

把 `dist/omni-segment-agent-mac-*.zip` 发给对方。对方解压后执行：

```bash
chmod +x scripts/install_mac.sh
./scripts/install_mac.sh "$HOME/Documents/Obsidian Vault"
```

更详细说明见 `INSTALL_OTHER_MAC.md`，也可以把 `CODEX_INSTALL_PROMPT.md` 里的提示词发给另一台 Mac 上的 Codex。

### 本地 Python 启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn agent.app:app --host 127.0.0.1 --port 9995
```

打开 `http://127.0.0.1:9995`。

## 配置

复制 `.env.example` 为 `.env`，填写 `OTU_API_KEY`。

`.env` 已被 `.gitignore` 忽略，后端日志会隐藏密钥。

## 输出

- 人物图：写回每个产品脚本所在文件夹，命名为 `<md名>-片段x-人物图.png`
- 故事版图：写回每个产品脚本所在文件夹，命名为 `<md名>-片段x-故事版.png`
- Omni 视频：写入 `VIDEO_OUTPUT_ROOT/<产品名>/<md名>-片段x-omni.mp4`

视频产出 Agent 只负责生成与导出素材。已拼接素材的成品校验和清理由 `http://127.0.0.1:9998/` 的片段合成 Agent 负责；归档列表只读取导出记录并显示“已清理”，不再提供删除媒体的入口。

## 多 SKU 产品参考图

同一产品共用脚本但有多个外观 SKU 时，脚本产品目录保持为产品名，参考图命名为：

```text
<产品名>-<SKU编码>-<SKU名称>.png
```

例如脚本目录为 `LUX-轻奢戒指/`，参考图可以命名为 `LUX-轻奢戒指-RG001-银色六爪.png`、`LUX-轻奢戒指-RG002-玫瑰金排钻.png`。页面会在产品分组内要求选择本批脚本使用的 SKU；只有一张匹配参考图时自动选择。人物图功能不依赖产品参考图，其余生成功能会在执行前校验选择。
