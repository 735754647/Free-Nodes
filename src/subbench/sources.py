from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests


_V2NODES_SUBSCRIPTION_RE = re.compile(
    r"https://www\.v2nodes\.com/subscriptions/country/all/\?key=[A-Za-z0-9_-]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str


@dataclass
class SourceResult:
    source: SourceSpec
    text: str | None = None
    error: str | None = None


def _is_v2nodes_landing_page(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    is_v2nodes_host = hostname == "v2nodes.com" or hostname.endswith(".v2nodes.com")
    return parsed.scheme == "https" and is_v2nodes_host and parsed.path.rstrip("/") == ""


def _extract_v2nodes_subscription_url(document: str) -> str:
    match = _V2NODES_SUBSCRIPTION_RE.search(html.unescape(document))
    if not match:
        raise ValueError("V2Nodes landing page did not contain a subscription link")
    return match.group(0)


def load_sources(path: Path) -> list[SourceSpec]:
    lines: list[str] = []
    if path.exists():
        lines.extend(path.read_text(encoding="utf-8").splitlines())
    lines.extend(os.environ.get("SOURCE_URLS", "").splitlines())

    specs: list[SourceSpec] = []
    seen: set[str] = set()
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if "|" in value:
            label, url = (item.strip() for item in value.split("|", 1))
        else:
            url = value
            label = url
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        specs.append(SourceSpec(name=label or url, url=url))
    return specs


def fetch_sources(
    specs: list[SourceSpec],
    timeout_seconds: int = 20,
    workers: int = 8,
    max_bytes: int = 10 * 1024 * 1024,
) -> list[SourceResult]:
    if not specs:
        return []

    def download(url: str) -> str:
        response = requests.get(
            url,
            headers={"User-Agent": "node-subscription-builder/0.1"},
            timeout=timeout_seconds,
            stream=True,
        )
        response.raise_for_status()
        buffer = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise ValueError(f"source exceeds {max_bytes} bytes")
        encoding = response.encoding or "utf-8"
        return buffer.decode(encoding, errors="replace")

    def fetch(spec: SourceSpec) -> SourceResult:
        try:
            url = spec.url
            if _is_v2nodes_landing_page(url):
                url = _extract_v2nodes_subscription_url(download(url))
                print(f"Resolved the current V2Nodes subscription for {spec.name}.", flush=True)
            return SourceResult(source=spec, text=download(url))
        except (requests.RequestException, ValueError) as exc:
            return SourceResult(source=spec, error=str(exc))

    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(fetch, spec): spec for spec in specs}
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item.source.name)
