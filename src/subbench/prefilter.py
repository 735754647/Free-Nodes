from __future__ import annotations

import socket
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .models import Node


Endpoint = tuple[str, int]
Connector = Callable[[Endpoint, float], object]


def _endpoint(node: Node) -> Endpoint | None:
    if not node.clash:
        return None
    server = str(node.clash.get("server") or "").strip()
    try:
        port = int(node.clash.get("port"))
    except (TypeError, ValueError):
        return None
    if not server or not 1 <= port <= 65535:
        return None
    return server, port


def tcp_prefilter(
    nodes: list[Node],
    timeout_seconds: float = 3.0,
    workers: int = 64,
    connector: Connector | None = None,
) -> list[Node]:
    connect = connector or socket.create_connection
    endpoint_nodes: dict[Endpoint, list[Node]] = defaultdict(list)
    for node in nodes:
        endpoint = _endpoint(node)
        if endpoint:
            endpoint_nodes[endpoint].append(node)

    def check(endpoint: Endpoint) -> tuple[Endpoint, float | None]:
        started = time.monotonic()
        try:
            connection = connect(endpoint, timeout_seconds)
            close = getattr(connection, "close", None)
            if callable(close):
                close()
            return endpoint, round((time.monotonic() - started) * 1000, 1)
        except (OSError, TimeoutError):
            return endpoint, None

    reachable: dict[Endpoint, float] = {}
    endpoints = list(endpoint_nodes)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(check, endpoint) for endpoint in endpoints]
        total = len(futures)
        for index, future in enumerate(as_completed(futures), start=1):
            endpoint, connect_ms = future.result()
            if connect_ms is not None:
                reachable[endpoint] = connect_ms
            if index % 100 == 0 or index == total:
                print(f"TCP prefilter {index}/{total}: {len(reachable)} reachable endpoints", flush=True)

    kept: list[Node] = []
    for node in nodes:
        endpoint = _endpoint(node)
        if endpoint not in reachable:
            continue
        node.metadata["tcp_connect_ms"] = reachable[endpoint]
        kept.append(node)

    print(
        f"TCP prefilter kept {len(kept)}/{len(nodes)} nodes "
        f"across {len(reachable)}/{len(endpoints)} reachable endpoints.",
        flush=True,
    )
    return kept
