from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class DockerStorageLayoutTests(unittest.TestCase):
    def test_docker_start_initializes_all_external_roots(self):
        launcher = (WORKSPACE_ROOT / "scripts" / "docker_up.sh").read_text(encoding="utf-8")
        for variable in ("OPC_VAULT_ROOT", "OPC_DOCKER_DATA_ROOT", "VIDEO_ASSEMBLY_WORK_ROOT"):
            self.assertIn(variable, launcher)
        self.assertIn('ensure_root_directory "$variable" "$value"', launcher)
        self.assertIn('create_storage_layout.sh" "$OPC_VAULT_ROOT"', launcher)
        self.assertIn('[ ! -w "$value" ]', launcher)

    def test_docker_start_creates_data_subdirectories(self):
        launcher = (WORKSPACE_ROOT / "scripts" / "docker_up.sh").read_text(encoding="utf-8")
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/config"', launcher)
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/finished-video-data"', launcher)
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/video-assembly-data"', launcher)
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/auto-publish-data"', launcher)

    def test_storage_layout_initializer_is_idempotent(self):
        initializer = WORKSPACE_ROOT / "scripts" / "create_storage_layout.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Obsidian Vault"
            subprocess.run([str(initializer), str(vault)], check=True, capture_output=True, text=True)
            marker = vault / "wiki" / "视频" / "纯AI视频" / "01来源素材" / "existing.txt"
            marker.write_text("keep", encoding="utf-8")
            subprocess.run([str(initializer), str(vault)], check=True, capture_output=True, text=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertTrue((vault / "wiki" / "视频" / "成品视频" / "视频标题库").is_dir())

    def test_storage_layout_initializer_refuses_missing_parent(self):
        initializer = WORKSPACE_ROOT / "scripts" / "create_storage_layout.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "missing-mount" / "Obsidian Vault"
            result = subprocess.run([str(initializer), str(vault)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(vault.exists())

    def test_windows_uses_the_same_docker_only_lifecycle(self):
        scripts = WORKSPACE_ROOT / "scripts"
        for name in ("create_storage_layout.ps1", "docker_up.ps1", "docker_stop.ps1", "docker_health.ps1"):
            self.assertTrue((scripts / name).is_file())
        launcher = (scripts / "docker_up.ps1").read_text(encoding="utf-8")
        self.assertIn("docker compose", launcher)
        self.assertIn("create_storage_layout.ps1", launcher)
        self.assertNotIn("ScheduledTask", launcher)


if __name__ == "__main__":
    unittest.main()
