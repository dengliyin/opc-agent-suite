# 爆款视频收集智能体说明

## 角色

本智能体负责从 FastMoss 找到符合条件的商品关联爆款视频，并把 TikTok 原始链接、关键指标和无水印视频文件归档到本地产品项目。

## 输入

- 产品项目：`product.name` 或 `product.slug`
- FastMoss 登录凭据：`FASTMOSS_PHONE` / `FASTMOSS_PASSWORD` 或 `~/Library/Application Support/OPC-Agent-Suite/Video-Collection/config.json`
- 采集条件：国家、关键词、类目路径、商品筛选条件
- 采集规模：商品数量、每个商品的视频数量
- 下载条件：是否下载、指定 CSV、下载数量上限

## 决策流程

1. 检查配置是否具备产品项目，避免写入错误目录。
2. 检查 FastMoss 登录态；账号或密码变化时自动清理旧登录状态。
3. 打开商品搜索页，按关键词、国家、类目和筛选条件定位商品。
4. 进入商品详情页的“商品关联视频”，采集近 28 天视频表现。
5. 逐条打开 FastMoss 视频详情页，提取 TikTok 官方视频链接。
6. 保存 CSV 到当前产品目录的 `collection_runs/<结果文件夹名>/`。
7. 读取 CSV 中的 `tiktok_video_url`，用 Kolsprite 下载无水印 MP4。
8. 按视频 ID 归档到同一结果文件夹的 `hot_sources/<video_id>/source/`。
9. 生成运行报告到同一结果文件夹的 `reports/`。

## 失败处理

- 配置缺失时直接停止，并提示需要补充的字段。
- FastMoss 出现验证码、滑块或安全策略时，开启 `fastmoss.show_browser` 后手动完成验证。
- 某条视频下载失败时记录到报告，继续处理后续视频。
- 已存在的视频不会重复下载，但会刷新 `source_metrics.json`。
