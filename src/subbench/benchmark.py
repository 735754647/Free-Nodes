from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .models import Node


def _parse_geo_payload(text: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        payload = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                payload[key.strip()] = value.strip()
    country_code = str(payload.get("country") or payload.get("loc") or "").upper()
    if len(country_code) != 2 or not country_code.isalpha():
        country_code = ""
    exit_ip = str(payload.get("ip") or payload.get("clientIp") or "").strip()
    return country_code or None, exit_ip or None


class MihomoBenchmark:
    def __init__(
        self,
        binary: Path,
        workdir: Path,
        nodes: list[Node],
        latency_url: str,
        speed_url: str,
        geo_url: str,
        timeout_ms: int,
        speed_bytes: int,
        speed_limit: int,
        speed_timeout_seconds: int,
        workers: int,
        speed_enabled: bool = True,
        geo_workers: int | None = None,
        latency_attempts: int = 2,
    ) -> None:
        self.binary = binary
        self.workdir = workdir
        self.nodes = nodes
        self.latency_url = latency_url
        self.speed_url = speed_url
        self.geo_urls = [item.strip() for item in geo_url.split(",") if item.strip()]
        self.timeout_ms = timeout_ms
        self.speed_bytes = speed_bytes
        self.speed_limit = speed_limit
        self.speed_timeout_seconds = max(1, speed_timeout_seconds)
        self.workers = max(1, workers)
        self.geo_workers = max(1, geo_workers or workers)
        self.latency_attempts = max(1, latency_attempts)
        self.speed_enabled = speed_enabled
        self.controller = "http://127.0.0.1:9090"
        self.proxy_port = 7890
        self.listener_port_base = 20000
        testable_nodes = [node for node in nodes if node.clash]
        if testable_nodes and self.listener_port_base + len(testable_nodes) - 1 > 65535:
            raise ValueError("Too many nodes for dedicated Mihomo benchmark listeners.")
        self.node_proxy_ports = {
            node.name: self.listener_port_base + index
            for index, node in enumerate(testable_nodes)
        }
        self.process: subprocess.Popen[str] | None = None
        self.log_handle = None

    def __enter__(self) -> "MihomoBenchmark":
        self.workdir.mkdir(parents=True, exist_ok=True)
        config_path = self.workdir / "mihomo-benchmark.yaml"
        write_mihomo_config(config_path, self.nodes, self.node_proxy_ports)
        config_path.write_text(
            "external-controller: 127.0.0.1:9090\n"
            + config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        log_path = self.workdir / "mihomo.log"
        self.log_handle = log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(self.binary), "-d", str(self.workdir), "-f", str(config_path)],
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{self.controller}/version", timeout=1)
                if response.ok:
                    return self
            except requests.RequestException:
                time.sleep(0.25)
        log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.log_handle:
            self.log_handle.close()
        raise RuntimeError(f"Mihomo did not start within 60 seconds. Log tail:\n{log_tail}")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.log_handle:
            self.log_handle.close()

    def _proxy_path(self, name: str) -> str:
        return f"{self.controller}/proxies/{quote(name, safe='')}"

    def latency(self, node: Node) -> Node:
        last_error: Exception | None = None
        for _ in range(self.latency_attempts):
            try:
                response = requests.get(
                    f"{self._proxy_path(node.name)}/delay",
                    params={
                        "url": self.latency_url,
                        "timeout": str(self.timeout_ms),
                        "expected": "204",
                    },
                    timeout=max(5, self.timeout_ms / 1000 + 5),
                )
                response.raise_for_status()
                node.latency_ms = int(response.json()["delay"])
                return node
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                last_error = exc
        if last_error:
            node.error = f"latency: {last_error}"
        return node

    def benchmark_latency(self, nodes: list[Node]) -> list[Node]:
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.latency, node) for node in nodes]
            measured: list[Node] = []
            total = len(futures)
            for index, future in enumerate(as_completed(futures), start=1):
                measured.append(future.result())
                if index % 100 == 0 or index == total:
                    usable = sum(node.latency_ms is not None for node in measured)
                    print(f"Latency test {index}/{total}: {usable} reachable", flush=True)
            return measured

    def _proxies_for_port(self, port: int) -> dict[str, str]:
        proxy = f"http://127.0.0.1:{port}"
        return {"http": proxy, "https": proxy}

    def geolocate(self, node: Node, proxy_port: int | None = None) -> None:
        port = proxy_port or self.proxy_port
        for geo_url in self.geo_urls:
            try:
                location = requests.get(
                    geo_url,
                    proxies=self._proxies_for_port(port),
                    timeout=(3, 5),
                )
                location.raise_for_status()
                country_code, exit_ip = _parse_geo_payload(location.text)
                if country_code:
                    node.metadata["country_code"] = country_code
                if exit_ip:
                    node.metadata["exit_ip"] = exit_ip
                if country_code:
                    break
            except requests.RequestException:
                continue

    def select(self, node: Node) -> None:
        selected = requests.put(
            f"{self.controller}/proxies/BENCHMARK",
            json={"name": node.name},
            timeout=10,
        )
        selected.raise_for_status()

    def locate(self, node: Node) -> Node:
        try:
            proxy_port = self.node_proxy_ports.get(node.name)
            if proxy_port is None:
                self.select(node)
            self.geolocate(node, proxy_port)
        except requests.RequestException as exc:
            node.metadata["geo_error"] = str(exc)
        return node

    def speed(self, node: Node) -> Node:
        try:
            self.select(node)

            started = time.monotonic()
            received = 0
            with requests.get(
                self.speed_url,
                proxies=self._proxies_for_port(self.proxy_port),
                stream=True,
                timeout=(min(10, self.speed_timeout_seconds), self.speed_timeout_seconds),
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    received += len(chunk)
                    if received >= self.speed_bytes:
                        break
            elapsed = max(time.monotonic() - started, 0.001)
            node.speed_mbps = round(received * 8 / elapsed / 1_000_000, 2)
            self.geolocate(node)
        except (requests.RequestException, ValueError) as exc:
            node.error = f"speed: {exc}"
        return node

    def benchmark(self, nodes: list[Node]) -> list[Node]:
        measured = self.benchmark_latency(nodes)
        valid = [node for node in measured if node.latency_ms is not None]
        valid.sort(key=lambda node: (node.latency_ms or 10**9, node.name))
        if not self.speed_enabled:
            total = len(valid)
            with ThreadPoolExecutor(max_workers=self.geo_workers) as executor:
                futures = [executor.submit(self.locate, node) for node in valid]
                located_nodes: list[Node] = []
                for index, future in enumerate(as_completed(futures), start=1):
                    located_nodes.append(future.result())
                    if index % 50 == 0 or index == total:
                        located = sum(bool(item.metadata.get("country_code")) for item in located_nodes)
                        print(f"Location test {index}/{total}: {located} countries detected", flush=True)
            return valid

        speed_candidates = valid if self.speed_limit <= 0 else valid[: self.speed_limit]
        total = len(speed_candidates)
        for index, node in enumerate(speed_candidates, start=1):
            self.speed(node)
            result = f"{node.speed_mbps} Mbps" if node.speed_mbps is not None else node.error or "failed"
            print(f"Speed test {index}/{total}: {node.name} - {result}", flush=True)
        return valid


def write_mihomo_config(
    path: Path,
    nodes: list[Node],
    listener_ports: dict[str, int] | None = None,
) -> None:
    import yaml

    names = [node.name for node in nodes if node.clash]
    document = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": [node.clash for node in nodes if node.clash],
        "proxy-groups": [
            {"name": "BENCHMARK", "type": "select", "proxies": names},
        ],
        "rules": ["MATCH,BENCHMARK"],
    }
    if listener_ports:
        document["listeners"] = [
            {
                "name": f"benchmark-{index:04d}",
                "type": "mixed",
                "listen": "127.0.0.1",
                "port": listener_ports[node.name],
                "proxy": node.name,
            }
            for index, node in enumerate(nodes, start=1)
            if node.clash and node.name in listener_ports
        ]
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
