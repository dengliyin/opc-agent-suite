# 控制台拆分记录

完成日期：2026-07-14

## 已完成

- `8888` 控制台迁入独立 `OPC-Console` 目录和 `.venv`。
- 控制台只保留 8 个 Agent 的启动、HTTP 状态检测、导航和运行日志。
- `Script-Generation` 只保留脚本产出业务。
- 脚本产出的通用 ModelMesh/Gemini HTTP 调用已迁入脚本产出模块自身。
- 已删除 `Script-Generation` 内被独立 Agent 替代的旧采集、旧视频拆解和旧脚本适配源码。
- 已删除没有独立产品入口的旧发布、归因、优化流程框架及其旧数据下载模块。

## 数据保护

本次没有删除以下本地内容：

- `Script-Generation/projects/`
- `Script-Generation/app_config.json`
- `Script-Generation/workflow_configs/` 下被 Git 忽略的本地配置
- Vault 中的产品资料、脚本、视频和生成结果
- 任何 Agent 的密钥、浏览器状态或运行产物

这些内容可能仍有历史数据价值。确认不再需要时应由用户单独清理，不属于源码迁移。

## 当前边界

`OPC-Console` 不导入任何 Agent 的 Python 包，也不执行采集、拆解、脚本生成、视频生成、发布或归因业务模块。每个启动命令都明确使用对应 Agent 的目录和虚拟环境。
