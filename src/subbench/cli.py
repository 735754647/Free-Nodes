from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .benchmark import MihomoBenchmark, write_mihomo_config
from .models import Node
from .output import prepare_names, write_outputs
from .parsers import parse_document
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
    nodes = list(unique.values())[: _int_env("MAX_NODES", 300)]
    if not nodes:
        raise RuntimeError("Sources were fetched, but no supported nodes were found.")
    prepare_names(nodes)

    mihomo = Path(args.mihomo)
    if args.skip_benchmark:
        print("Benchmark skipped; publishing parsed nodes.")
    elif not mihomo.exists():
        raise RuntimeError(f"Mihomo binary not found: {mihomo}")
    else:
        workdir = Path(args.workdir)
        with MihomoBenchmark(
            binary=mihomo,
            workdir=workdir,
            nodes=nodes,
            latency_url=os.environ.get("LATENCY_TEST_URL", "https://www.gstatic.com/generate_204"),
            speed_url=os.environ.get(
                "SPEED_TEST_URL",
                "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/release/country.mmdb",
            ),
            timeout_ms=_int_env("LATENCY_TIMEOUT_MS", 8000),
            speed_bytes=_int_env("SPEED_TEST_BYTES", 1_000_000),
            speed_limit=_int_env("SPEED_TEST_LIMIT", 50),
            workers=_int_env("BENCHMARK_WORKERS", 12),
        ) as benchmark:
            write_mihomo_config(workdir / "mihomo-nodes.yaml", nodes)
            nodes = benchmark.benchmark(nodes)

    max_latency = _int_env("MAX_LATENCY_MS", 5000)
    min_speed = _float_env("MIN_SPEED_MBPS", 0.0)
    nodes = [
        node
        for node in nodes
        if (node.latency_ms is None or node.latency_ms <= max_latency)
        and (node.speed_mbps is None or node.speed_mbps >= min_speed)
    ]
    nodes.sort(
        key=lambda node: (
            node.speed_mbps is None,
            -(node.speed_mbps or 0),
            node.latency_ms is None,
            node.latency_ms or 10**9,
        )
    )
    nodes = nodes[: _int_env("MAX_OUTPUT_NODES", 100)]
    if not nodes:
        failures = "; ".join(node.error or "unknown error" for node in unique.values() if node.error)
        raise RuntimeError(f"All nodes failed the configured latency/speed filters. {failures[:1000]}")

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
