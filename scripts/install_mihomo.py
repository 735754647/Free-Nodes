from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import stat
import tarfile
import urllib.request
import zipfile
from pathlib import Path


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "node-subscription-builder/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def choose_asset(release: dict) -> dict:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux" and machine in {"x86_64", "amd64"}:
        patterns = ("mihomo-linux-amd64-v3-", "mihomo-linux-amd64-compatible-", "mihomo-linux-amd64-")
    elif system == "linux" and machine in {"aarch64", "arm64"}:
        patterns = ("mihomo-linux-arm64-",)
    elif system == "windows" and machine in {"x86_64", "amd64"}:
        patterns = ("mihomo-windows-amd64-v3-", "mihomo-windows-amd64-compatible-", "mihomo-windows-amd64-")
    else:
        raise RuntimeError(f"Unsupported platform or runner architecture: {system}/{machine}")
    candidates = [
        asset
        for asset in release.get("assets", [])
        if any(str(asset.get("name", "")).startswith(pattern) for pattern in patterns)
        and str(asset.get("name", "")).endswith((".gz", ".zip", ".tar.gz"))
    ]
    if not candidates:
        raise RuntimeError("Could not find a compatible Mihomo release asset.")
    return sorted(candidates, key=lambda asset: str(asset["name"]))[-1]


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "node-subscription-builder/0.1"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def extract(asset_name: str, payload: bytes) -> bytes:
    if asset_name.endswith(".gz") and not asset_name.endswith(".tar.gz"):
        return gzip.decompress(payload)
    if asset_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            binary = [
                item
                for item in archive.namelist()
                if Path(item).name.lower().startswith("mihomo")
                and not Path(item).name.lower().endswith((".txt", ".md"))
            ]
            if not binary:
                raise RuntimeError("Mihomo executable not found in zip archive.")
            return archive.read(binary[0])
    if asset_name.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            member = next((item for item in archive.getmembers() if item.name.endswith("/mihomo") or item.name == "mihomo"), None)
            if member is None:
                raise RuntimeError("Mihomo executable not found in tar archive.")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError("Could not read Mihomo executable.")
            return extracted.read()
    raise RuntimeError(f"Unsupported asset format: {asset_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    release = fetch_json("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest")
    asset = choose_asset(release)
    payload = download(asset["browser_download_url"])
    expected = str(asset.get("digest", ""))
    if expected.startswith("sha256:"):
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected.removeprefix("sha256:"):
            raise RuntimeError("Mihomo release checksum mismatch.")
    binary = extract(str(asset["name"]), payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(binary)
    args.output.chmod(args.output.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed {release.get('tag_name', 'unknown')} from {asset['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
