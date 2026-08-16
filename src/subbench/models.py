from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass
class Node:
    uri: str
    scheme: str
    name: str
    clash: dict[str, Any] | None
    source: str
    latency_ms: int | None = None
    speed_mbps: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_key(self) -> str:
        if self.clash:
            normalized = {
                key: value
                for key, value in self.clash.items()
                if key not in {"name", "dialer-proxy"}
            }
            return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

        parsed = urlsplit(self.uri)
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))

    def report_dict(self) -> dict[str, Any]:
        server = self.clash.get("server") if self.clash else None
        port = self.clash.get("port") if self.clash else None
        return {
            "name": self.name,
            "type": self.scheme,
            "server": server,
            "port": port,
            "source": self.source,
            "original_name": self.metadata.get("original_name"),
            "country_code": self.metadata.get("country_code"),
            "exit_ip": self.metadata.get("exit_ip"),
            "tcp_connect_ms": self.metadata.get("tcp_connect_ms"),
            "aliyun_tcp_reachable": self.metadata.get("aliyun_tcp_reachable"),
            "latency_ms": self.latency_ms,
            "speed_mbps": self.speed_mbps,
            "error": self.error,
        }
