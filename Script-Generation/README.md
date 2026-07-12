# OPC 内容量化增长引擎

本地脚本产出独立 agent，用于从已有产品信息 Markdown 和参考爆款脚本/拆解稿生成产品带货视频脚本。

## 启动

第一次使用时，可以从示例配置创建本地配置：

```bash
cp app_config.example.json app_config.json
```

脚本产出 agent 的输入配置保存在 `opc_engine/features/script_generation/config/inputs.json`，模型配置保存在 `opc_engine/features/script_generation/config/model_settings.json`。这些文件只保留在本机，不提交 Git。

```bash
./run_kesai_app.sh
```

启动后会自动打开：

```text
http://127.0.0.1:9993/
```

`9993` 现在只运行脚本产出独立 agent，不再承载 OPC 混合主控页面。

## 脚本产出资产结构

脚本产出 agent 从已有产品信息 Markdown 中确认本次要处理的产品：

```text
$OPC_VAULT_ROOT/wiki/产品/产品信息
```

页面保存的脚本产出状态在：

```text
opc_engine/features/script_generation/config/inputs.json
```

各 agent 的输入/输出目录按知识库分区，再按产品名建子文件夹，例如爆款视频、爆款脚本、产品脚本、适配脚本和视频片段目录分别放在对应的 Obsidian 知识库目录下。旧 `projects/` 目录和旧配置仍保留给兼容入口使用，不迁移、不删除、不作为新主流程要求。

前端统一用项目相对路径展示本项目内的文件和目录，例如 `projects/<product>/...` 或 `knowledge_base/...`；只有外部选择的非项目文件才显示电脑绝对路径。点击“打开文件/目录”时，程序会自动解析到真实本机路径。

## 程序代码结构

统一控制台是适配层。当前推荐的最新 agent 入口如下：

| 控制台页面 | 最新 agent | 调用方式 |
| --- | --- | --- |
| 视频采集 | `../tkfastmoss` | 生成临时 `tkfastmoss` 配置后调用 `run_agent.sh --config <temp> pipeline` |
| 脚本解析 | `../video-teardown-agent` | 调用 `scripts/analyze_video.py <视频/目录> --output-dir <产品脚本目录>` |
| 脚本产出 | `opc_engine/features/script_generation` | 当前项目内最新脚本产出模块，支持产品 Markdown + 参考爆款脚本直接生成 |
| 脚本适配 | `~/.codex/skills/script-adaptation-agent` | 调用新版 skill 包内 `script_adaptation_agent --stage adapt --script-file <md> --execute` |
| 视频产出 | `../Video-Generation` | 先同步路径到 `http://127.0.0.1:9995/settings/api/paths`，再触发 Omni/Grok/Sora 片段产出 |

旧 `opc_engine/features/hot_collection`、旧 `video_teardown`、旧 `script_adaptation.content_workflow_stage` 仍保留作为 legacy/debug 兼容代码，不再作为统一控制台主运行入口。

```text
opc_engine/
  core/                  # 产品项目、路径归档、本地资产管理
  features/
    hot_collection/      # 爆款采集、FastMoss、Kolsprite 下载
    video_teardown/      # 爆款视频拆解
    script_generation/   # 脚本产出
    script_adaptation/   # 脚本适配、视频生成/发布/归因/优化框架
    data_attribution/    # 自然流数据和投放数据下载
  tools/                 # 迁移、整理等维护工具
projects/                # 本地业务产物，不提交 Git
knowledge_base/          # 本地共用知识库，不提交 Git
workflow_configs/        # 各功能独立输入和提示词配置，不提交 Git
```

legacy/debug 命令示例：

```bash
python3 -m opc_engine.features.script_generation.generate_product_script
```

## 使用流程

1. 进入「总览」页面了解完整循环，或直接点击对应功能按钮跳转。
2. 在任意 agent 页面选择已有产品信息 Markdown，确认这个 agent 当前处理的产品。
3. 切换到「爆款采集」页面，填写账号、密码、可选关键词、国家/地区、三级类目、商品链接数量、每商品视频数量。
4. 点击「保存设置」。
5. 点击「一键采集」。
6. 在日志区域查看执行进度。默认启动后最小化浏览器窗口，你主要看日志即可。
7. 一键采集会先生成 CSV，再读取 CSV 的 `tiktok_video_url` 自动下载视频。
8. 切换到「视频拆解」页面，先选择产品 Markdown，再选择本地 MP4 或视频目录，把竞品爆款视频拆解成结构化脚本。
9. 切换到「脚本产出」页面，选择参考爆款拆解结果，结合「产品信息」生成自家产品带货脚本。
10. 切换到「脚本适配」页面，调用 ModelMesh / Gemini 文本模型，把成品脚本适配成 Veo 等视频生成模型可用的片段文案、镜头指令和首帧图提示词。
11. 切换到「视频生成」页面，当前仅使用流程框架整理已有片段目录和生成清单，未接入真实视频生成模型。
12. 切换到「视频发布」页面，当前仅使用流程框架生成发布计划/记录，未接入 TikTok 自动发布。
13. 切换到「数据归因」页面，分两个阶段处理：先分别下载自然流数据和投放数据，再把同一作品的两类数据合并成作品归因表。
14. 切换到「脚本优化」页面，根据同一脚本产出的所有视频数据做加权评估并产出优化建议。
15. 如果遇到验证码或滑块，勾选「显示浏览器窗口」后重新运行，在弹出的浏览器里手动完成验证。

## 功能与实现状态

| 功能 | 当前实现状态 | 主要产物 |
| --- | --- | --- |
| 总览 | 已实现，本地首页一屏展示完整闭环和功能入口 | `/` |
| 产品信息 | 已实现，本地保存产品资料，并同步生成可打开的本地 Markdown 文件 | `projects/<product>/product_profile/` |
| 爆款采集 | 已实现，自动采集商品关联视频数据并下载视频 | `projects/<product>/collection_runs/`、`hot_sources/<source_id>/source/` |
| 视频拆解 | 已实现，调用 ModelMesh / Gemini 拆解本地 MP4 | `hot_sources/<source_id>/teardown/` |
| 脚本产出 | 已实现，调用 ModelMesh / Gemini 生成自家产品带货脚本 | `hot_sources/<source_id>/scripts/` |
| 脚本适配 | 已实现，调用 ModelMesh / Gemini 文本模型生成适配结果；不调用视频生成模型 | `hot_sources/<source_id>/adaptations/` |
| 视频生成 | 流程框架已搭建，未接入实际视频生成模型和完整自动剪辑链路；仅生成清单/可选本地合并已有片段 | `hot_sources/<source_id>/generated_videos/` |
| 视频发布 | 流程框架已搭建，未接入 TikTok 自动登录、账号授权和自动发布；仅生成发布计划/记录 | `hot_sources/<source_id>/publish_records/` |
| 数据归因 | 已实现为两阶段框架：阶段一分别下载自然流与投放数据，阶段二按作品ID合并归因 | `raw_data/`、`product_level_reports/data_attribution/` |
| 脚本优化 | 已实现为数据驱动优化建议框架，尚未自动重写新脚本 | `hot_sources/<source_id>/optimizations/` |

完整闭环可以理解为：

```text
产品信息
→ 爆款采集
→ 视频拆解
→ 脚本产出
→ 脚本适配
→ 视频生成
→ 视频发布
→ 数据归因
→ 脚本优化
→ 回到下一轮脚本产出/适配/发布测试
```

现在真正会调用外部模型的阶段是「视频拆解」「脚本产出」和「脚本适配」。其中「脚本适配」只调用文本模型生成适配后的片段文案、镜头指令和首帧图提示词，不调用 Veo、可灵或其他视频生成模型。

## 功能输入 / 输出协议

统一控制台的总协议是：agent 是代码边界，不是产品入口边界。页面只保存统一控制台配置，运行时把产品 Markdown、输入路径、输出路径、模型选择和运行偏好转换成临时参数或临时配置快照，再调用原 agent 模块。旧 agent 配置文件不作为本次重构对象。

| 功能 | 输入协议 | 输出协议 | 下游消费 |
| --- | --- | --- | --- |
| 总览 | 不需要业务输入；读取当前本地状态用于导航展示。 | 不产生业务文件，只提供功能入口。 | 引导进入产品信息、爆款采集、视频拆解等页面。 |
| 产品信息 | 已有产品信息 Markdown，或页面内临时维护的产品资料字段。 | 统一控制台状态：`workflow_configs/unified_console/config/inputs.json`；产品原文仍来自产品信息 Markdown 库。 | 后续各 agent 的产品确认来源；不要求创建 `projects/<product>`。 |
| 爆款采集 | 产品 Markdown；FastMoss 账号密码；可选关键词；国家/地区；一级/二级/三级类目；店铺类型、商品类型、商品状态和筛选条件；商品链接数量；每商品视频数量。 | 统一控制台生成临时 `tkfastmoss` 配置并调用最新版采集 agent；视频产物按 agent 输出目录进入对应产品子目录，旧入口仍可写入 `projects/`。 | 视频拆解读取下载 MP4；脚本产出可继续引用同一爆款来源。 |
| 视频拆解 | 产品 Markdown；单个 MP4 或 MP4 目录；ModelMesh API Key、Base URL、模型；爆款视频拆解提示词；爆款内容知识库路径。 | 拆解 Markdown 输出到统一控制台推断的脚本解析输出目录；旧入口配置不被覆盖。 | 脚本产出选择拆解 Markdown 作为参考爆款案例。 |
| 脚本产出 | 产品信息 Markdown；参考竞品爆款脚本/拆解 Markdown；可选视频总时长；复刻提示词；当前产品错题本；可选「是否裂变」。 | 成品带货脚本：`$OPC_VAULT_ROOT/wiki/视频/05产品视频脚本/<产品名>/...`；原始模型响应随脚本输出保存。 | 脚本适配读取成品脚本；脚本优化后续读取同一脚本并结合数据归因结果。 |
| 脚本适配 | 产品 Markdown；成品脚本 Markdown；ModelMesh API Key、Base URL、文本模型；目标视频生成模型；单片段时长上限。 | 调用最新版 `script-adaptation-agent`，输出完整适配 Markdown、故事版 JSON、视频批量生成 CSV。 | Omni/Sora/Grok/Veo 等下游视频产出模型可直接使用的片段文案、镜头指令、首帧图或宫格图提示词。 |
| 视频生成 | 产品 Markdown；适配后的脚本目录；目标模型 Omni/Sora/Grok；输出目录。 | 调用最新版 `Video-Generation` 片段产出 agent，生成图片、故事版图和视频片段。 | 人工检查、后续剪辑和发布流程读取。 |
| 视频发布 | 产品 Markdown；待发布视频路径；TikTok 账号别名；标题/文案；标签；发布模式。当前是流程框架，不自动发布。 | 继续复用原模块的发布计划/记录输出逻辑；统一控制台只传临时运行参数。 | 数据归因阶段用于理解发布计划；后续接入真实发布接口。 |
| 数据归因 | 产品 Markdown；阶段一输入为自然流账号分组和投放数据下载配置；阶段二读取自然流与投放数据表。 | 继续复用原模块的数据下载、归因 CSV 和分析记录输出逻辑；统一控制台只传临时运行参数。 | 脚本优化读取归因 CSV，按作品/脚本评估播放、互动、点击、成交和投放表现。 |
| 脚本优化 | 产品 Markdown；原始成品脚本；数据归因 CSV；优化备注。 | 继续复用原模块的优化建议输出逻辑；统一控制台只传临时运行参数。 | 下一轮脚本产出、脚本适配和视频测试。 |

旧入口仍然保留自己的本地输入配置文件，保存路径为：

```text
workflow_configs/product_info/config/inputs.json
workflow_configs/hot_collection/config/inputs.json
workflow_configs/video_teardown/config/inputs.json
opc_engine/features/script_generation/config/inputs.json
workflow_configs/script_adaptation/config/inputs.json
workflow_configs/video_generation/config/inputs.json
workflow_configs/video_publish/config/inputs.json
workflow_configs/data_attribution/config/inputs.json
workflow_configs/script_optimization/config/inputs.json
```

统一控制台页面显示的是统一配置文件路径 `workflow_configs/unified_console/config/inputs.json`。自动化出问题时，可以打开这个文件查看当前页面选择；如果要调试旧独立入口，再查看对应 agent 自己的 `inputs.json`。

提示词类功能还有一条额外协议：页面上的结构化字段负责变量输入，提示词文件只维护执行规则和输出格式。三个核心提示词也已经按功能拆开存储：

```text
workflow_configs/video_teardown/config/video_teardown_prompt.md
opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md
opc_engine/features/script_generation/config/script_generation_mutation_prompt.md
workflow_configs/script_adaptation/config/script_adaptation_prompt.md
```

脚本生成模块的提示词作为该智能体能力放在模块目录内；当前产品错题本从 Obsidian 的 `07错题本` 目录按产品名读取。真实运行输入和模型密钥写入各自的 ignored 本地配置文件。也就是说，复刻提示词不再重复写产品信息、竞品参考和可选总时长；目标语言、钩子节奏和音频情绪直接从竞品爆款参考中复刻。裂变提示词也在同一模块目录内，用于在脚本产出后替换人物设定、场景环境、服饰道具和画面表象，同时保留镜头语言、情绪张力、视觉奇观和叙事结构。脚本适配提示词不再重复写成品脚本、目标模型和片段时长。每个功能页都展示自己的提示词文件路径，可以直接打开文件人工修改。

## 页面与流程

### 总览

入口：

```text
/
```

作用：作为进入系统的第一屏，说明 OPC 内容量化增长引擎如何帮助一人公司围绕一个产品持续完成内容生产、发布测试、数据归因和脚本优化。

流程：

```text
打开本地 Web 控制台
→ 默认进入总览页
→ 查看增长闭环
→ 点击对应功能按钮进入具体页面
```

结果：不产生文件，主要承担导航和业务说明。

## 产品信息

同一个本地入口里仍保留「产品信息」页面，但统一控制台的推荐方式是直接选择已有产品信息 Markdown。这个产品 Markdown 后续会和竞品爆款视频拆解结果一起用于复刻带货脚本。

产品信息只保存在本地，不会提交到 Git。统一控制台只记录当前选择的产品 Markdown 路径和页面状态，不覆盖旧 `app_config.json` 或旧 agent 配置。字段结构按产品资料 Markdown 调整，包括基础识别、定价策略、TOP 3 核心卖点、目标人群 × 痛点矩阵、核心痛点与转化话术、TikTok 营销推广切入点、市场关键词参考、适配素材类型建议和补充备注。

流程：

```text
选择已有产品信息 Markdown
→ 确认产品名和产品路径
→ 按 agent 选择输入/输出目录和模型偏好
→ 保存到 workflow_configs/unified_console/config/inputs.json
```

结果：形成统一控制台当前选择；每个 agent 可独立确认要处理的产品。

## 爆款采集

作用：从 FastMoss 根据可选关键词和商品搜索筛选条件采集竞品商品关联视频，并自动下载 TikTok 视频。

运行前必须先选择产品信息 Markdown。采集、下载和后续拆解会按统一控制台推断的 agent 输入/输出目录运行；旧入口仍可使用 `projects/` 归档。

流程：

```text
填写 FastMoss 手机号和密码
→ 可选填写关键词；留空时仅按国家/地区、商品分类和筛选条件采集
→ 像 FastMoss 页面一样点选国家/地区、商品分类、店铺类型、商品类型、商品状态和筛选条件
→ 填写商品链接数量、每商品视频数量
→ 点击「保存设置」
→ 点击「一键采集」
→ 程序检查登录状态，过期则自动登录
→ 如果手机号或密码已变更，程序会清理旧登录态并重新登录新账号
→ 搜索商品并按保存的筛选条件筛选；需要确认的 FastMoss 下拉筛选会自动点击确认
→ 打开前 N 个商品详情页
→ 进入商品关联视频
→ 分页采集视频数据
→ 收集 TikTok 视频 URL
→ 调用 Kolsprite 下载无水印 MP4
```

采集字段包括：视频标题、创作者名字、近 28 天销量、近 28 天销售额、近 28 天广告消耗、近 28 天 ROAS、播放量、点赞数、评论数、互动率、视频发布时间和 `tiktok_video_url`。

商品分类下拉选项来自本地文件 `data/fastmoss_category_tree.json`。如果 FastMoss 更新类目，可运行：

```bash
python3 -m opc_engine.features.hot_collection.scrape_fastmoss_category_tree
```

该脚本会登录 FastMoss 商品搜索页，滚动收录一级、二级、三级类目后刷新本地类目树。采集脚本会先展开商品分类区域，再按保存的一级、二级、三级类目选择。

## 输出命名

CSV 文件名格式：

```text
关键词_国家_完整三级类目_年月日_商品链接数量_视频URL数量.csv
```

关键词为空时，文件名前缀使用 `无关键词`。

CSV 会保存在：

```text
projects/<product>/collection_runs/<run_name>/<run_name>.csv
```

视频文件名格式：

```text
TikTok视频ID.mp4
```

例如：

```text
7622175051634314497.mp4
```

视频会保存在：

```text
projects/<product>/hot_sources/<source_id>/source/
```

## 视频拆解

在同一个本地入口切换到「视频拆解」页面，可以保存中转 API Key、切换模型、修改拆解提示词，并点击「拆解视频」分析 MP4。

「拆解视频路径」可以手动填写，也可以点击「选择目录」批量拆解一个目录，或点击「选择视频」单独拆解一个 MP4。视频拆解和爆款采集互相独立，路径不能为空，也不会自动使用采集下载目录。

视频拆解会同时读取本地「爆款内容知识库」文件：

```text
knowledge_base/hot_content_knowledge_base.md
```

这份文件用于保存视频拆解和脚本适配共用的爆款内容方法论，只保存在本机，不会提交到 Git。脚本产出不再读取这份方法论作为专家规则，而是按当前产品读取 `$OPC_VAULT_ROOT/wiki/视频/07错题本/<产品名>.md` 作为纠错材料。旧版 `knowledge_base/video_teardown_knowledge_base.md` 会被兼容读取，但新配置统一使用 `hot_content_knowledge_base.md`。

点击「保存设置」后，这些字段会同步保存在本地 `workflow_configs/video_teardown/config/inputs.json`，并更新当前运行状态 `app_config.json`，不要提交到 Git：

```json
{
  "modelmesh_api_key": "",
  "modelmesh_base_url": "https://router.shengsuanyun.com/api",
  "video_analysis_model": "google/gemini-3-flash",
  "video_analysis_prompt_path": "workflow_configs/video_teardown/config/video_teardown_prompt.md",
  "video_teardown_knowledge_base_path": "knowledge_base/hot_content_knowledge_base.md",
  "video_analysis_max_output_tokens": 32768,
  "analysis_input_path": ""
}
```

按已保存的 `analysis_input_path` 批量拆解：

```bash
python3 -m opc_engine.features.video_teardown.analyze_video_teardown_batch
```

对单个 MP4 做最小测试：

```bash
python3 -m opc_engine.features.video_teardown.analyze_video_teardown /path/to/video.mp4
```

结果会输出到 `projects/<product>/hot_sources/<source_id>/teardown/`。`analysis_input_path` 是目录时会拆解目录下全部 MP4，是单个 MP4 文件时只拆解该视频。

流程：

```text
填写/保存 ModelMesh API Key、Base URL 和拆解模型
→ 选择单个 MP4 或包含 MP4 的目录
→ 读取爆款视频拆解提示词
→ 读取爆款内容知识库
→ 调用 Gemini / ModelMesh
→ 输出 Markdown 拆解报告和 raw JSON
```

结果：形成可供「脚本产出」选择的竞品爆款拆解结果。

## 脚本产出

在同一个本地入口切换到「脚本产出」页面，核心输入是四类：

- 复刻提示词：规定怎么一比一复刻竞品爆款脚本逻辑。
- 参考爆款拆解结果：来自 `hot_sources/<source_id>/teardown/` 的 Markdown，提供具体爆款案例；素材框架和案例节奏会从这个拆解结果中自动提取，不需要手动填写。
- 产品信息：来自统一控制台选择的产品信息 Markdown，页面用“本 Agent 产品确认”提示归属，并提供打开产品信息目录的入口。
- 当前产品错题本：脚本生成智能体从 `$OPC_VAULT_ROOT/wiki/视频/07错题本/<产品名>.md` 读取，只用于避免重复历史错误、错误卖点、错误表达、合规风险和不适合本产品的转化角度。

系统会把这四类输入合并，把竞品爆款视频的逻辑和情绪节奏复刻成适合自家产品的新带货脚本。

如果勾选「是否裂变」，系统只允许读取已经生成过的复刻稿进行第二阶段裂变；没有复刻稿时不能执行裂变。裂变没有额外模式，只按裂变提示词和当前产品错题本的限制执行，保留镜头语言、情绪张力、视觉奇观和叙事结构。最终输出区只展示裂变后的 `.md` 成品脚本。
命令行也支持直接传入产品文档和竞品爆款脚本；此时程序会先从竞品脚本静默还原镜头结构、痛点递进、情绪强度、卖点进入顺序和 CTA 位置，再映射到产品文档中的新产品。

复刻提示词默认保存在本地文件：

```text
opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md
```

这份提示词保存在脚本生成模块自己的 config 目录。页面里修改并点击「保存设置」后，会更新这份本地文件。产品信息、参考竞品爆款脚本/拆解稿、可选视频总时长和当前产品错题本会由程序自动注入；黄金钩子和音频情绪强度不再作为独立输入，直接跟随参考爆款。提示词文件只维护复刻规则和输出格式，不需要再写“项目变量导入台”。脚本生成的错题本默认来自 `$OPC_VAULT_ROOT/wiki/视频/07错题本`，运行时按当前产品匹配同名 `.md`。

裂变提示词默认保存在：

```text
opc_engine/features/script_generation/config/script_generation_mutation_prompt.md
```

命令行生成脚本：

```bash
python3 -m opc_engine.features.script_generation.generate_product_script
```

打开脚本产出独立 agent 可视化界面：

```bash
python3 -m opc_engine.features.script_generation.script_generation_agent_web --port 9993
```

直接用产品文档和竞品脚本生成：

```bash
python3 -m opc_engine.features.script_generation.generate_product_script \
  --product-doc /path/to/product.md \
  --reference-script /path/to/hot_competitor_script.md \
  --total-duration 40s
```

命令行启用裂变：

```bash
python3 -m opc_engine.features.script_generation.generate_product_script \
  --enable-mutation \
  --mutation-variants 3
```

常规项目模式结果会输出到 `projects/<product>/hot_sources/<source_id>/scripts/`，文件名为 `<source_id>_<product>.md`；如果同名文件已存在，会自动保存为 `<source_id>_<product>_002.md`、`<source_id>_<product>_003.md` 等，避免覆盖。直接文件模式没有活动产品项目时，结果会输出到脚本生成模块自己的 `outputs/` 目录。

流程：

```text
选择一个 hot_sources/<source_id>/teardown/ 下的爆款拆解 Markdown
→ 读取当前选择的产品信息 Markdown
→ 读取当前产品错题本
→ 读取脚本产出提示词
→ 调用 Gemini / ModelMesh
→ 输出自家产品带货脚本
```

结果：得到后续「脚本适配」要使用的成品脚本。

## 脚本适配

作用：调用 ModelMesh / Gemini 文本模型，把成品脚本改写成适合交给 Veo 等视频生成模型继续生产的宫格首帧图提示词，以及一张“视频模型输入 CSV”。CSV 每一行对应一个片段任务，核心字段 `video_model_input_text` 可以直接复制到视频生成模型中使用。

当前状态：调用文本模型完成适配改写，但不调用 Veo、可灵或其他视频生成模型。

输入：

- 成品脚本 Markdown。
- 脚本适配提示词。
- 爆款内容知识库。
- 目标视频生成模型，例如 Veo。
- 单片段时长上限和适配备注。

流程：

```text
选择 hot_sources/<source_id>/scripts/ 中的成品脚本
→ 读取 workflow_configs/script_adaptation/config/script_adaptation_prompt.md
→ 读取 knowledge_base/hot_content_knowledge_base.md
→ 合并目标模型、时长、备注和脚本正文
→ 调用文本模型输出模块一宫格分镜 JSON
→ 输出模块二视频模型输入 CSV，每行是一条可直接输入视频生成模型的文字
→ 额外落盘 *_image_prompts.json 和 *_video_prompts.csv，供后续批量视频生成读取
```

结果：

```text
projects/<product>/hot_sources/<source_id>/adaptations/
```

每次脚本适配只生成三类核心文件：

```text
<timestamp>_<script>_<model>.md                    # 完整模型返回内容，便于人工审查
<timestamp>_<script>_<model>_image_prompts.json    # 从模块一提取的文生图/首帧图提示词
<timestamp>_<script>_<model>_video_prompts.csv     # 从模块二提取的视频片段提示词，每行一个片段
```

`*_video_prompts.csv` 中，`time_range` 表示该片段自身时长，例如 `3.5s` 或 `8s`，不是整条视频里的绝对时间段；`shot_reference` 只保留分镜编号，是否延续同一分镜由 `segment_type=continuation` 表示。

适配提示词默认保存在本地文件：

```text
workflow_configs/script_adaptation/config/script_adaptation_prompt.md
```

这份提示词只保存在本机，不会提交到 Git。页面里修改并点击「保存设置」后，会更新这份本地文件。成品脚本、目标视频生成模型、单片段时长上限、适配备注和爆款内容知识库会由程序自动注入，提示词文件只维护适配规则和输出格式，不需要再写“用户输入区”或脚本占位。旧路径 `knowledge_base/script_adaptation_prompt.md` 只作为兼容读取。

## 内容分发闭环

后续五个环节用于把脚本继续推进到发布测试和数据反馈。目前其中一部分已经是可运行本地框架，后续可以继续接真实平台接口。

- 「视频生成」当前是流程框架，未接入 Veo/可灵等视频生成模型，也不是完整自动剪辑链路；它读取已有视频片段目录，输出到 `hot_sources/<source_id>/generated_videos/`，生成视频生成清单，必要时可用 `ffmpeg` 尝试本地合并已有片段。
- 「视频发布」当前是流程框架，未接入 TikTok 自动登录、账号授权和自动发布；它输出到 `hot_sources/<source_id>/publish_records/`，只生成本地发布计划/记录。
- 「数据归因」分两个阶段：阶段一分别执行自然流数据下载和投放数据下载；阶段二读取自然流数据和投放数据，按 `作品ID / Video ID` 合并同一作品的两类表现，输出到 `product_level_reports/data_attribution/`。
- 「脚本优化」读取原脚本和数据归因结果，输出到 `hot_sources/<source_id>/optimizations/`，先形成加权评估和优化建议框架。

### 视频生成

当前状态：流程框架。这里还没有接入实际视频生成模型，也不会自动生产新片段；目前只做已有片段目录的整理、清单生成和可选本地合并。

流程：

```text
选择视频片段目录
→ 扫描 mp4 / mov / m4v
→ 生成视频生成清单
→ 如果检测到 ffmpeg，则可选尝试无转码合并已有片段
```

结果：

```text
projects/<product>/hot_sources/<source_id>/generated_videos/
```

### 视频发布

当前状态：流程框架。这里还没有接入 TikTok 自动登录、账号授权和自动发布；目前只生成发布计划和本地记录。

流程：

```text
选择待发布视频
→ 填写 TikTok 账号别名、标题、标签、发布模式
→ 生成发布计划/记录
```

结果：

```text
projects/<product>/hot_sources/<source_id>/publish_records/
```

当前不会自动登录或发布 TikTok。

### 数据归因

数据归因分成两个阶段：

- 阶段一：分别运行自然流数据下载和投放数据下载。自然流需要填写账号分组；投放数据默认下载昨天。
- 阶段二：自动读取本地最新的自然流数据和投放数据，用自然流表的 `作品ID` 对齐投放表的 `Video ID`，把同一个作品的播放/互动/发布时间与投放消耗/成交/ROAS 汇总成一张作品归因表。前端只展示处理后的归因表路径，不展示原始数据路径。

当前已放入两个阶段一下载入口：

```text
opc_engine.features.data_attribution.login_natural_flow_assisted
opc_engine.features.data_attribution.download_natural_flow_data
opc_engine.features.data_attribution.download_ad_performance_data
```

自然流数据登录模式：先运行半自动登录脚本，自动填写用户名和密码，验证码手动完成，然后保存项目内独立的自动化浏览器 profile 和本地登录状态。这个 profile 不会读取或复用你的常用 Chrome 个人资料。真实账号密码不要写进 Git，运行时用环境变量传入：

```bash
NATURAL_FLOW_USERNAME='你的用户名' NATURAL_FLOW_PASSWORD='你的密码' python3 -m opc_engine.features.data_attribution.login_natural_flow_assisted
```

自然流下载脚本会复用登录态，按必填账号分组筛选并导出自然流数据。账号分组可以只填分组名称，不需要填写括号里的数量。投放数据下载入口默认拉昨天的数据，并把导出表同步到阶段一的数据下载目录。

阶段二自动读取的原始数据目录：

```text
projects/<product>/raw_data/natural_flow/
projects/<product>/raw_data/ad_performance/
```

阶段二处理后的归因结果只输出到：

```text
projects/<product>/product_level_reports/data_attribution/*作品归因汇总.csv
```

流程：

```text
填写账号分组
→ 点击下载自然流数据
→ 点击下载投放数据（默认昨天）
→ 点击整理分析数据
→ 按作品ID / Video ID 合并同一个作品的两类数据
→ 标记 matched、natural_only、ads_only
→ 输出中文表头的作品归因 CSV
```

结果：

```text
projects/<product>/product_level_reports/data_attribution/
```

### 脚本优化

流程：

```text
选择原脚本
→ 选择数据归因结果
→ 填写优化备注
→ 输出加权评估框架和优化建议
```

结果：

```text
projects/<product>/hot_sources/<source_id>/optimizations/
```

当前先输出优化建议框架，后续可以继续接入模型，让它自动生成下一版脚本。

命令行也可以分别运行：

```bash
python3 -m opc_engine.features.script_adaptation.content_workflow_stage adapt
python3 -m opc_engine.features.script_adaptation.content_workflow_stage assemble
python3 -m opc_engine.features.script_adaptation.content_workflow_stage publish
python3 -m opc_engine.features.script_adaptation.content_workflow_stage metrics_download
python3 -m opc_engine.features.script_adaptation.content_workflow_stage metrics_natural_download
python3 -m opc_engine.features.script_adaptation.content_workflow_stage metrics_ads_download
python3 -m opc_engine.features.script_adaptation.content_workflow_stage metrics
python3 -m opc_engine.features.script_adaptation.content_workflow_stage optimize
```

这些输出目录都只保存在本地，不会提交到 Git。
