# Node Subscription Builder

This project fetches public proxy sources, extracts supported node links, removes duplicates, benchmarks them with Mihomo, and publishes V2Ray and Clash/Mihomo subscriptions through GitHub Pages.

Supported protocols: `VLESS`, `VMess`, `Trojan`, `Shadowsocks`, `Hysteria2`, and `TUIC`.

## Quick start

1. Create a GitHub repository and copy this directory into it.
2. Add one URL per line to `config/sources.txt`, for example:

   ```text
   provider-a | https://example.com/public-subscription
   https://example.org/nodes.txt
   ```

   The fetcher accepts plain text, Base64 subscriptions, HTML containing links, and Clash YAML. Dynamic pages that require JavaScript need a direct subscription URL or a custom extractor.
3. Commit and push to the `main` branch.
4. In repository settings, enable Pages with **GitHub Actions** as the source.
5. Run **Build subscriptions** once from the Actions tab.

After deployment, the generated files are available at:

```text
https://YOUR_USER.github.io/YOUR_REPOSITORY/v2ray.txt
https://YOUR_USER.github.io/YOUR_REPOSITORY/clash.yaml
```

`v2ray.txt` is a Base64 subscription. `clash.yaml` is a complete Clash/Mihomo configuration with an automatic latency group.

## Private sources

GitHub Pages is public. Do not put private subscription tokens in the repository or publish nodes that you are not allowed to redistribute. For private URLs, create a repository secret named `SOURCE_URLS` containing newline-separated URLs. The workflow combines that secret with `config/sources.txt`; the generated page is still public, so use a private repository and an access-controlled publisher if the output must stay private.

## Tuning

The workflow sets conservative defaults for GitHub-hosted runners. These environment variables can be changed in `.github/workflows/build.yml`:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `MAX_NODES` | `300` | Maximum nodes parsed before testing |
| `MAX_OUTPUT_NODES` | `100` | Maximum nodes published |
| `MAX_LATENCY_MS` | `5000` | Latency filter |
| `MIN_SPEED_MBPS` | `0` | Download speed filter |
| `SPEED_TEST_LIMIT` | `50` | Nodes receiving the download test |
| `SPEED_TEST_BYTES` | `1000000` | Bytes read per speed test |
| `LATENCY_TEST_URL` | Google generate_204 | Latency target |
| `SPEED_TEST_URL` | Meta rules database | Download target |

The speed test is intentionally bounded. Testing hundreds of nodes with large downloads can exhaust a GitHub Actions runner or violate a provider's acceptable-use policy.

## Local test

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
python -m subbench run --skip-benchmark
```

The last command needs at least one source URL. It writes generated files to `public/`.

## Notes

- Only use sources and nodes that you are authorized to fetch and redistribute.
- Mihomo is downloaded from its latest GitHub release and checked against the release SHA-256 digest when available.
- The workflow runs every six hours and can also be started manually.
- GitHub Actions runner IPs and geography differ from your phone or home network, so a node that passes CI is not guaranteed to work everywhere.
