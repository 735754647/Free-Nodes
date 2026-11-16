import unittest
from unittest.mock import patch

import requests

from subbench.parsers import parse_document
from subbench.sources import (
    SourceSpec,
    _extract_cfmem_article_url,
    _extract_cfmem_subscription_urls,
    _is_cfmem_landing_page,
    fetch_sources,
)
from test_sources import DummyResponse


HOME = "https://www.cfmem.com/"
ARTICLE = "https://www.cfmem.com/2026/11/20261116-27-trojan-2-hysteria2-1-vless.html"
TOKEN = "a" * 64
MIHOMO_URL = f"https://nodebuf.com/node-sub/{TOKEN}/mihomo"
V2RAY_URL = f"https://nodebuf.com/node-sub/{TOKEN}/v2ray"
OLDER_ARTICLE = (
    "<a href='/2026/11/20261115-30-older.html'>"
    "2026\u5e7411\u670815\u65e5 \u514d\u8d39\u8282\u70b9\u66f4\u65b0</a>"
)
LATEST_ARTICLE = (
    f"<a href='{ARTICLE}'><span>2026\u5e7411\u670816\u65e5</span> "
    "\u514d\u8d39\u8282\u70b9\u66f4\u65b0</a>"
)
ARTICLE_HTML = (
    f'<a href="{V2RAY_URL}">V2Ray \u8ba2\u9605\u94fe\u63a5</a>'
    f'<a href="{MIHOMO_URL}">Clash \u8ba2\u9605\u94fe\u63a5</a>'
)
MIHOMO_SUBSCRIPTION = """proxies:
  - name: anytls
    type: anytls
    server: anytls.example
    port: 443
    password: secret
    sni: anytls.example
  - name: hysteria
    type: hysteria
    server: hysteria.example
    port: 443
    auth-str: secret
    up: 10 Mbps
    down: 50 Mbps
"""
V2RAY_SUBSCRIPTION = "vless://id@example.com:443?encryption=none#sample"


class CfmemSourceTests(unittest.TestCase):
    def test_only_recognizes_cfmem_homepage(self):
        self.assertTrue(_is_cfmem_landing_page(HOME))
        self.assertTrue(_is_cfmem_landing_page("https://cfmem.com"))
        self.assertFalse(_is_cfmem_landing_page(ARTICLE))
        self.assertFalse(_is_cfmem_landing_page(HOME + "?page=2"))
        self.assertFalse(_is_cfmem_landing_page("https://cfmem.com.example.org/"))

    def test_selects_latest_dated_node_article(self):
        self.assertEqual(
            _extract_cfmem_article_url(OLDER_ARTICLE + LATEST_ARTICLE, HOME),
            ARTICLE,
        )

    def test_same_day_article_order_is_preserved(self):
        other = (
            "https://www.cfmem.com/2026/11/20261116-29-other.html"
        )
        document = LATEST_ARTICLE + (
            f"<a href='{other}'>2026\u5e7411\u670816\u65e5 \u514d\u8d39\u8282\u70b9</a>"
        )
        self.assertEqual(_extract_cfmem_article_url(document, HOME), ARTICLE)

    def test_ignores_invalid_dates_and_external_article_links(self):
        document = (
            LATEST_ARTICLE
            + "<a href='/2026/11/20261132-invalid.html'>"
            "2099\u5e7413\u670832\u65e5 \u514d\u8d39\u8282\u70b9</a>"
            + "<a href='https://evil.example/2026/11/20261130-post.html'>"
            "2099\u5e7411\u670830\u65e5 \u514d\u8d39\u8282\u70b9</a>"
        )
        self.assertEqual(_extract_cfmem_article_url(document, HOME), ARTICLE)

    def test_extracts_and_prioritizes_only_supported_nodebuf_formats(self):
        document = (
            ARTICLE_HTML
            + f'<a href="https://nodebuf.com/node-sub/{TOKEN}/singbox">Sing-box</a>'
            + f'<a href="https://evil.example/node-sub/{TOKEN}/mihomo">bad host</a>'
            + f'<a href="https://nodebuf.com/node-sub/{TOKEN}/unknown">unknown</a>'
        )
        self.assertEqual(
            _extract_cfmem_subscription_urls(document, ARTICLE),
            [MIHOMO_URL, V2RAY_URL],
        )

    def test_rejects_article_without_supported_subscription_links(self):
        with self.assertRaisesRegex(ValueError, "did not expose"):
            _extract_cfmem_subscription_urls(
                f'<a href="https://nodebuf.com/node-sub/{TOKEN}/singbox">Sing-box</a>',
                ARTICLE,
            )

    def test_parser_preserves_anytls_and_hysteria_yaml_nodes(self):
        nodes = parse_document(MIHOMO_SUBSCRIPTION, "CFmem")
        self.assertEqual([node.scheme for node in nodes], ["anytls", "hysteria"])
        self.assertEqual(nodes[0].uri, "")
        self.assertEqual(nodes[0].clash["password"], "secret")
        self.assertEqual(nodes[1].clash["auth-str"], "secret")

    def test_fetches_latest_article_and_mihomo_subscription(self):
        responses = [
            DummyResponse(OLDER_ARTICLE + LATEST_ARTICLE),
            DummyResponse(ARTICLE_HTML),
            DummyResponse(MIHOMO_SUBSCRIPTION),
        ]
        with patch("subbench.sources.requests.get", side_effect=responses) as requester:
            result = fetch_sources([SourceSpec("CFmem", HOME)], workers=1)[0]
        self.assertIsNone(result.error)
        self.assertEqual(result.text, MIHOMO_SUBSCRIPTION)
        self.assertEqual(
            [call.args[0] for call in requester.call_args_list],
            [HOME, ARTICLE, MIHOMO_URL],
        )

    def test_falls_back_to_v2ray_when_mihomo_has_no_supported_nodes(self):
        responses = [
            DummyResponse(LATEST_ARTICLE),
            DummyResponse(ARTICLE_HTML),
            DummyResponse("<html>access denied</html>"),
            DummyResponse(V2RAY_SUBSCRIPTION),
        ]
        with patch("subbench.sources.requests.get", side_effect=responses) as requester:
            result = fetch_sources(
                [SourceSpec("CFmem", HOME)], workers=1, retries=1, retry_backoff_seconds=0,
            )[0]
        self.assertIsNone(result.error)
        self.assertEqual(result.text, V2RAY_SUBSCRIPTION)
        self.assertEqual(requester.call_args_list[-2].args[0], MIHOMO_URL)
        self.assertEqual(requester.call_args_list[-1].args[0], V2RAY_URL)

    def test_reports_missing_latest_article(self):
        with patch("subbench.sources.requests.get", return_value=DummyResponse("<html>empty</html>")):
            result = fetch_sources([SourceSpec("CFmem", HOME)], workers=1)[0]
        self.assertIsNone(result.text)
        self.assertIn("did not contain a dated free-node article", result.error or "")


if __name__ == "__main__":
    unittest.main()
