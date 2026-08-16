import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

import yaml

from subbench.output import _rename_uri, write_outputs


class OutputTests(unittest.TestCase):
    def test_vless_fragment_is_replaced(self):
        rendered = _rename_uri("vless://id@example.com:443?security=tls#old", "vless", "🇺🇸 美国 | VLESS | 001")
        self.assertEqual(unquote(rendered.split("#", 1)[1]), "🇺🇸 美国 | VLESS | 001")

    def test_vmess_display_name_is_replaced(self):
        payload = base64.urlsafe_b64encode(json.dumps({"ps": "old", "add": "example.com"}).encode()).decode().rstrip("=")
        rendered = _rename_uri(f"vmess://{payload}", "vmess", "🇯🇵 日本 | VMESS | 001")
        encoded = rendered.split("://", 1)[1]
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertEqual(json.loads(decoded)["ps"], "🇯🇵 日本 | VMESS | 001")

    def test_empty_subscription_uses_direct_only_group(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_outputs(output, [], [{"source": "benchmark", "error": "no usable nodes"}])
            clash = yaml.safe_load((output / "clash.yaml").read_text(encoding="utf-8"))
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(clash["proxy-groups"], [{"name": "PROXY", "type": "select", "proxies": ["DIRECT"]}])
        self.assertEqual(report["node_count"], 0)


if __name__ == "__main__":
    unittest.main()
