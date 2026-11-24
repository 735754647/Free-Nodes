from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests


DEFAULT_RESULTS_URL = "https://results-receiver.actions.githubusercontent.com/"
ARTIFACT_PATH = "twirp/github.actions.results.api.v1.ArtifactService/CreateArtifact"


def check_route(session: requests.Session, endpoint: str, proxy: str) -> bool:
    route = "Proxy" if proxy else "Direct"
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    try:
        # A credential-free POST checks the actual endpoint without creating an artifact.
        with session.post(
            endpoint,
            json={},
            proxies=proxies,
            timeout=(5, 10),
            allow_redirects=False,
        ) as response:
            status = response.status_code
    except requests.RequestException as exc:
        print(f"{route} artifact endpoint check failed: {type(exc).__name__}: {exc}", flush=True)
        return False
    print(f"{route} artifact endpoint check: HTTP {status}", flush=True)
    # The service requires a runtime token. 401 confirms an HTTP response, not an upload.
    return status == 401


def select_proxy(results_url: str, proxy: str) -> str:
    endpoint = f"{results_url.rstrip('/')}/{ARTIFACT_PATH}"
    with requests.Session() as session:
        # Ignore inherited proxy variables, Windows proxy settings, and netrc credentials.
        session.trust_env = False
        if check_route(session, endpoint, ""):
            print("Using direct upload: the artifact endpoint is reachable.", flush=True)
            return ""
        if check_route(session, endpoint, proxy):
            print("Using proxy upload: direct check failed and proxy check passed.", flush=True)
            return proxy
    print("Neither check passed; retrying direct upload without forcing an unavailable proxy.", flush=True)
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default="http://127.0.0.1:10808")
    parser.add_argument(
        "--results-url", default=os.environ.get("ACTIONS_RESULTS_URL") or DEFAULT_RESULTS_URL
    )
    args = parser.parse_args(argv)
    proxy = select_proxy(args.results_url, args.proxy)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"proxy={proxy}\n")
            handle.write(f"no_proxy={'127.0.0.1,localhost' if proxy else '*'}\n")
            handle.write(f"route={'proxy' if proxy else 'direct'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
