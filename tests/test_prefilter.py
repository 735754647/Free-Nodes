import unittest

from subbench.models import Node
from subbench.prefilter import tcp_prefilter


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


class TcpPrefilterTests(unittest.TestCase):
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
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(node.metadata.get("tcp_connect_ms") is not None for node in kept))


if __name__ == "__main__":
    unittest.main()
