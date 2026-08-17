import unittest
from unittest.mock import patch

from subbench.sources import (
    SourceSpec,
    _extract_v2nodes_subscription_url,
    fetch_sources,
)


class DummyResponse:
    def __init__(self, text: str):
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self.content


class SourceTests(unittest.TestCase):
    def test_extracts_v2nodes_subscription_from_landing_page(self):
        url = "https://www.v2nodes.com/subscriptions/country/all/?key=ABC123"
        document = f'<input data-config="{url}" value="{url}">'
        self.assertEqual(_extract_v2nodes_subscription_url(document), url)

    def test_v2nodes_landing_page_resolves_current_key_before_download(self):
        subscription_url = (
            "https://www.v2nodes.com/subscriptions/country/all/?key=ABC123"
        )
        responses = [
            DummyResponse(f'<input value="{subscription_url}">'),
            DummyResponse("vless://example"),
        ]
        with patch("subbench.sources.requests.get", side_effect=responses) as requester:
            results = fetch_sources(
                [SourceSpec(name="V2Nodes", url="https://www.v2nodes.com/")],
                workers=1,
            )

        self.assertEqual(results[0].text, "vless://example")
        self.assertIsNone(results[0].error)
        self.assertEqual(requester.call_count, 2)
        self.assertEqual(requester.call_args_list[1].args[0], subscription_url)

    def test_v2nodes_missing_subscription_link_is_reported(self):
        with patch(
            "subbench.sources.requests.get",
            return_value=DummyResponse("<html>No subscription here</html>"),
        ) as requester:
            results = fetch_sources(
                [SourceSpec(name="V2Nodes", url="https://www.v2nodes.com/")],
                workers=1,
            )

        self.assertIsNone(results[0].text)
        self.assertIn("did not contain a subscription link", results[0].error or "")
        self.assertEqual(requester.call_count, 1)


if __name__ == "__main__":
    unittest.main()
