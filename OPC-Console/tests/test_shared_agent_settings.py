from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def assignment_map(path: str):
    values = {}
    for raw_line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class SharedAgentSettingsTests(unittest.TestCase):
    def test_model_agents_keep_non_secret_settings_in_tracked_files(self):
        analysis = read_json("Script-Analysis/config/settings.json")
        generation = read_json(
            "Script-Generation/opc_engine/features/script_generation/config/model_defaults.json"
        )
        adaptation = read_json(
            "Script-Adaptation/software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_settings.json"
        )
        rewrite = read_json("Product-Script-Rewrite/agent_config/agent_settings.json")
        video = assignment_map("Video-Generation/agent_settings.env")

        self.assertEqual(analysis["base_url"], "https://zexapi.com")
        self.assertEqual(generation["modelmesh_base_url"], "https://api.deepseek.com")
        self.assertIn("model", adaptation)
        self.assertIn("model", rewrite)
        self.assertEqual(video["OTU_BASE_URL"], "https://zexapi.com")
        self.assertEqual(video["GROK_BASE_URL"], "https://www.runninghub.cn")

        serialized = json.dumps([analysis, generation, adaptation, rewrite], ensure_ascii=False)
        self.assertNotIn('"api_key"', serialized)
        self.assertFalse(any(key.endswith("API_KEY") for key in video))

    def test_tracked_secret_templates_contain_no_credentials(self):
        env_values = assignment_map(".env.example")
        video_env_values = assignment_map("Video-Generation/.env.example")
        analysis_local = read_json("Script-Analysis/config/settings.local.example.json")
        adaptation_local = read_json(
            "Script-Adaptation/software/Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_secrets.example.json"
        )
        rewrite_local = read_json("Product-Script-Rewrite/agent_config/agent_secrets.example.json")
        collection = read_json("Video-Collection/config.example.json")

        for key, value in {**env_values, **video_env_values}.items():
            if any(marker in key for marker in ("KEY", "TOKEN", "PASSWORD")):
                self.assertEqual(value, "", key)
        self.assertEqual(analysis_local["api_key"], "")
        self.assertFalse(any(value for key, value in adaptation_local.items() if "key" in key.lower()))
        self.assertFalse(any(value for key, value in rewrite_local.items() if "key" in key.lower()))
        self.assertEqual(collection["fastmoss"]["phone"], "")
        self.assertEqual(collection["fastmoss"]["password"], "")


if __name__ == "__main__":
    unittest.main()
