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

    def test_vless_non_none_encryption_is_rejected_for_mihomo(self):
        with self.assertRaisesRegex(ValueError, "unsupported VLESS encryption"):
            parse_uri(
                "vless://00000000-0000-4000-8000-000000000001@example.com:443?encryption=mlkem768x25519plus.native.0rtt.secret",
                "test",
            )

    def test_document_reports_skipped_vless_encryption(self):
        skipped: list[str] = []
        nodes = parse_document(
            "vless://00000000-0000-4000-8000-000000000001@example.com:443?encryption=mlkem768x25519plus.native.0rtt.secret",
            "test-source",
            skipped,
        )
        self.assertEqual(nodes, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("test-source", skipped[0])

    def test_clash_vless_non_none_encryption_is_rejected(self):
        skipped: list[str] = []
        nodes = parse_document(
            "proxies:\n"
            "  - name: bad\n"
            "    type: vless\n"
            "    server: example.com\n"
            "    port: 443\n"
            "    uuid: 00000000-0000-4000-8000-000000000001\n"
            "    encryption: mlkem768x25519plus.native.0rtt.secret\n",
            "test",
            skipped,
        )
        self.assertEqual(nodes, [])
        self.assertEqual(len(skipped), 1)

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

    def test_shadowsocks_legacy_cipher_is_normalized(self):
        credential = base64.urlsafe_b64encode(b"chacha20-poly1305:secret").decode().rstrip("=")
        node = parse_uri(f"ss://{credential}@example.com:443#legacy", "test")
        self.assertEqual(node.clash["cipher"], "chacha20-ietf-poly1305")
        reparsed = parse_uri(node.uri, "test")
        self.assertEqual(reparsed.clash["cipher"], "chacha20-ietf-poly1305")

    def test_invalid_shadowsocks_cipher_is_rejected(self):
        credential = base64.urlsafe_b64encode(b"ss:secret").decode().rstrip("=")
        with self.assertRaisesRegex(ValueError, "unsupported Shadowsocks cipher"):
            parse_uri(f"ss://{credential}@example.com:443#invalid", "test")


if __name__ == "__main__":
    unittest.main()
