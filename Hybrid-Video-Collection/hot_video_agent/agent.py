from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from .config import ROOT, ConfigError, compact_params, load_config, validate_config
from .fastmoss import FastMossCollector
from .kolsprite import KolspriteDownloader
from .paths import ProjectPaths
from .reporting import RunReport


class HotVideoAgent:
    def __init__(self, config_path: Path, logger=print) -> None:
        self.config_path = Path(config_path)
        self.log = logger
        self.config: Dict[str, Any] = load_config(self.config_path)
        self.paths = ProjectPaths(ROOT, self.config)

    def validate(self, mode: str) -> None:
        validate_config(self.config, require_credentials=mode in {"collect", "pipeline", "login"})

    def refresh_login(self) -> None:
        self.validate("login")
        self.paths.ensure()
        FastMossCollector(self.config, self.paths, self.log).refresh_login()

    def run(self, mode: str) -> Tuple[Path, RunReport]:
        if mode not in {"collect", "download", "pipeline"}:
            raise ConfigError(f"未知运行模式: {mode}")

        self.validate(mode)
        self.paths.ensure()
        report = RunReport(mode=mode, started_at=datetime.now())

        params = compact_params(
            self.config,
            [
                "phone",
                "keyword",
                "country",
                "category_path",
                "product_limit",
                "videos_per_product",
                "show_browser",
            ],
        )
        self.log(f"当前产品项目: {self.paths.slug}")
        self.log(f"结果文件夹: {self.paths.result_dir()}")
        self.log(f"关键参数: {params}")

        try:
            if mode in {"collect", "pipeline"}:
                collector = FastMossCollector(self.config, self.paths, self.log)
                report.csv_path = collector.run()

            should_download = bool((self.config.get("download") or {}).get("enabled", True))
            if mode == "download" or (mode == "pipeline" and should_download):
                downloader = KolspriteDownloader(self.config, self.paths, self.log)
                csv_path, downloaded, skipped, failures = downloader.run(report.csv_path)
                report.csv_path = csv_path
                report.downloaded.extend(downloaded)
                report.skipped.extend(skipped)
                report.failures.extend(failures)
        except Exception as exc:
            report.failures.append(str(exc))
            report_path = report.write(self.paths)
            self.log(f"运行报告: {report_path}")
            raise

        report_path = report.write(self.paths)
        self.log(f"运行报告: {report_path}")
        return report_path, report
