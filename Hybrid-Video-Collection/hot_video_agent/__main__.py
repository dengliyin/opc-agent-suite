from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from .agent import HotVideoAgent
from .config import CONFIG_PATH, ConfigError, init_config, load_config, validate_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="混剪参考视频采集智能体")
    parser.add_argument("--config", default=str(CONFIG_PATH), help=f"配置文件路径，默认 {CONFIG_PATH}")

    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="创建本地 config.json")
    init_parser.add_argument("--force", action="store_true", help="覆盖已有配置")

    subparsers.add_parser("doctor", help="检查运行环境和配置")
    subparsers.add_parser("login", help="只刷新 FastMoss 登录状态")
    subparsers.add_parser("collect", help="只采集 FastMoss 商品关联视频 CSV")
    subparsers.add_parser("download", help="只下载最新 CSV 里的 TikTok 视频")
    subparsers.add_parser("pipeline", help="采集 CSV 并下载视频")
    web_parser = subparsers.add_parser("web", help="启动网页版可视化界面")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=10001)
    return parser


def command_init(args) -> int:
    path = init_config(Path(args.config), overwrite=args.force)
    print(f"配置文件已准备: {path}")
    print("下一步：编辑该配置文件，并用环境变量 FASTMOSS_PHONE / FASTMOSS_PASSWORD 提供账号密码。")
    return 0


def command_doctor(args) -> int:
    config_path = Path(args.config)
    print(f"项目目录: {Path(__file__).resolve().parents[1]}")
    print(f"配置文件: {config_path}")
    print(f"配置存在: {'是' if config_path.exists() else '否'}")
    print(f"Playwright: {'已安装' if importlib.util.find_spec('playwright') else '未安装'}")

    try:
        config = load_config(config_path)
        validate_config(config, require_credentials=False)
        product = config.get("product") or {}
        fastmoss = config.get("fastmoss") or {}
        has_credentials = bool(fastmoss.get("phone") and fastmoss.get("password"))
        print(f"产品项目: {product.get('slug') or product.get('name')}")
        print(f"FastMoss 账号: {'已配置' if has_credentials else '未配置，可用环境变量提供'}")
        print("基础配置: 通过")
        return 0
    except ConfigError as exc:
        print(f"基础配置: 未通过 - {exc}")
        return 1


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "pipeline"

    try:
        if command == "init":
            return command_init(args)
        if command == "doctor":
            return command_doctor(args)
        if command == "web":
            from .hybrid_web import main as web_main

            web_main(["--host", args.host, "--port", str(args.port)])
            return 0

        agent = HotVideoAgent(Path(args.config))
        if command == "login":
            agent.refresh_login()
            return 0

        _, report = agent.run(command)
        return 1 if report.failures else 0
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("用户中断。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"任务失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
