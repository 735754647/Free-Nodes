import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

import yaml

from subbench.models import Node
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

    def test_v2ray_output_uses_xray_compatible_subset(self):
        nodes = [
            Node(
                uri="vless://id@example.com:443?encryption=none#vless",
                scheme="vless",
                name="vless",
                clash={"name": "vless", "type": "vless", "server": "example.com", "port": 443},
                source="test",
            ),
            Node(
                uri="hysteria2://secret@example.com:443#hy2",
                scheme="hysteria2",
                name="hy2",
                clash={"name": "hy2", "type": "hysteria2", "server": "example.com", "port": 443},
                source="test",
            ),
            Node(
                uri="trojan://secret@example.com:443?allowInsecure=1#insecure",
                scheme="trojan",
                name="insecure",
                clash={
                    "name": "insecure",
                    "type": "trojan",
                    "server": "example.com",
                    "port": 443,
                    "skip-cert-verify": True,
                },
                source="test",
            ),
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_outputs(output, nodes, [])
            decoded = base64.b64decode((output / "v2ray.txt").read_text(encoding="ascii")).decode()
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            clash = yaml.safe_load((output / "clash.yaml").read_text(encoding="utf-8"))

        self.assertEqual(decoded.count("\n"), 1)
        self.assertIn("vless://", decoded)
        self.assertNotIn("hysteria2://", decoded)
        self.assertNotIn("trojan://", decoded)
        self.assertEqual(report["node_count"], 3)
        self.assertEqual(report["v2ray_node_count"], 1)
        self.assertEqual(report["v2ray_excluded_count"], 2)
        self.assertEqual(len(clash["proxies"]), 3)

    def test_v2ray_output_excludes_xhttp_without_path(self):
        nodes = [
            Node(
                uri="vless://id@example.com:443?encryption=none&type=xhttp&sni=example.com#missing",
                scheme="vless",
                name="missing",
                clash={
                    "name": "missing",
                    "type": "vless",
                    "server": "example.com",
                    "port": 443,
                    "network": "xhttp",
                    "xhttp-opts": {},
                },
                source="test",
            ),
            Node(
                uri="vless://id@example.com:443?encryption=none&type=xhttp&path=%2Fedge#complete",
                scheme="vless",
                name="complete",
                clash={
                    "name": "complete",
                    "type": "vless",
                    "server": "example.com",
                    "port": 443,
                    "network": "xhttp",
                    "xhttp-opts": {"path": "/edge"},
                },
                source="test",
            ),
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_outputs(output, nodes, [])
            decoded = base64.b64decode((output / "v2ray.txt").read_text(encoding="ascii")).decode()

        self.assertNotIn("missing", decoded)
        self.assertIn("complete", decoded)


if __name__ == "__main__":
    unittest.main()
