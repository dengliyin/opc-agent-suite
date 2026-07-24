# 片段合成智能体

独立、完全离线的产品视频片段扫描与拼接工具。

## 启动

```bash
bash scripts/start_web.sh
```

访问 `http://127.0.0.1:9998/`。

## 工作流

页面扫描以下目录：

```text
$OPC_VAULT_ROOT/wiki/视频/纯AI视频/06合成工作区
```

扫描结果分为已有成品、待拼接、已归档和异常。“待拼接”项目可以选择后拼接；“已有成品”中仍保留源素材的项目可以选择后清理。两个操作都需要独立的二次确认，扫描和拼接完成都不会自动删除素材。

确认拼接时只有两个字幕选项：

- `不生成字幕`：默认选项，保持原来的拼接速度。
- `TikTok 卡拉 OK 逐词高亮`：先生成无字幕成品，再用本地 Whisper 对齐音频时间；字幕文字优先取 Markdown 各 Segment 的 `[音频文案]`，最终烧录到 MP4。

成品输出到：

```text
$OPC_VAULT_ROOT/wiki/视频/成品视频/产品/脚本同名.mp4
```

扫描时仍会识别成品目录内旧的 `模型/日期/产品/脚本同名.mp4`，但新拼接的视频只写入产品目录。

## Agent 职责

- 片段产出 Agent 负责生成片段、图片并导出到待拼接目录。
- 片段合成 Agent 负责扫描、拼接、成品校验和已拼接素材清理。
- 清理前使用 FFprobe 确认成品有有效时长、视频轨和音频轨，并要求用户勾选“成品可以使用”。
- 清理仅删除待拼接脚本目录中的片段、图片和 `.product-lock.json`；保留 Markdown、`.exported.json` 和成品 MP4。
- 清理后导出记录写入 `upload_status: "已清理"` 和 `media_cleaned: true`。

## 离线边界

- 拼接与字幕生成不调用远程模型或 API。
- 页面不加载 CDN、远程字体或远程图片。
- 不通过 `npx`、`pnpm dlx` 或包管理器下载运行依赖。
- Node、FFmpeg、FFprobe、HyperFrames、Chrome 和 GSAP 均由本目录提供。
- 卡拉 OK 字幕使用随应用安装并缓存的 `uvx`、`mlx-whisper`、Whisper 模型和开源字体；首次使用前运行一次 `bash scripts/install_caption_runtime.sh` 完成本机安装。
- HyperFrames 的更新检查、自动安装和遥测均关闭。

## 验证

```bash
bash scripts/validate_app.sh
```
