from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import yaml

from .models import Node


def _safe_name(name: str, index: int, used: set[str]) -> str:
    clean = " ".join(name.split()).strip() or f"node-{index:03d}"
    candidate = clean[:80]
    suffix = 2
    while candidate in used:
        candidate = f"{clean[:70]}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def prepare_names(nodes: list[Node]) -> None:
    used: set[str] = {"AUTO", "PROXY", "BENCHMARK", "DIRECT"}
    for index, node in enumerate(nodes, start=1):
        node.name = _safe_name(node.name, index, used)
        if node.clash:
            node.clash["name"] = node.name


def _rename_uri(uri: str, scheme: str, name: str) -> str:
    if scheme == "vmess" and uri.startswith("vmess://"):
        try:
            encoded = uri.split("://", 1)[1].split("#", 1)[0]
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            payload["ps"] = name
            rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return "vmess://" + base64.urlsafe_b64encode(rendered).decode("ascii").rstrip("=")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
            return uri
    main = uri.split("#", 1)[0]
    return f"{main}#{quote(name, safe='')}"


def write_outputs(output_dir: Path, nodes: list[Node], source_errors: list[dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepare_names(nodes)

    uris = [_rename_uri(node.uri, node.scheme, node.name) for node in nodes if node.uri]
    raw = "\n".join(uris) + ("\n" if uris else "")
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    (output_dir / "v2ray.txt").write_text(encoded + "\n", encoding="ascii")
    (output_dir / "v2ray-raw.txt").write_text(raw, encoding="utf-8")

    proxies = [node.clash for node in nodes if node.clash]
    names = [proxy["name"] for proxy in proxies]
    if names:
        proxy_groups = [
            {
                "name": "AUTO",
                "type": "url-test",
                "url": "https://www.google.com/generate_204",
                "interval": 300,
                "tolerance": 100,
                "proxies": names,
            },
            {"name": "PROXY", "type": "select", "proxies": ["AUTO", "DIRECT", *names]},
        ]
    else:
        proxy_groups = [{"name": "PROXY", "type": "select", "proxies": ["DIRECT"]}]

    clash_config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": proxies,
        "proxy-groups": proxy_groups,
        "rules": ["MATCH,PROXY"],
    }
    (output_dir / "clash.yaml").write_text(
        yaml.safe_dump(clash_config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes),
        "source_errors": source_errors,
        "nodes": [node.report_dict() for node in nodes],
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rows = "".join(
        f"<tr><td>{index}</td><td>{node.name}</td><td>{node.scheme}</td>"
        f"<td>{node.latency_ms or '-'} ms</td><td>{node.speed_mbps or '-'} Mbps</td></tr>"
        for index, node in enumerate(nodes, start=1)
    )
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>Node subscriptions</title>
<style>body{{font:16px system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}code{{background:#f3f3f3;padding:2px 4px}}</style>
<h1>Node subscriptions</h1>
<p>Generated {report['generated_at']} with {len(nodes)} usable nodes.</p>
<ul><li><a href="v2ray.txt">V2Ray Base64 subscription</a></li><li><a href="clash.yaml">Clash/Mihomo config</a></li><li><a href="v2ray-raw.txt">Raw links</a></li><li><a href="report.json">JSON report</a></li></ul>
<table><thead><tr><th>#</th><th>Name</th><th>Type</th><th>Latency</th><th>Speed</th></tr></thead><tbody>{rows}</tbody></table>
"""
    (output_dir / "index.html").write_text(page, encoding="utf-8")
