# 产品脚本改写智能体

将某个产品目录中的爆款 Markdown 脚本，按目标产品信息改写后，写入目标产品在 `纯AI视频/02参考脚本` 下的子文件夹。

启动：

```bash
bash scripts/start_web.sh
```

页面地址：`http://127.0.0.1:9997/`

校验：

```bash
bash scripts/validate_app.sh
```

文件命名：

```text
<国家>-<账号>（原<来源产品文件夹全称>）-<视频ID>-<原标题>.md
```

本地密钥保存在 `agent_config/agent_secrets.local.json`，该文件已由同目录 `.gitignore` 忽略。
