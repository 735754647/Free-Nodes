import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "select_artifact_proxy.py"
SPEC = importlib.util.spec_from_file_location("select_artifact_proxy", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {SCRIPT_PATH}")
SELECT_PROXY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECT_PROXY)
PROXY = "http://127.0.0.1:10808"
RESULTS_URL = "https://results.example.test/"


def response(status: int) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = b""
    result._content_consumed = True
    return result


class ArtifactProxyTests(unittest.TestCase):
    def setUp(self):
        self.log = io.StringIO()
        capture = redirect_stdout(self.log)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def test_direct_success_ignores_inherited_proxy_and_skips_proxy_probe(self):
        with patch.dict(os.environ, {"HTTP_PROXY": PROXY, "HTTPS_PROXY": PROXY}), patch.object(
            requests.Session, "send", return_value=response(401)
        ) as send:
            self.assertEqual(SELECT_PROXY.select_proxy(RESULTS_URL, PROXY), "")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["proxies"], {})
        request = send.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url, RESULTS_URL + SELECT_PROXY.ARTIFACT_PATH)
        self.assertNotIn("Authorization", request.headers)
        self.assertFalse(send.call_args.kwargs["allow_redirects"])

    def test_direct_failure_uses_proxy_only_after_endpoint_responds(self):
        with patch.dict(os.environ, {"NO_PROXY": "*"}), patch.object(
            requests.Session,
            "send",
            side_effect=[requests.ConnectionError("connection reset"), response(401)],
        ) as send:
            self.assertEqual(SELECT_PROXY.select_proxy(RESULTS_URL, PROXY), PROXY)
        self.assertEqual(send.call_args.kwargs["proxies"], {"http": PROXY, "https": PROXY})
        self.assertIn("connection reset", self.log.getvalue())

    def test_closed_proxy_falls_back_to_direct_and_logs_both_errors(self):
        with patch.object(
            requests.Session,
            "send",
            side_effect=[requests.Timeout("direct timed out"), requests.exceptions.ProxyError("connection refused")],
        ):
            self.assertEqual(SELECT_PROXY.select_proxy(RESULTS_URL, PROXY), "")
        self.assertIn("direct timed out", self.log.getvalue())
        self.assertIn("connection refused", self.log.getvalue())

    def test_redirects_proxy_auth_and_gateway_errors_do_not_select_proxy(self):
        for status in (200, 302, 403, 407, 502, 503):
            with self.subTest(status=status), patch.object(
                requests.Session, "send", side_effect=[response(503), response(status)]
            ):
                self.assertEqual(SELECT_PROXY.select_proxy(RESULTS_URL, PROXY), "")

    def test_next_retry_rechecks_direct_instead_of_reusing_proxy(self):
        with patch.object(
            requests.Session, "send", side_effect=[response(503), response(401), response(401)]
        ) as send:
            self.assertEqual(SELECT_PROXY.select_proxy(RESULTS_URL, PROXY), PROXY)
            self.assertEqual(SELECT_PROXY.select_proxy(RESULTS_URL, PROXY), "")
        self.assertEqual(send.call_args.kwargs["proxies"], {})

    def test_writes_action_outputs_for_each_route_and_uses_runtime_endpoint(self):
        for proxy in ("", PROXY):
            with self.subTest(proxy=proxy), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "outputs"
                output.write_text("existing=value\n", encoding="utf-8")
                with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "ACTIONS_RESULTS_URL": RESULTS_URL}), patch.object(
                    SELECT_PROXY, "select_proxy", return_value=proxy
                ) as select:
                    self.assertEqual(SELECT_PROXY.main([]), 0)
                select.assert_called_once_with(RESULTS_URL, PROXY)
                self.assertEqual(
                    output.read_text(encoding="utf-8").splitlines(),
                    [
                        "existing=value",
                        f"proxy={proxy}",
                        f"no_proxy={'127.0.0.1,localhost' if proxy else '*'}",
                        f"route={'proxy' if proxy else 'direct'}",
                    ],
                )


if __name__ == "__main__":
    unittest.main()
