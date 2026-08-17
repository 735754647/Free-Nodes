import unittest

import requests

from subbench.models import Node
from subbench.prefilter import aliyun_tcp_prefilter, normalize_aliyun_url, tcp_prefilter


def make_node(name: str, server: str, port: int) -> Node:
    return Node(
        uri=f"vless://id@{server}:{port}#{name}",
        scheme="vless",
        name=name,
        clash={"name": name, "type": "vless", "server": server, "port": port, "uuid": "id"},
        source="test",
    )


class DummyConnection:
    def close(self) -> None:
        return None


class DummyResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class TcpPrefilterTests(unittest.TestCase):
    def test_normalize_aliyun_url_accepts_wrapped_http_url(self):
        self.assertEqual(
            normalize_aliyun_url('  "http://fc.example/"  '),
            "http://fc.example/",
        )
        self.assertEqual(normalize_aliyun_url("http//fc.example/"), "")

    def test_shared_endpoint_is_checked_once_and_keeps_all_nodes(self):
        nodes = [
            make_node("one", "reachable.example", 443),
            make_node("two", "reachable.example", 443),
            make_node("three", "blocked.example", 8443),
        ]
        calls: list[tuple[tuple[str, int], float]] = []

        def connector(endpoint: tuple[str, int], timeout: float):
            calls.append((endpoint, timeout))
            if endpoint[0] == "blocked.example":
                raise TimeoutError("blocked")
            return DummyConnection()

        kept = tcp_prefilter(nodes, timeout_seconds=2.5, workers=2, connector=connector)
        self.assertEqual([node.name for node in kept], ["one", "two"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum(endpoint[0] == "blocked.example" for endpoint, _ in calls), 2)
        self.assertTrue(all(node.metadata.get("tcp_connect_ms") is not None for node in kept))

    def test_transient_tcp_failure_is_retried(self):
        node = make_node("one", "flaky.example", 443)
        attempts = 0

        def connector(endpoint: tuple[str, int], timeout: float):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("temporary")
            return DummyConnection()

        kept = tcp_prefilter([node], timeout_seconds=2.5, workers=1, connector=connector)
        self.assertEqual([item.name for item in kept], ["one"])
        self.assertEqual(attempts, 2)

    def test_aliyun_prefilter_checks_unique_endpoints_and_waits(self):
        nodes = [
            make_node("one", "open.example", 443),
            make_node("two", "open.example", 443),
            make_node("three", "closed.example", 8443),
        ]
        requests_made: list[dict[str, object]] = []
        waits: list[float] = []

        def requester(url: str, **kwargs):
            requests_made.append(kwargs["params"])
            if kwargs["params"]["ip"] == "open.example":
                return DummyResponse('{"status":"ok"}')
            return DummyResponse('{"status":"closed"}')

        kept = aliyun_tcp_prefilter(
            nodes,
            url="http://fc.example/",
            requester=requester,
            sleeper=waits.append,
        )
        self.assertEqual([node.name for node in kept], ["one", "two"])
        self.assertEqual(len(requests_made), 2)
        self.assertEqual(waits, [0.2, 0.2])
        self.assertTrue(all(node.metadata.get("aliyun_tcp_reachable") for node in kept))

    def test_aliyun_prefilter_fails_open_when_service_is_unavailable(self):
        nodes = [
            make_node("one", "one.example", 443),
            make_node("two", "two.example", 443),
            make_node("three", "three.example", 443),
            make_node("four", "four.example", 443),
        ]
        calls = 0

        def requester(url: str, **kwargs):
            nonlocal calls
            calls += 1
            raise requests.RequestException("offline")

        kept = aliyun_tcp_prefilter(
            nodes,
            url="http://fc.example/",
            max_consecutive_errors=3,
            requester=requester,
            sleeper=lambda seconds: None,
        )
        self.assertEqual(kept, nodes)
        self.assertEqual(calls, 3)


if __name__ == "__main__":
    unittest.main()
