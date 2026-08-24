from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CONSOLE_ROOT = Path(__file__).resolve().parents[1]


def load_console_module():
    spec = importlib.util.spec_from_file_location("opc_console_update", CONSOLE_ROOT / "kesai_app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"state": "complete"}).encode("utf-8")


class ConsoleSystemUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_console_module()

    def test_console_does_not_expose_local_update_controls(self):
        self.assertNotIn("本地更新", self.app.INDEX_HTML)
        self.assertNotIn("应用本地更新", self.app.INDEX_HTML)
        self.assertNotIn("/api/system-update", self.app.INDEX_HTML)
        self.assertNotIn("openUpdate", self.app.INDEX_HTML)

    def test_proxy_uses_private_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "updater.token"
            token_file.write_text("secret-token", encoding="utf-8")
            with mock.patch.object(self.app, "UPDATER_TOKEN_FILE", token_file), mock.patch.object(
                self.app.urllib.request, "urlopen", return_value=Response()
            ) as urlopen:
                status, payload = self.app.updater_request("/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "complete")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-opc-updater-token"), "secret-token")

    def test_ai_restart_proxy_forwards_selected_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "updater.token"
            token_file.write_text("secret-token", encoding="utf-8")
            with mock.patch.object(self.app, "UPDATER_TOKEN_FILE", token_file), mock.patch.object(
                self.app.urllib.request, "urlopen", return_value=Response()
            ) as urlopen:
                self.app.updater_request(
                    "/restart-ai-agents",
                    method="POST",
                    payload={"group": "text"},
                )

        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"group": "text"})

    def test_missing_token_reports_service_unavailable(self):
        with mock.patch.object(self.app, "UPDATER_TOKEN_FILE", Path("/missing/updater.token")):
            status, payload = self.app.updater_request("/status")
        self.assertEqual(status, 503)
        self.assertEqual(payload["state"], "unavailable")


if __name__ == "__main__":
    unittest.main()
