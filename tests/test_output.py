import base64
import json
import unittest
from urllib.parse import unquote

from subbench.output import _rename_uri


class OutputTests(unittest.TestCase):
    def test_vless_fragment_is_replaced(self):
        rendered = _rename_uri("vless://id@example.com:443?security=tls#old", "vless", "🇺🇸 US | VLESS | 001")
        self.assertEqual(unquote(rendered.split("#", 1)[1]), "🇺🇸 US | VLESS | 001")

    def test_vmess_display_name_is_replaced(self):
        payload = base64.urlsafe_b64encode(json.dumps({"ps": "old", "add": "example.com"}).encode()).decode().rstrip("=")
        rendered = _rename_uri(f"vmess://{payload}", "vmess", "🇯🇵 JP | VMESS | 001")
        encoded = rendered.split("://", 1)[1]
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertEqual(json.loads(decoded)["ps"], "🇯🇵 JP | VMESS | 001")


if __name__ == "__main__":
    unittest.main()
