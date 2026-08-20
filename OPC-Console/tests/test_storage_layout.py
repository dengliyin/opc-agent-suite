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

    def test_first_start_chooses_storage_beside_repository(self):
        launcher = (WORKSPACE_ROOT / "scripts" / "docker_up.sh").read_text(encoding="utf-8")
        self.assertIn('STORAGE_ROOT="$(dirname "$ROOT_DIR")"', launcher)
        self.assertIn('OPC_VAULT_ROOT="%s/Obsidian Vault"', launcher)
        self.assertIn('OPC_DOCKER_DATA_ROOT="%s/OPC-Data/docker"', launcher)
        self.assertIn('VIDEO_ASSEMBLY_WORK_ROOT="%s/OPC-Data/Video-Assembly-hd"', launcher)
        self.assertIn("if [ ! -f \"$ENV_FILE\" ]", launcher)

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
            claude_file = vault / "CLAUDE.md"
            self.assertIn("OPC 资料库协作规则", claude_file.read_text(encoding="utf-8"))
            marker = vault / "wiki" / "视频" / "纯AI视频" / "01来源素材" / "existing.txt"
            marker.write_text("keep", encoding="utf-8")
            claude_file.write_text("custom rules", encoding="utf-8")
            subprocess.run([str(initializer), str(vault)], check=True, capture_output=True, text=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(claude_file.read_text(encoding="utf-8"), "custom rules")
            self.assertTrue((vault / "wiki" / "视频" / "成品视频" / "视频标题库").is_dir())

    def test_storage_template_claude_file_uses_current_layout(self):
        content = (WORKSPACE_ROOT / "storage-template" / "CLAUDE.md").read_text(encoding="utf-8")
        for current_path in ("纯AI视频/01来源素材", "纯AI视频/06合成工作区", "AI实拍混剪/08混剪工作区"):
            self.assertIn(current_path, content)
        for legacy_path in ("03爆款视频", "10omni视频片段", "视频片段 （待拼接）"):
            self.assertNotIn(legacy_path, content)

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
        initializer = (scripts / "create_storage_layout.ps1").read_text(encoding="utf-8")
        self.assertIn("docker compose", launcher)
        self.assertIn("create_storage_layout.ps1", launcher)
        self.assertIn("Copy-Item", initializer)
        self.assertIn('Name -ne ".gitkeep"', initializer)
        self.assertIn('$StorageRoot = Split-Path -Parent $RootDir', launcher)
        self.assertIn('Join-Path $StorageRoot "Obsidian Vault"', launcher)
        self.assertIn('Join-Path $StorageRoot "OPC-Data\\docker"', launcher)
        self.assertIn('if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf))', launcher)
        self.assertNotIn("ScheduledTask", launcher)


if __name__ == "__main__":
    unittest.main()
