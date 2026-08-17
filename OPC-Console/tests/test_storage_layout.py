from __future__ import annotations

import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class DockerStorageLayoutTests(unittest.TestCase):
    def test_docker_start_requires_all_external_roots(self):
        launcher = (WORKSPACE_ROOT / "scripts" / "docker_up.sh").read_text(encoding="utf-8")
        for variable in ("OPC_VAULT_ROOT", "OPC_DOCKER_DATA_ROOT", "VIDEO_ASSEMBLY_WORK_ROOT"):
            self.assertIn(variable, launcher)
        self.assertIn('[ ! -d "$value" ]', launcher)
        self.assertIn('[ ! -w "$value" ]', launcher)

    def test_docker_start_creates_only_data_subdirectories(self):
        launcher = (WORKSPACE_ROOT / "scripts" / "docker_up.sh").read_text(encoding="utf-8")
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/config"', launcher)
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/finished-video-data"', launcher)
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/video-assembly-data"', launcher)
        self.assertIn('"$OPC_DOCKER_DATA_ROOT/auto-publish-data"', launcher)
        self.assertNotIn('mkdir -p "$OPC_VAULT_ROOT"', launcher)

    def test_windows_uses_the_same_docker_only_lifecycle(self):
        scripts = WORKSPACE_ROOT / "scripts"
        for name in ("docker_up.ps1", "docker_stop.ps1", "docker_health.ps1"):
            self.assertTrue((scripts / name).is_file())
        launcher = (scripts / "docker_up.ps1").read_text(encoding="utf-8")
        self.assertIn("docker compose", launcher)
        self.assertNotIn("ScheduledTask", launcher)


if __name__ == "__main__":
    unittest.main()
