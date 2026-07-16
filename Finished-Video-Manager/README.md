# 成品管理

本地网页 agent，用来查看 Obsidian 里的成品视频，以及对应产品、国家的短视频标题标签池。

## 启动

```bash
cd opc-agent-suite/Finished-Video-Manager
./run_agent.sh web
```

默认地址：

```text
http://127.0.0.1:9996
```

附加管理页：

```text
http://127.0.0.1:9996/product-id
http://127.0.0.1:9996/records
```

## 数据来源

成品视频：

```text
$OPC_VAULT_ROOT/wiki/视频/成品视频
```

优先读取 `成品视频/产品/文件.mp4`，同时兼容旧的 `成品视频/模型/日期/产品/文件.mp4`。新旧结构存在同一产品、同名文件时只展示新结构；新结构的日期取文件修改日期。

商品映射按产品编码、国家、店铺和账号类型保存，不依赖视频目录。历史发布记录和待发布队列中的旧视频路径会在读取及执行时自动解析到对应的新路径，不会批量改写历史数据。

视频标题库：

```text
$OPC_VAULT_ROOT/wiki/视频/视频标题库
```

第一版只读扫描这些文件，不会修改 Obsidian 内容。

## TikTok 发布

右侧面板顶部提供单条视频完整发布流程：

1. 从当前登录的比特浏览器子账号读取其可见窗口列表。
2. 选择当前成品视频对应的标题标签，生成发布文案。
3. 点击「手动发布」，程序只打开选中的比特浏览器窗口、进入 TikTok 上传页并上传当前视频，后续全部手动处理。
4. 点击「自动发布」，程序会清空并填写文案，自动开启 AI 生成内容标识、挂载商品链接、确认可见性为所有人，然后点击 TikTok 发布按钮。
5. TikTok 返回发布成功后，写入 `data/publish_records.json`。

每台发布电脑应登录独立的比特浏览器成员子账号，并只给该子账号授权本机负责的窗口。页面不再重复维护分组，Local API 返回的可见窗口就是本机发布账号范围。

也可以不用网页，直接运行单条发布命令：

```bash
cd opc-agent-suite/Finished-Video-Manager
./run_agent.sh publish \
  --profile-id '<BITBROWSER_PROFILE_ID>' \
  --video-path "$OPC_VAULT_ROOT/wiki/视频/成品视频/<video>.mp4" \
  --caption '<CAPTION>' \
  --product-id '<TIKTOK_PRODUCT_ID>' \
  --product-short-name '<PRODUCT_SHORT_NAME>'
```

比特浏览器需要先在本机运行，并开启默认 Local API 服务：

```text
http://127.0.0.1:54345
```

当前脚本不处理验证码、账号异常、风控提示。前端只显示比特窗口的 `id`、序号、编号、名称、平台和 URL，不返回代理账号、代理密码、Cookie 等敏感字段。

发布配置保存在：

```text
data/publish_config.json
```

账号、商品 ID 和店铺映射只保存在本机 `data/publish_config.json`，示例代码不包含真实业务配置。

发布记录保存在：

```text
data/publish_records.json
```

视频卡片上的“已发布”提示来自这个记录文件。

## 标题库格式

每个国家使用一个二级标题，标题后面直接带 5 个标签：

```markdown
## 国家：泰国 (TH)

### 标题标签池

| # | 标题 | 语言 | 标签1 | 标签2 | 标签3 | 标签4 | 标签5 |
|---|------|:--:|------|------|------|------|------|
| 1 | ตัวอย่าง标题 | TH | #标签1 | #标签2 | #标签3 | #标签4 | #标签5 |
```

如果成品视频文件名里连续出现多个国家码，只取第一个国家码。例如 `UK-BR` 会按 `UK` 处理。
