# 给另一台 Mac 上 Codex 的安装提示词

请帮我安装这个片段产出程序：

1. 解压我给你的 `omni-segment-agent-mac-*.zip`。
2. 进入解压后的程序目录。
3. 确认 Docker Desktop 已安装并正在运行。
4. 执行：

```bash
chmod +x scripts/install_mac.sh
./scripts/install_mac.sh "$HOME/Documents/Obsidian Vault"
```

5. 打开 `http://127.0.0.1:9995`。
6. 如果 API Key 还没配置，进入网页里的 `API 设置` 填写。
7. 如果我要使用手动任务包，请进入 `路径设置`，把输入路径、产品参考图路径和输出路径指向任务包里的对应文件夹。

注意：

- 不要把 `.env` 上传或发给别人。
- 如果 9995 端口被占用，修改 `.env` 里的 `PORT`，然后重新执行 `docker compose up -d --build`。
