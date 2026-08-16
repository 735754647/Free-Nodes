from __future__ import annotations

import socket
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import requests

from .models import Node


Endpoint = tuple[str, int]
Connector = Callable[[Endpoint, float], object]
Requester = Callable[..., Any]


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
    attempts: int = 2,
    connector: Connector | None = None,
) -> list[Node]:
    connect = connector or socket.create_connection
    endpoint_nodes: dict[Endpoint, list[Node]] = defaultdict(list)
    for node in nodes:
        endpoint = _endpoint(node)
        if endpoint:
            endpoint_nodes[endpoint].append(node)

    def check(endpoint: Endpoint) -> tuple[Endpoint, float | None]:
        for _ in range(max(1, attempts)):
            started = time.monotonic()
            try:
                connection = connect(endpoint, timeout_seconds)
                close = getattr(connection, "close", None)
                if callable(close):
                    close()
                return endpoint, round((time.monotonic() - started) * 1000, 1)
            except (OSError, TimeoutError):
                continue
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


def aliyun_tcp_prefilter(
    nodes: list[Node],
    url: str,
    timeout_seconds: float = 10.0,
    interval_seconds: float = 1.5,
    max_consecutive_errors: int = 3,
    requester: Requester | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[Node]:
    endpoint_nodes: dict[Endpoint, list[Node]] = defaultdict(list)
    for node in nodes:
        endpoint = _endpoint(node)
        if endpoint:
            endpoint_nodes[endpoint].append(node)

    endpoints = list(endpoint_nodes)
    if not url.strip() or not endpoints:
        return nodes

    session: requests.Session | None = None
    if requester is None:
        session = requests.Session()
        session.trust_env = False
        requester = session.get

    results: dict[Endpoint, bool] = {}
    errors = 0
    consecutive_errors = 0
    error_limit = max(1, max_consecutive_errors)
    try:
        for index, endpoint in enumerate(endpoints, start=1):
            server, port = endpoint
            try:
                response = requester(
                    url,
                    params={"ip": server, "port": port},
                    timeout=max(1.0, timeout_seconds),
                )
                if response.status_code != 200:
                    raise requests.RequestException(f"HTTP {response.status_code}")
                results[endpoint] = "ok" in response.text.lower()
                consecutive_errors = 0
            except (requests.RequestException, OSError, TimeoutError):
                errors += 1
                consecutive_errors += 1
                if consecutive_errors >= error_limit:
                    print(
                        "Aliyun FC TCP prefilter is unavailable; keeping untested endpoints.",
                        flush=True,
                    )
                    break
            finally:
                sleeper(max(0.0, interval_seconds))

            if index % 50 == 0 or index == len(endpoints):
                reachable = sum(results.values())
                print(
                    f"Aliyun FC TCP prefilter {index}/{len(endpoints)}: "
                    f"{reachable} reachable, {errors} request errors",
                    flush=True,
                )
    finally:
        if session is not None:
            session.close()

    kept: list[Node] = []
    for node in nodes:
        endpoint = _endpoint(node)
        if results.get(endpoint) is False:
            continue
        if results.get(endpoint) is True:
            node.metadata["aliyun_tcp_reachable"] = True
        kept.append(node)

    rejected = sum(result is False for result in results.values())
    print(
        f"Aliyun FC TCP prefilter kept {len(kept)}/{len(nodes)} nodes; "
        f"rejected {rejected} endpoints and preserved failed or untested checks.",
        flush=True,
    )
    return kept
