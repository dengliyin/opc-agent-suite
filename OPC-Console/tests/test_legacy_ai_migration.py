from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from opc_shared.legacy_ai_migration import (
    MARKER_NAME,
    PRIVATE_NAME,
    load_report,
    resolve_conflicts,
    run_migration,
)


class LegacyAIMigrationTests(unittest.TestCase):
    def test_unique_values_migrate_once_without_overwriting_global(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            config = root / "config"
            analysis = repo / "Script-Analysis" / "config"
            video = repo / "Video-Generation"
            text_runtime = repo / "Script-Generation" / "runtime"
            analysis.mkdir(parents=True)
            video.mkdir(parents=True)
            text_runtime.mkdir(parents=True)
            analysis.joinpath("settings.json").write_text(
                '{"base_url":"https://vision.example","model":"vision-model"}', encoding="utf-8"
            )
            analysis.joinpath("settings.local.json").write_text(
                '{"api_key":"vision-secret"}', encoding="utf-8"
            )
            video.joinpath(".env").write_text(
                "OTU_BASE_URL=https://otu.example\nOTU_API_KEY=otu-secret\nIMAGE_MODEL=image-model\nOMNI_MODEL=video-model\n",
                encoding="utf-8",
            )
            text_runtime.joinpath("model_settings.json").write_text(
                '{"modelmesh_base_url":"https://text.example","script_generation_model":"text-model","modelmesh_api_key":"text-secret"}',
                encoding="utf-8",
            )
            config.mkdir()
            config.joinpath(".env").write_text('OPC_VIDEO_ANALYSIS_MODEL="keep-global"\n', encoding="utf-8")

            report = run_migration(repo, config)
            saved = config.joinpath(".env").read_text(encoding="utf-8")
            backup = Path(report["backup_dir"])

            self.assertEqual(report["status"], "complete")
            self.assertIn('OPC_VIDEO_ANALYSIS_MODEL="keep-global"', saved)
            self.assertIn('OPC_VIDEO_ANALYSIS_API_BASE_URL="https://vision.example"', saved)
            self.assertIn('OPC_VIDEO_ANALYSIS_API_KEY="vision-secret"', saved)
            self.assertIn('OTU_API_KEY="otu-secret"', saved)
            self.assertIn('OPC_TEXT_API_BASE_URL="https://text.example"', saved)
            self.assertIn('OPC_TEXT_MODEL="text-model"', saved)
            self.assertTrue((config / MARKER_NAME).is_file())
            self.assertTrue((backup / "legacy" / "Script-Analysis" / "config" / "settings.local.json").is_file())
            self.assertNotIn("vision-secret", str(report))

            analysis.joinpath("settings.json").write_text(
                '{"base_url":"https://changed.example","model":"changed-model"}', encoding="utf-8"
            )
            rerun = run_migration(repo, config)
            self.assertEqual(rerun, load_report(config))
            self.assertNotIn("changed.example", config.joinpath(".env").read_text(encoding="utf-8"))

    def test_conflicts_are_masked_and_require_an_explicit_choice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            config = root / "config"
            first = repo / "Script-Analysis" / "config"
            second = repo / "Hybrid-Script-Analysis" / "config"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            first.joinpath("settings.local.json").write_text(
                '{"base_url":"https://one.example","api_key":"secret-one"}', encoding="utf-8"
            )
            second.joinpath("settings.local.json").write_text(
                '{"base_url":"https://two.example","api_key":"secret-two"}', encoding="utf-8"
            )

            report = run_migration(repo, config)
            public_text = str(report)

            self.assertEqual(report["status"], "pending")
            self.assertNotIn("secret-one", public_text)
            self.assertNotIn("secret-two", public_text)
            self.assertTrue((config / PRIVATE_NAME).is_file())
            config.joinpath(".env").write_text('OPC_VIDEO_ANALYSIS_API_BASE_URL="https://manual.example"\n', encoding="utf-8")
            choices = {item["field"]: item["candidates"][1]["id"] for item in report["conflicts"]}
            completed = resolve_conflicts(config, choices)
            saved = config.joinpath(".env").read_text(encoding="utf-8")

            self.assertEqual(completed["status"], "complete")
            self.assertIn('OPC_VIDEO_ANALYSIS_API_BASE_URL="https://manual.example"', saved)
            self.assertIn('OPC_VIDEO_ANALYSIS_API_KEY="secret-two"', saved)
            self.assertFalse((config / PRIVATE_NAME).exists())
            self.assertTrue((config / MARKER_NAME).is_file())


if __name__ == "__main__":
    unittest.main()
