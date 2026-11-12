from __future__ import annotations

import html
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from .parsers import parse_document


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


def _is_yudou_landing_page(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"yudou789.top", "www.yudou789.top"}
        and parsed.path.rstrip("/") == ""
        and not parsed.query
    )


class _ArticleLinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attributes = dict(attrs)
            self.href = attributes.get("href")
            self.label = [attributes.get("title") or ""]

    def handle_data(self, data: str) -> None:
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href is not None:
            self.links.append((self.href, "".join(self.label)))
            self.href = None


def _extract_yudou_article_url(document: str, homepage: str) -> str:
    parser = _ArticleLinksParser()
    parser.feed(document)
    articles: list[tuple[date, str]] = []
    for href, title in parser.links:
        if "\u8282\u70b9" not in title:
            continue
        match = re.search(r"(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5", title)
        url = urljoin(homepage, href)
        parsed = urlsplit(url)
        if (
            not match
            or parsed.scheme != "https"
            or parsed.hostname not in {"yudou789.top", "www.yudou789.top"}
            or not re.fullmatch(r"/\d+\.html", parsed.path)
        ):
            continue
        try:
            article_date = date(*(int(value) for value in match.groups()))
        except ValueError:
            continue
        articles.append((article_date, url))
    if not articles:
        raise ValueError("Yudou landing page did not contain a dated node article")
    return max(articles)[1]


def _extract_yudou_subscription_urls(document: str) -> list[str]:
    urls: list[str] = []
    # The article includes plain-text URLs inside its hidden content as well as links.
    for url in re.findall(r"https://[^\s<>\"']+", html.unescape(document)):
        parsed = urlsplit(url)
        if (
            re.fullmatch(r"(?:[a-z0-9-]+\.)*yudou\d+\.top", parsed.hostname or "")
            and Path(parsed.path).suffix.lower() in {".yaml", ".yml", ".txt"}
            and url not in urls
        ):
            urls.append(url)
    if not urls:
        raise ValueError(
            "Yudou article did not expose a subscription URL; "
            "the page may require authenticated access or its layout may have changed"
        )
    return sorted(urls, key=lambda url: Path(urlsplit(url).path).suffix.lower() == ".txt")


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
    timeout_seconds: float = 60,
    workers: int = 4,
    max_bytes: int = 10 * 1024 * 1024,
    retries: int = 3,
    retry_backoff_seconds: float = 2.0,
) -> list[SourceResult]:
    if not specs:
        return []

    max_attempts = max(1, retries + 1)
    connect_timeout = min(15.0, max(1.0, timeout_seconds))
    read_timeout = max(connect_timeout, timeout_seconds)

    def download(url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            response = None
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": "node-subscription-builder/0.1"},
                    timeout=(connect_timeout, read_timeout),
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
            except requests.RequestException as exc:
                last_error = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                retryable_status = status_code is None or status_code in {408, 425, 429, 500, 502, 503, 504}
                if attempt >= max_attempts or not retryable_status:
                    raise
                delay = max(0.0, retry_backoff_seconds) * attempt
                print(
                    f"Source fetch attempt {attempt}/{max_attempts} failed with "
                    f"{type(exc).__name__}; retrying in {delay:.1f}s.",
                    flush=True,
                )
                if delay:
                    time.sleep(delay)
            finally:
                if response is not None:
                    response.close()
        if last_error is not None:
            raise last_error
        raise RuntimeError("source download failed without an error")

    def fetch(spec: SourceSpec) -> SourceResult:
        try:
            url = spec.url
            if _is_yudou_landing_page(url):
                article_url = _extract_yudou_article_url(download(url), url)
                subscriptions = _extract_yudou_subscription_urls(download(article_url))
                print(f"Resolved the latest Yudou node article: {article_url}", flush=True)
                failures: list[str] = []
                for subscription_url in subscriptions:
                    try:
                        text = download(subscription_url)
                        parsed_nodes = parse_document(text, spec.name)
                        if not parsed_nodes:
                            raise ValueError("subscription did not contain supported nodes")
                        print(
                            f"Fetched {len(parsed_nodes)} supported nodes for {spec.name}.",
                            flush=True,
                        )
                        return SourceResult(source=spec, text=text)
                    except (requests.RequestException, ValueError) as exc:
                        failures.append(str(exc))
                        print(
                            f"Yudou subscription attempt failed with {type(exc).__name__}; "
                            "trying any remaining article links.",
                            flush=True,
                        )
                raise ValueError("All Yudou subscription links failed: " + "; ".join(failures))
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
