import unittest
from unittest.mock import patch

import requests

from subbench.sources import (
    SourceSpec,
    _extract_yudou_article_url,
    _extract_yudou_subscription_urls,
    _is_yudou_landing_page,
    fetch_sources,
)
from test_sources import DummyResponse


HOME = "https://www.yudou789.top/"
ARTICLE = "https://www.yudou789.top/2236.html"
YAML_URL = "https://uu.yudou226.top/202611/20261111mh8eta.yaml"
TEXT_URL = "https://uu.yudou226.top/202611/20261111bax7se.txt"
LANDING = '<a href="/2236.html">2026\u5e7411\u670811\u65e5\u8282\u70b9</a>'
HIDDEN = f'<div style="display:none"><p>{TEXT_URL}</p><p>{YAML_URL}</p></div>'
SUBSCRIPTION = """proxies:
  - name: sample
    type: trojan
    server: example.com
    port: 443
    password: example
"""
RAW_SUBSCRIPTION = "trojan://example@example.com:443#sample"


class YudouSourceTests(unittest.TestCase):
    def test_only_recognizes_configured_homepage(self):
        self.assertTrue(_is_yudou_landing_page(HOME))
        self.assertTrue(_is_yudou_landing_page("https://yudou789.top"))
        self.assertFalse(_is_yudou_landing_page(ARTICLE))
        self.assertFalse(_is_yudou_landing_page(HOME + "?golink=example"))
        self.assertFalse(_is_yudou_landing_page("https://yudou789.top.example.com/"))

    def test_selects_date_instead_of_position_or_article_id(self):
        document = (
            '<a href="/9999.html">2026\u5e7411\u67089\u65e5\u8282\u70b9</a>'
            + LANDING
            + '<a href="/2228.html"><span>2026\u5e7411\u670810\u65e5</span>\u8282\u70b9</a>'
        )
        self.assertEqual(_extract_yudou_article_url(document, HOME), ARTICLE)

    def test_ignores_invalid_dates_external_links_and_other_articles(self):
        document = (
            LANDING
            + '<a href="https://example.com/1.html">2099\u5e7411\u670811\u65e5\u8282\u70b9</a>'
            + '<a href="/2.html">2026\u5e7413\u670831\u65e5\u8282\u70b9</a>'
            + '<a href="/3.html">2026\u5e7411\u670812\u65e5 tutorial</a>'
        )
        self.assertEqual(_extract_yudou_article_url(document, HOME), ARTICLE)

    def test_accepts_title_attribute(self):
        document = (
            '<a href="/2236.html" title="2026\u5e7411\u670811\u65e5\u8282\u70b9">'
            '<img src="image.png"></a>'
        )
        self.assertEqual(_extract_yudou_article_url(document, HOME), ARTICLE)

    def test_extracts_plain_hidden_urls_and_prefers_yaml(self):
        document = HIDDEN + f'<a href="{YAML_URL}">duplicate</a>'
        document += '<a href="https://unrelated.example/config.yaml">other</a>'
        self.assertEqual(_extract_yudou_subscription_urls(document), [YAML_URL, TEXT_URL])

    def test_preserves_url_query_parameters(self):
        document = f'<a href="{YAML_URL}?format=clash&amp;download=1">Download</a>'
        self.assertEqual(
            _extract_yudou_subscription_urls(document),
            [YAML_URL + "?format=clash&download=1"],
        )

    def test_fetches_latest_article_without_password_or_cookie(self):
        responses = [DummyResponse(LANDING), DummyResponse(HIDDEN), DummyResponse(SUBSCRIPTION)]
        with patch("subbench.sources.requests.get", side_effect=responses) as requester:
            result = fetch_sources([SourceSpec("Yudou", HOME)], workers=1)[0]
        self.assertIsNone(result.error)
        self.assertEqual(result.text, SUBSCRIPTION)
        self.assertEqual([call.args[0] for call in requester.call_args_list], [HOME, ARTICLE, YAML_URL])
        for call in requester.call_args_list:
            self.assertNotIn("auth", call.kwargs)
            self.assertNotIn("cookies", call.kwargs)

    def test_retries_yaml_before_falling_back_to_text(self):
        responses = [
            DummyResponse(LANDING), DummyResponse(HIDDEN),
            requests.Timeout("temporary"), requests.Timeout("still unavailable"),
            DummyResponse(RAW_SUBSCRIPTION),
        ]
        with patch("subbench.sources.requests.get", side_effect=responses) as requester:
            result = fetch_sources(
                [SourceSpec("Yudou", HOME)], workers=1, retries=1, retry_backoff_seconds=0,
            )[0]
        self.assertIsNone(result.error)
        self.assertEqual(result.text, RAW_SUBSCRIPTION)
        self.assertEqual(
            [call.args[0] for call in requester.call_args_list],
            [HOME, ARTICLE, YAML_URL, YAML_URL, TEXT_URL],
        )

    def test_http_200_login_page_triggers_text_fallback(self):
        responses = [
            DummyResponse(LANDING), DummyResponse(HIDDEN),
            DummyResponse("<html>Please log in</html>"), DummyResponse(RAW_SUBSCRIPTION),
        ]
        with patch("subbench.sources.requests.get", side_effect=responses):
            result = fetch_sources([SourceSpec("Yudou", HOME)], workers=1)[0]
        self.assertIsNone(result.error)
        self.assertEqual(result.text, RAW_SUBSCRIPTION)

    def test_protected_article_reports_error_without_choosing_old_article(self):
        landing = LANDING + '<a href="/2228.html">2026\u5e7411\u670810\u65e5\u8282\u70b9</a>'
        responses = [DummyResponse(landing), DummyResponse('<form><input type="password"></form>')]
        with patch("subbench.sources.requests.get", side_effect=responses) as requester:
            result = fetch_sources([SourceSpec("Yudou", HOME)], workers=1)[0]
        self.assertIsNone(result.text)
        self.assertIn("did not expose a subscription URL", result.error)
        self.assertEqual(requester.call_count, 2)

    def test_missing_articles_reports_source_error(self):
        with patch("subbench.sources.requests.get", return_value=DummyResponse("<html>Empty</html>")):
            result = fetch_sources([SourceSpec("Yudou", HOME)], workers=1)[0]
        self.assertIsNone(result.text)
        self.assertIn("did not contain a dated node article", result.error)

    def test_all_invalid_subscriptions_reports_error(self):
        responses = [
            DummyResponse(LANDING), DummyResponse(HIDDEN),
            DummyResponse("proxies: []"), DummyResponse("<html>Access denied</html>"),
        ]
        with patch("subbench.sources.requests.get", side_effect=responses):
            result = fetch_sources([SourceSpec("Yudou", HOME)], workers=1)[0]
        self.assertIsNone(result.text)
        self.assertIn("All Yudou subscription links failed", result.error)


if __name__ == "__main__":
    unittest.main()
