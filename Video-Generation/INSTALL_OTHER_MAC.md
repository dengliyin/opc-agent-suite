# 其他 Mac 安装说明

这个包用于把 Omni/Grok 片段产出程序安装到另一台 Mac。包内不包含 `.env`、API Key、任务数据、视频素材或本机缓存。

## 前置条件

1. 安装并启动 Docker Desktop for Mac。
2. 解压本程序包到任意目录，例如：

```bash
~/Documents/omni片段产出
```

## 一键安装

进入程序目录后执行：

```bash
chmod +x scripts/install_mac.sh
./scripts/install_mac.sh "$HOME/Documents/Obsidian Vault"
```

如果你想把任务包放到别的位置，把第二行里的路径换成你的数据根目录即可。

安装脚本会自动创建这些目录：

```text
Obsidian Vault/
  wiki/视频/纯AI视频/04适配脚本/
    omni/
    grok/
  wiki/产品/产品底图/
  wiki/视频/纯AI视频/05AI片段/omni/
  wiki/视频/纯AI视频/05AI片段/grok/
```

启动后打开：

```text
http://127.0.0.1:9995
```

## API Key

首次安装后会生成本机 `.env`。可以用两种方式配置 API：

1. 打开网页 `API 设置` 填写。
2. 直接编辑 `.env`。

`.env` 只留在本机，不要上传网盘或发给别人。

## 手动任务包使用方式

把任务包下载到这台 Mac 后，有两种方式：

1. 放进安装脚本创建的数据根目录。
2. 在网页 `路径设置` 里选择任务包内对应目录。

推荐任务包结构：

```text
任务包_xxx/
  09产品参考图/
  输入/
    omni10s1片段/
    grok6-30s1片段/
  输出/
    05AI片段/omni/
    05AI片段/grok/
```

对应路径设置：

```text
Omni 脚本输入路径 -> 任务包/输入/omni10s1片段
Grok 脚本输入路径 -> 任务包/输入/grok6-30s1片段
产品参考图路径 -> 任务包/09产品参考图
Omni 视频输出路径 -> 任务包/输出/05AI片段/omni
Grok 视频输出路径 -> 任务包/输出/05AI片段/grok
```

## 常用命令

启动或更新：

```bash
docker compose up -d --build
```

停止：

```bash
docker compose down
```

查看状态：

```bash
docker compose ps
```
