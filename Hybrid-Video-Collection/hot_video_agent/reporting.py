from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .paths import ProjectPaths


@dataclass
class RunReport:
    mode: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    csv_path: Optional[Path] = None
    downloaded: List[Path] = field(default_factory=list)
    skipped: List[Path] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)

    def finish(self) -> None:
        self.ended_at = datetime.now()

    def write(self, paths: ProjectPaths) -> Path:
        self.finish()
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        result_dir = self.csv_path.parent if self.csv_path else None
        report_path = paths.report_path(f"{stamp}_{self.mode}", result_dir=result_dir)
        lines = [
            f"# 爆款视频收集运行报告",
            "",
            f"- 模式: {self.mode}",
            f"- 开始时间: {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 结束时间: {self.ended_at.strftime('%Y-%m-%d %H:%M:%S') if self.ended_at else ''}",
            f"- 产品项目: {paths.slug}",
            f"- 结果文件夹: {paths.relative(result_dir) if result_dir else paths.relative(paths.result_dir())}",
            f"- CSV: {paths.relative(self.csv_path) if self.csv_path else '未生成'}",
            f"- 新下载视频: {len(self.downloaded)}",
            f"- 已存在跳过: {len(self.skipped)}",
            f"- 失败项: {len(self.failures)}",
            "",
        ]

        if self.downloaded:
            lines.append("## 新下载视频")
            lines.extend(f"- {paths.relative(path)}" for path in self.downloaded)
            lines.append("")

        if self.skipped:
            lines.append("## 已存在跳过")
            lines.extend(f"- {paths.relative(path)}" for path in self.skipped)
            lines.append("")

        if self.failures:
            lines.append("## 失败详情")
            lines.extend(f"- {item}" for item in self.failures)
            lines.append("")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
