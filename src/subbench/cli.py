from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .benchmark import MihomoBenchmark, write_mihomo_config
from .countries import country_name_zh
from .models import Node
from .output import prepare_names, write_outputs
from .parsers import parse_document
from .prefilter import tcp_prefilter
from .sources import fetch_sources, load_sources


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _filter_benchmarked_nodes(
    nodes: list[Node],
    max_latency: int,
    min_speed: float,
    require_speed: bool = True,
) -> list[Node]:
    return [
        node
        for node in nodes
        if node.error is None
        and node.latency_ms is not None
        and node.latency_ms <= max_latency
        and (
            not require_speed
            or (node.speed_mbps is not None and node.speed_mbps >= min_speed)
        )
    ]


def _country_flag(country_code: str) -> str:
    code = country_code.upper()
    if len(code) != 2 or not code.isalpha():
        return "🏳️"
    return "".join(chr(ord(character) + 127397) for character in code)


def _rename_nodes_by_country(nodes: list[Node]) -> None:
    counters: dict[tuple[str, str], int] = {}
    for node in nodes:
        country_code = str(node.metadata.get("country_code", "UN")).upper()
        if len(country_code) != 2 or not country_code.isalpha():
            country_code = "UN"
        protocol = node.scheme.upper()
        key = (country_code, protocol)
        counters[key] = counters.get(key, 0) + 1
        node.name = (
            f"{_country_flag(country_code)} {country_name_zh(country_code)}"
            f" | {protocol} | {counters[key]:03d}"
        )
        if node.clash:
            node.clash["name"] = node.name


def run(args: argparse.Namespace) -> int:
    source_specs = load_sources(args.sources)
    if not source_specs:
        raise RuntimeError("No sources configured. Add URLs to config/sources.txt or SOURCE_URLS.")

    source_results = fetch_sources(
        source_specs,
        timeout_seconds=_int_env("SOURCE_TIMEOUT_SECONDS", 20),
        workers=_int_env("FETCH_WORKERS", 8),
    )
    nodes: list[Node] = []
    source_errors: list[dict[str, str]] = []
    for result in source_results:
        if result.error:
            source_errors.append({"source": result.source.name, "error": result.error})
            continue
        nodes.extend(parse_document(result.text or "", result.source.name))

    print(f"Fetched {len(source_results)} sources and parsed {len(nodes)} candidate nodes.")

    unique: dict[str, Node] = {}
    for node in nodes:
        unique.setdefault(node.canonical_key(), node)
    nodes = list(unique.values())
    max_nodes = _int_env("MAX_NODES", 300)
    if max_nodes > 0:
        nodes = nodes[:max_nodes]
    if not nodes:
        raise RuntimeError("Sources were fetched, but no supported nodes were found.")
    for node in nodes:
        node.metadata.setdefault("original_name", node.name)

    mihomo = Path(args.mihomo)
    benchmark_performed = False
    speed_test_enabled = _bool_env("SPEED_TEST_ENABLED", False)
    if args.skip_benchmark:
        print("Benchmark skipped; publishing parsed nodes.")
    elif not mihomo.exists():
        raise RuntimeError(f"Mihomo binary not found: {mihomo}")
    else:
        benchmark_performed = True
        if _bool_env("TCP_PREFILTER_ENABLED", True):
            nodes = tcp_prefilter(
                nodes,
                timeout_seconds=_float_env("TCP_CONNECT_TIMEOUT_SECONDS", 3.0),
                workers=_int_env("TCP_PREFILTER_WORKERS", 64),
            )
        if not nodes:
            print("No nodes passed the TCP prefilter; publishing an empty subscription.")
        else:
            prepare_names(nodes)
            workdir = Path(args.workdir)
            with MihomoBenchmark(
                binary=mihomo,
                workdir=workdir,
                nodes=nodes,
                latency_url=os.environ.get("LATENCY_TEST_URL", "https://www.google.com/generate_204"),
                speed_url=os.environ.get(
                    "SPEED_TEST_URL",
                    "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/release/country.mmdb",
                ),
                geo_url=os.environ.get(
                    "GEOIP_TEST_URLS",
                    "https://www.cloudflare.com/cdn-cgi/trace,https://api.country.is/",
                ),
                timeout_ms=_int_env("LATENCY_TIMEOUT_MS", 8000),
                speed_bytes=_int_env("SPEED_TEST_BYTES", 1_000_000),
                speed_limit=_int_env("SPEED_TEST_LIMIT", 0),
                speed_timeout_seconds=_int_env("SPEED_TIMEOUT_SECONDS", 8),
                workers=_int_env("BENCHMARK_WORKERS", 12),
                speed_enabled=speed_test_enabled,
            ) as benchmark:
                write_mihomo_config(workdir / "mihomo-nodes.yaml", nodes)
                nodes = benchmark.benchmark(nodes)

    max_latency = _int_env("MAX_LATENCY_MS", 3000)
    min_speed = _float_env("MIN_SPEED_MBPS", 0.1)
    if benchmark_performed:
        nodes = _filter_benchmarked_nodes(
            nodes,
            max_latency,
            min_speed,
            require_speed=speed_test_enabled,
        )
    nodes.sort(
        key=lambda node: (
            node.speed_mbps is None,
            -(node.speed_mbps or 0),
            node.latency_ms is None,
            node.latency_ms or 10**9,
        )
    )
    max_output_nodes = _int_env("MAX_OUTPUT_NODES", 100)
    if max_output_nodes > 0:
        nodes = nodes[:max_output_nodes]
    if benchmark_performed:
        _rename_nodes_by_country(nodes)
    if not nodes:
        failures = "; ".join(node.error or "unknown error" for node in unique.values() if node.error)
        source_errors.append(
            {
                "source": "benchmark",
                "error": f"No nodes passed the configured latency/speed filters. {failures[:1000]}",
            }
        )
        print("No nodes passed the configured latency/speed filters; publishing an empty subscription.")

    write_outputs(Path(args.output), nodes, source_errors)
    print(f"Published {len(nodes)} nodes from {len(source_specs)} sources.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", default="run")
    parser.add_argument("--sources", type=Path, default=Path("config/sources.txt"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--workdir", type=Path, default=Path(".work"))
    parser.add_argument("--mihomo", type=Path, default=Path(".bin/mihomo"))
    parser.add_argument("--skip-benchmark", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
