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


class MihomoBenchmark:
    def __init__(
        self,
        binary: Path,
        workdir: Path,
        nodes: list[Node],
        latency_url: str,
        speed_url: str,
        timeout_ms: int,
        speed_bytes: int,
        speed_limit: int,
        workers: int,
    ) -> None:
        self.binary = binary
        self.workdir = workdir
        self.nodes = nodes
        self.latency_url = latency_url
        self.speed_url = speed_url
        self.timeout_ms = timeout_ms
        self.speed_bytes = speed_bytes
        self.speed_limit = speed_limit
        self.workers = max(1, workers)
        self.controller = "http://127.0.0.1:9090"
        self.proxy_port = 7890
        self.process: subprocess.Popen[str] | None = None
        self.log_handle = None

    def __enter__(self) -> "MihomoBenchmark":
        self.workdir.mkdir(parents=True, exist_ok=True)
        config_path = self.workdir / "mihomo-benchmark.yaml"
        write_mihomo_config(config_path, self.nodes)
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
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            node.error = f"latency: {exc}"
        return node

    def benchmark_latency(self, nodes: list[Node]) -> list[Node]:
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.latency, node) for node in nodes]
            return [future.result() for future in as_completed(futures)]

    def speed(self, node: Node) -> Node:
        try:
            selected = requests.put(
                f"{self.controller}/proxies/BENCHMARK",
                json={"name": node.name},
                timeout=10,
            )
            selected.raise_for_status()

            started = time.monotonic()
            received = 0
            with requests.get(
                self.speed_url,
                proxies={"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
                stream=True,
                timeout=(10, 30),
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    received += len(chunk)
                    if received >= self.speed_bytes:
                        break
            elapsed = max(time.monotonic() - started, 0.001)
            node.speed_mbps = round(received * 8 / elapsed / 1_000_000, 2)
        except (requests.RequestException, ValueError) as exc:
            node.error = f"speed: {exc}"
        return node

    def benchmark(self, nodes: list[Node]) -> list[Node]:
        measured = self.benchmark_latency(nodes)
        valid = [node for node in measured if node.latency_ms is not None]
        valid.sort(key=lambda node: (node.latency_ms or 10**9, node.name))
        for node in valid[: self.speed_limit]:
            self.speed(node)
        return valid


def write_mihomo_config(path: Path, nodes: list[Node]) -> None:
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
            {
                "name": "AUTO",
                "type": "url-test",
                "url": "https://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 100,
                "proxies": names,
            },
            {"name": "BENCHMARK", "type": "select", "proxies": names},
            {"name": "PROXY", "type": "select", "proxies": ["AUTO", "BENCHMARK", "DIRECT", *names]},
        ],
        "rules": ["MATCH,PROXY"],
    }
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
