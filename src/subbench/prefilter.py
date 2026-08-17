from __future__ import annotations

import socket
import time
import random
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from .models import Node


Endpoint = tuple[str, int]
Connector = Callable[[Endpoint, float], object]
Requester = Callable[..., Any]
Randomizer = Callable[[float, float], float]


def normalize_aliyun_url(value: str) -> str:
    """Return a usable FC HTTP URL, removing common Secret copy/paste wrappers."""
    url = str(value or "").strip().strip("\"'").strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


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
    interval_seconds: float = 0.2,
    max_consecutive_errors: int = 3,
    workers: int = 3,
    requester: Requester | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    randomizer: Randomizer = random.uniform,
    interval_jitter_seconds: float = 0.1,
) -> list[Node]:
    endpoint_nodes: dict[Endpoint, list[Node]] = defaultdict(list)
    for node in nodes:
        endpoint = _endpoint(node)
        if endpoint:
            endpoint_nodes[endpoint].append(node)

    endpoints = list(endpoint_nodes)
    url = normalize_aliyun_url(url)
    if not url:
        if endpoints:
            print(
                "Aliyun FC TCP prefilter skipped: ALIYUN_FC_URL must be an exact http:// or https:// URL.",
                flush=True,
            )
        return nodes
    if not endpoints:
        return nodes

    results: dict[Endpoint, bool] = {}
    errors = 0
    consecutive_errors = 0
    error_samples: list[str] = []
    error_limit = max(1, max_consecutive_errors)
    progress_interval = 10
    interval_low = max(0.0, interval_seconds - abs(interval_jitter_seconds))
    interval_high = max(interval_low, interval_seconds + abs(interval_jitter_seconds))
    print(
        f"Aliyun FC TCP prefilter starting: {len(endpoints)} unique endpoints, "
        f"random {interval_low:.1f}-{interval_high:.1f}s interval, "
        f"up to {max(1, workers)} concurrent requests.",
        flush=True,
    )
    def check(endpoint: Endpoint) -> tuple[Endpoint, bool | None, str | None]:
        server, port = endpoint
        local_session: requests.Session | None = None
        try:
            if requester is None:
                local_session = requests.Session()
                local_session.trust_env = False
                request = local_session.get
            else:
                request = requester
            response = request(
                url,
                params={"ip": server, "port": port},
                timeout=max(1.0, timeout_seconds),
            )
            if response.status_code != 200:
                raise requests.RequestException(f"HTTP {response.status_code}")
            return endpoint, "ok" in response.text.lower(), None
        except (requests.RequestException, OSError, TimeoutError) as exc:
            detail = str(exc) if str(exc).startswith("HTTP ") else type(exc).__name__
            return endpoint, None, detail
        finally:
            if local_session is not None:
                local_session.close()
            sleeper(randomizer(interval_low, interval_high))

    worker_count = max(1, workers)
    executor = ThreadPoolExecutor(max_workers=worker_count)
    pending = {
        executor.submit(check, endpoint)
        for endpoint in endpoints[:worker_count]
    }
    next_index = worker_count
    completed = 0
    unavailable = False
    try:
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                endpoint, reachable, detail = future.result()
                completed += 1
                server, port = endpoint
                if detail is None:
                    results[endpoint] = bool(reachable)
                    consecutive_errors = 0
                else:
                    errors += 1
                    consecutive_errors += 1
                    if len(error_samples) < 3:
                        error_samples.append(f"{server}:{port} ({detail})")
                    if consecutive_errors >= error_limit:
                        unavailable = True

                if not unavailable and next_index < len(endpoints):
                    pending.add(executor.submit(check, endpoints[next_index]))
                    next_index += 1

                if completed % progress_interval == 0 or completed == len(endpoints):
                    reachable_count = sum(results.values())
                    print(
                        f"Aliyun FC TCP prefilter {completed}/{len(endpoints)}: "
                        f"{reachable_count} reachable, {errors} request errors",
                        flush=True,
                    )
            if unavailable:
                for future in pending:
                    future.cancel()
                print(
                    "Aliyun FC TCP prefilter is unavailable; keeping untested endpoints. "
                    f"Error samples: {', '.join(error_samples)}",
                    flush=True,
                )
                break
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

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
