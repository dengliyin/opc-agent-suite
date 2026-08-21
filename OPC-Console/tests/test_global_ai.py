from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from opc_shared.global_ai import load_profile, runtime_override_active, set_runtime_overrides


class GlobalAISettingsTests(unittest.TestCase):
    def test_profile_reads_global_values_and_legacy_secret_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            path.write_text(
                'OPC_TEXT_API_BASE_URL="https://text.example/v1"\n'
                'OPC_TEXT_MODEL="text-model"\n'
                'MODELMESH_API_KEY="legacy-secret"\n',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                profile = load_profile("text", path)

        self.assertEqual(profile["base_url"], "https://text.example/v1")
        self.assertEqual(profile["model"], "text-model")
        self.assertEqual(profile["api_key"], "legacy-secret")

    def test_runtime_override_wins_and_is_process_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            path.write_text('OPC_TEXT_MODEL="global-model"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                set_runtime_overrides("text", {"model": "temporary-model"})
                self.assertTrue(runtime_override_active("text"))
                self.assertEqual(load_profile("text", path)["model"], "temporary-model")

            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertFalse(runtime_override_active("text"))
                self.assertEqual(load_profile("text", path)["model"], "global-model")


if __name__ == "__main__":
    unittest.main()
