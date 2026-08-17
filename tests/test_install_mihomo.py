import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install_mihomo.py"
SPEC = importlib.util.spec_from_file_location("install_mihomo", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {SCRIPT_PATH}")
INSTALL_MIHOMO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL_MIHOMO)
github_api_headers = INSTALL_MIHOMO.github_api_headers


class InstallMihomoTests(unittest.TestCase):
    def test_github_token_is_used_for_release_api(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=False):
            headers = github_api_headers()

        self.assertEqual(headers["Authorization"], "Bearer test-token")

    def test_release_api_headers_work_without_token(self):
        with patch.dict(os.environ, {}, clear=True):
            headers = github_api_headers()

        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["Accept"], "application/vnd.github+json")


if __name__ == "__main__":
    unittest.main()
