from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audio_agent.core import AudioPaths, generate_entries, parse_document, scan_library


SAMPLE = """# 测试产品原创音频文案

## 西班牙 ES

### ES-001｜高空拍摄

建议音频文件名：`AI音频-ES-高空拍摄-001.m4a`

音频文案：

> Hola desde arriba.

中文校对：

> 你好。

### ES-002｜旅行便携

建议音频文件名：`AI音频-ES-旅行便携-002.m4a`

音频文案：

> Viaja con una vista diferente.
"""


class AudioCoreTests(unittest.TestCase):
    def paths(self, root: Path) -> AudioPaths:
        return AudioPaths(root, root / "06音频文案", root / "06音频文件")

    def test_parse_document_extracts_only_source_language_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.paths(Path(temporary))
            paths.copy_root.mkdir()
            source = paths.copy_root / "测试产品-原创文案.md"
            source.write_text(SAMPLE, encoding="utf-8")

            document = parse_document(source, paths)

        self.assertEqual(document["product"], "测试产品")
        self.assertEqual(len(document["entries"]), 2)
        self.assertEqual(document["entries"][0]["market"], "ES")
        self.assertEqual(document["entries"][0]["text"], "Hola desde arriba.")
        self.assertNotIn("你好", document["entries"][0]["text"])

    def test_scan_library_reports_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.paths(Path(temporary))
            paths.copy_root.mkdir()
            source = paths.copy_root / "测试产品-原创文案.md"
            source.write_text(SAMPLE, encoding="utf-8")
            output = paths.audio_root / "测试产品/AI音频-ES-高空拍摄-001.m4a"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"audio")

            library = scan_library(paths)

        self.assertTrue(library["documents"][0]["entries"][0]["generated"])
        self.assertFalse(library["documents"][0]["entries"][1]["generated"])

    @mock.patch("audio_agent.core.runtime_paths")
    @mock.patch("audio_agent.core.run_checked")
    def test_generate_entries_uses_speed_1_2_and_writes_product_output(self, run_checked, runtime_paths):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self.paths(root)
            paths.copy_root.mkdir()
            source = paths.copy_root / "测试产品-原创文案.md"
            source.write_text(SAMPLE, encoding="utf-8")
            node = root / "node"
            cli = root / "cli.js"
            ffmpeg = root / "ffmpeg"
            for path in (node, cli, ffmpeg):
                path.touch()
            runtime_paths.return_value = (node, cli, ffmpeg)

            def create_outputs(command, **_kwargs):
                output = Path(command[-2] if "--json" in command else command[-1])
                output.write_bytes(b"audio")

            run_checked.side_effect = create_outputs
            with mock.patch("audio_agent.core.ROOT", root):
                python = root / ".venv/bin/python"
                python.parent.mkdir(parents=True)
                python.touch()
                with mock.patch(
                    "audio_agent.core.os.rename",
                    side_effect=OSError(errno.EXDEV, "Cross-device link"),
                ):
                    outputs = generate_entries(
                        source.name,
                        ["ES-001"],
                        "ef_dora",
                        paths=paths,
                    )
                tts_command = run_checked.call_args_list[0].args[0]
                self.assertIn("--speed", tts_command)
                self.assertEqual(tts_command[tts_command.index("--speed") + 1], "1.2")
                self.assertEqual(outputs[0]["status"], "generated")
                self.assertTrue(Path(outputs[0]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
