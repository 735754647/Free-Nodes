import unittest
from pathlib import Path

from subbench.benchmark import MihomoBenchmark, _parse_geo_payload
from subbench.cli import _filter_benchmarked_nodes, _rename_nodes_by_country
from subbench.models import Node


def make_node(name: str, latency: int = 100, speed: float | None = None, error: str | None = None) -> Node:
    return Node(
        uri=f"vless://id@example.com:443#{name}",
        scheme="vless",
        name=name,
        clash={"name": name, "type": "vless", "server": "example.com", "port": 443, "uuid": "id"},
        source="test",
        latency_ms=latency,
        speed_mbps=speed,
        error=error,
    )


class BenchmarkTests(unittest.TestCase):
    def test_zero_speed_limit_tests_every_latency_valid_node(self):
        nodes = [make_node("one", 100), make_node("two", 200), make_node("three", 300)]
        benchmark = MihomoBenchmark(
            binary=Path("mihomo"),
            workdir=Path(".work-test"),
            nodes=nodes,
            latency_url="https://www.google.com/generate_204",
            speed_url="https://example.com/test.bin",
            geo_url="https://api.country.is/",
            timeout_ms=8000,
            speed_bytes=1000,
            speed_limit=0,
            speed_timeout_seconds=15,
            workers=1,
        )
        benchmark.benchmark_latency = lambda candidates: candidates
        tested: list[str] = []

        def fake_speed(node: Node) -> Node:
            tested.append(node.name)
            node.speed_mbps = 1.0
            return node

        benchmark.speed = fake_speed
        benchmark.benchmark(nodes)
        self.assertEqual(tested, ["one", "two", "three"])

    def test_filter_rejects_incomplete_or_failed_measurements(self):
        nodes = [
            make_node("good", 100, 5.0),
            make_node("no-speed", 100),
            make_node("speed-error", 100, error="speed: timeout"),
            make_node("too-slow", 100, 0.1),
            make_node("too-late", 4000, 5.0),
        ]
        filtered = _filter_benchmarked_nodes(nodes, max_latency=3000, min_speed=0.5)
        self.assertEqual([node.name for node in filtered], ["good"])

    def test_nodes_are_renamed_with_exit_country_and_protocol(self):
        first = make_node("upstream one", 100, 5.0)
        second = make_node("upstream two", 120, 4.0)
        first.metadata["country_code"] = "US"
        second.metadata["country_code"] = "US"
        _rename_nodes_by_country([first, second])
        self.assertEqual(first.name, "🇺🇸 US | VLESS | 001")
        self.assertEqual(second.name, "🇺🇸 US | VLESS | 002")

    def test_cloudflare_trace_geo_payload(self):
        country, exit_ip = _parse_geo_payload("ip=203.0.113.10\nloc=JP\ncolo=NRT\n")
        self.assertEqual(country, "JP")
        self.assertEqual(exit_ip, "203.0.113.10")

    def test_json_geo_payload(self):
        country, exit_ip = _parse_geo_payload('{"ip":"203.0.113.20","country":"SG"}')
        self.assertEqual(country, "SG")
        self.assertEqual(exit_ip, "203.0.113.20")


if __name__ == "__main__":
    unittest.main()
