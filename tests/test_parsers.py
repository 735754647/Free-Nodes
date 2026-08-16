import base64
import json
import unittest

from subbench.parsers import parse_document, parse_uri


class ParserTests(unittest.TestCase):
    def test_vless_ws(self):
        node = parse_uri(
            "vless://00000000-0000-4000-8000-000000000001@example.com:443?encryption=none&security=tls&type=ws&host=cdn.example.com&path=%2Fws&sni=example.com#demo",
            "test",
        )
        self.assertEqual(node.clash["type"], "vless")
        self.assertEqual(node.clash["ws-opts"]["headers"]["Host"], "cdn.example.com")
        self.assertTrue(node.clash["tls"])

    def test_vmess_base64_subscription(self):
        payload = {
            "v": "2",
            "ps": "demo",
            "add": "example.com",
            "port": "443",
            "id": "00000000-0000-4000-8000-000000000001",
            "aid": "0",
            "scy": "auto",
            "net": "ws",
            "host": "cdn.example.com",
            "path": "/ws",
            "tls": "tls",
        }
        uri = "vmess://" + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        subscription = base64.b64encode(uri.encode()).decode()
        nodes = parse_document(subscription, "test")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].scheme, "vmess")
        self.assertEqual(nodes[0].clash["network"], "ws")

    def test_clash_yaml(self):
        text = """
proxies:
  - name: demo
    type: trojan
    server: example.com
    port: 443
    password: secret
    sni: example.com
"""
        nodes = parse_document(text, "test")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].clash["type"], "trojan")
        self.assertIn("trojan://", nodes[0].uri)

    def test_duplicate_fragments_share_key(self):
        first = parse_uri(
            "vless://00000000-0000-4000-8000-000000000001@example.com:443?encryption=none&type=tcp#one",
            "a",
        )
        second = parse_uri(
            "vless://00000000-0000-4000-8000-000000000001@example.com:443?encryption=none&type=tcp#two",
            "b",
        )
        self.assertEqual(first.canonical_key(), second.canonical_key())


if __name__ == "__main__":
    unittest.main()
