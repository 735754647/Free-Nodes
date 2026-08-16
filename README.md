# Free Nodes

[![Build subscriptions](https://github.com/735754647/Free-Nodes/actions/workflows/build.yml/badge.svg)](https://github.com/735754647/Free-Nodes/actions/workflows/build.yml)

[简体中文](#简体中文) | [English](#english)

## 简体中文

一个自动收集、解析、去重和测速公开代理节点的 GitHub Actions 项目。项目使用 Mihomo 对候选节点进行实际连通性与下载速度测试，并通过 GitHub Pages 生成 V2Ray 和 Clash/Mihomo 订阅。

> 免费节点来自公开网络，可能随时失效、限速或被修改。请勿用于传输敏感信息，也不要将测速结果视为长期可用保证。

### 订阅地址

| 类型 | 订阅链接 | 说明 |
| --- | --- | --- |
| V2Ray | `https://735754647.github.io/Free-Nodes/v2ray.txt` | Base64 编码订阅，适用于 v2rayN、v2rayNG 等客户端 |
| Clash / Mihomo | `https://735754647.github.io/Free-Nodes/clash.yaml` | 完整 Clash/Mihomo 配置，包含自动延迟选择组 |
| 原始节点 | `https://735754647.github.io/Free-Nodes/v2ray-raw.txt` | 未进行 Base64 编码的节点链接 |
| 测速报告 | `https://735754647.github.io/Free-Nodes/report.json` | 节点来源、延迟、速度和错误信息 |
| 状态页面 | `https://735754647.github.io/Free-Nodes/` | 最近一次生成结果和节点列表 |

首次使用前，需要在仓库 `Settings → Pages` 中将发布来源设置为 **GitHub Actions**。Pages 尚未启用时，上述链接会返回 404。

### 主要功能

- 从多个公开订阅、文本文件或网页抓取节点
- 支持普通文本、Base64 订阅、HTML 中的节点链接和 Clash YAML
- 支持 `VLESS`、`VMess`、`Trojan`、`Shadowsocks`、`Hysteria2` 和 `TUIC`
- 根据协议参数进行规范化去重，而不是只比较节点名称
- 在加载代理内核前并发检测去重后的入口 IP/域名与端口，快速剔除本地 TCP 不可达节点
- 使用 Mihomo 测试代理连通性、延迟和限定大小的下载速度
- 自动过滤不可用节点，并按速度和延迟排序
- 通过代理出口 IP 识别国家，并将节点重命名为 `🇺🇸 美国 | VLESS | 001` 格式
- 每天北京时间 08:00 和 20:00 自动更新，也支持在 Actions 页面手动运行
- 生成 V2Ray、Clash/Mihomo、原始链接和 JSON 报告

### 客户端使用

V2Ray 客户端导入：

```text
https://735754647.github.io/Free-Nodes/v2ray.txt
```

Clash/Mihomo 客户端导入：

```text
https://735754647.github.io/Free-Nodes/clash.yaml
```

不同客户端对协议和传输方式的支持程度不同。如果某个节点在报告中可用，但客户端无法连接，请检查客户端内核版本以及对应协议支持情况。

### 添加节点来源

公开来源写入 [`config/sources.txt`](config/sources.txt)，每行一个地址：

```text
provider-name | https://example.com/public-subscription
https://example.org/nodes.txt
```

带有订阅密钥或访问令牌的地址不要提交到公开仓库。请在仓库中创建 Actions Secret：

```text
Settings → Secrets and variables → Actions → New repository secret
Name: SOURCE_URLS
Value: 每行一个订阅地址
```

`SOURCE_URLS` 会和 `config/sources.txt` 中的公开来源一起处理。请注意：即使来源保存在 Secret 中，GitHub Pages 生成的节点订阅仍然是公开的。

### 测速设置

可在 [`.github/workflows/build.yml`](.github/workflows/build.yml) 中调整：

| 环境变量 | 默认值 | 用途 |
| --- | ---: | --- |
| `MAX_NODES` | `0` | `0` 表示对全部去重后的候选节点进行测速 |
| `MAX_OUTPUT_NODES` | `0` | `0` 表示发布全部通过延迟和下载测速的可用节点 |
| `TCP_PREFILTER_ENABLED` | `1` | 在 Mihomo 测试前启用入口 TCP 端口预筛 |
| `TCP_CONNECT_TIMEOUT_SECONDS` | `3` | 单个入口端口连接超时 |
| `TCP_CONNECT_ATTEMPTS` | `2` | TCP 首次失败时再尝试一次；首次成功不会重复连接 |
| `TCP_PREFILTER_WORKERS` | `64` | 并发入口端口检测数量 |
| `ALIYUN_FC_URL` | Secret，可选 | 使用阿里云函数从杭州逐个复核入口端口；未配置时自动跳过 |
| `ALIYUN_FC_TIMEOUT_SECONDS` | `10` | 单次阿里云函数请求超时 |
| `ALIYUN_FC_INTERVAL_SECONDS` | `1.5` | 每次阿里云检测后的强制等待时间 |
| `ALIYUN_FC_MAX_CONSECUTIVE_ERRORS` | `3` | 连续请求异常后停止远程检测并保留未检测节点 |
| `MAX_LATENCY_MS` | `3000` | 最大允许延迟 |
| `LATENCY_TEST_ATTEMPTS` | `2` | Google 204 首次失败时重试一次，降低瞬时网络抖动导致的误删 |
| `MIN_SPEED_MBPS` | `0.1` | 最低下载速度；低于 `0.1 Mbps` 或未完成下载测速的节点不会发布 |
| `GEOIP_TEST_URLS` | Cloudflare trace + country.is | 依次通过节点查询实际出口 IP 和国家代码 |
| `GEOIP_WORKERS` | `24` | 并发查询真实出口国家数量；每个节点使用独立本地 Mihomo 入口 |
| `SPEED_TEST_ENABLED` | `0` | `0` 关闭下载测速；改成 `1` 可恢复测速和最低速度过滤 |
| `SPEED_TEST_LIMIT` | `0` | `0` 表示对全部延迟测试通过的节点执行下载测速 |
| `SPEED_TEST_BYTES` | `1000000` | 启用测速后每个节点下载约 1 MB，用于筛选而非精确带宽评测 |
| `SPEED_TIMEOUT_SECONDS` | `8` | 单个节点下载测速读取超时 |
| `BENCHMARK_WORKERS` | `24` | 并发延迟测试数量 |

测速运行在 GitHub 托管的服务器上，结果反映的是 GitHub Runner 所在网络到节点的质量，并不等于你本地网络的实际体验。

### 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/install_mihomo.py --output .bin/mihomo.exe
python -m subbench run --mihomo .bin/mihomo.exe
```

Windows 用户也可以直接运行本地线路测速脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1
```

下载速度测试默认关闭。需要临时开启时运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1 -EnableSpeedTest
```

本地结果写入 `public-local/`，其延迟和速度更接近当前电脑运行 v2rayN 时的实际线路。GitHub Pages 上的订阅仍由 GitHub 托管服务器测速。

生成文件位于 `public/`。只想检查解析和订阅生成时，可以使用：

```powershell
python -m subbench run --skip-benchmark
```

### 项目说明

- 本项目不提供、出售或运营任何代理服务器
- 节点内容由上游公开来源提供，本项目只进行自动整理和测试
- 测速会产生真实代理流量，因此限制了并发量和下载大小
- 公开节点可能存在隐私、安全和可用性风险
- 请遵守所在地区法律、GitHub 服务条款以及节点提供方的使用规则

### 免责声明

本项目仅用于技术研究、网络测试和自动化学习。维护者不保证节点的真实性、安全性、速度或持续可用性，也不对使用这些节点造成的账号、数据、隐私、网络或法律风险承担责任。请只收集和发布你有权使用及再分发的来源。

---

## English

Free Nodes is a GitHub Actions project that collects public proxy links, parses and deduplicates them, benchmarks connectivity and download speed with Mihomo, and publishes V2Ray and Clash/Mihomo subscriptions through GitHub Pages.

> Public free nodes can disappear, slow down, or change without notice. Do not use them for sensitive traffic, and do not treat a successful CI test as a long-term availability guarantee.

### Subscription URLs

| Format | URL | Description |
| --- | --- | --- |
| V2Ray | `https://735754647.github.io/Free-Nodes/v2ray.txt` | Base64 subscription for clients such as v2rayN and v2rayNG |
| Clash / Mihomo | `https://735754647.github.io/Free-Nodes/clash.yaml` | Complete configuration with an automatic latency group |
| Raw links | `https://735754647.github.io/Free-Nodes/v2ray-raw.txt` | Extracted node links without Base64 encoding |
| Benchmark report | `https://735754647.github.io/Free-Nodes/report.json` | Source, latency, speed, and error details |
| Status page | `https://735754647.github.io/Free-Nodes/` | Latest generated results and node table |

Before the first deployment, open `Settings → Pages` and select **GitHub Actions** as the publishing source. The URLs return 404 until Pages is enabled.

### Features

- Fetches multiple public subscriptions, text files, and webpages
- Accepts plain URI lists, Base64 subscriptions, HTML links, and Clash YAML
- Supports `VLESS`, `VMess`, `Trojan`, `Shadowsocks`, `Hysteria2`, and `TUIC`
- Deduplicates nodes by normalized connection parameters
- Concurrently checks unique entry hosts and ports before loading Mihomo
- Uses Mihomo for real proxy connectivity, latency, and bounded download tests
- Filters failed nodes and sorts successful results by speed and latency
- Detects the proxy exit country and renames nodes like `🇺🇸 美国 | VLESS | 001`
- Runs daily at 08:00 and 20:00 Asia/Shanghai and supports manual workflow dispatch
- Publishes V2Ray, Clash/Mihomo, raw-link, and JSON report outputs

### Usage

Import one of these URLs into a compatible client:

```text
V2Ray: https://735754647.github.io/Free-Nodes/v2ray.txt
Clash: https://735754647.github.io/Free-Nodes/clash.yaml
```

Protocol and transport support varies between clients. A node that passes the CI benchmark can still fail on an older or incompatible client core.

### Adding Sources

Add public URLs to [`config/sources.txt`](config/sources.txt), one per line:

```text
provider-name | https://example.com/public-subscription
https://example.org/nodes.txt
```

Store tokenized or private source URLs in the `SOURCE_URLS` GitHub Actions secret as newline-separated values. Do not commit subscription tokens to a public repository. Remember that the generated GitHub Pages subscriptions remain public even when the input URL is stored as a secret.

### Benchmark Configuration

The main limits are configured in [`.github/workflows/build.yml`](.github/workflows/build.yml):

| Variable | Default | Purpose |
| --- | ---: | --- |
| `MAX_NODES` | `0` | `0` benchmarks every deduplicated candidate |
| `MAX_OUTPUT_NODES` | `0` | `0` publishes every node that passes latency and download testing |
| `TCP_PREFILTER_ENABLED` | `1` | Enables entry TCP port prefiltering before Mihomo tests |
| `TCP_CONNECT_TIMEOUT_SECONDS` | `3` | Per-entry TCP connection timeout |
| `TCP_CONNECT_ATTEMPTS` | `2` | Retries TCP once after an initial failure; successful connections are not repeated |
| `TCP_PREFILTER_WORKERS` | `64` | Concurrent entry-port checks |
| `ALIYUN_FC_URL` | Optional secret | Rechecks entry ports sequentially from Alibaba Cloud Hangzhou; skipped when unset |
| `ALIYUN_FC_TIMEOUT_SECONDS` | `10` | Timeout for each Alibaba Cloud function request |
| `ALIYUN_FC_INTERVAL_SECONDS` | `1.5` | Mandatory delay after each Alibaba Cloud check |
| `ALIYUN_FC_MAX_CONSECUTIVE_ERRORS` | `3` | Stops remote checks after consecutive request errors and preserves untested nodes |
| `MAX_LATENCY_MS` | `3000` | Maximum accepted latency |
| `LATENCY_TEST_ATTEMPTS` | `2` | Retries the Google 204 check once after an initial failure to reduce transient false negatives |
| `MIN_SPEED_MBPS` | `0.1` | Minimum download speed; nodes below `0.1 Mbps` or without a completed speed test are rejected |
| `GEOIP_TEST_URLS` | Cloudflare trace + country.is | Looks up the actual exit IP and country code with fallback |
| `GEOIP_WORKERS` | `24` | Concurrent exit-country lookups; each node uses a dedicated local Mihomo listener |
| `SPEED_TEST_ENABLED` | `0` | `0` disables download tests; set to `1` to restore speed filtering |
| `SPEED_TEST_LIMIT` | `0` | `0` tests every node that passes the latency check |
| `SPEED_TEST_BYTES` | `1000000` | Downloads about 1 MB per node when enabled, for screening rather than precise bandwidth benchmarking |
| `SPEED_TIMEOUT_SECONDS` | `8` | Per-node download read timeout |
| `BENCHMARK_WORKERS` | `24` | Concurrent latency checks |

GitHub-hosted runners have different routes and locations from your local network, so benchmark results are useful for filtering but cannot predict every user's connection quality.

### Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/install_mihomo.py --output .bin/mihomo.exe
python -m subbench run --mihomo .bin/mihomo.exe
```

Windows users can benchmark from their current local network with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1
```

Local results are written to `public-local/`. They better represent the route used by v2rayN on that computer, while the GitHub Pages subscriptions are still benchmarked from a GitHub-hosted runner.

Generated subscriptions are written to `public/`. Use `python -m subbench run --skip-benchmark` when you only need to verify parsing and output generation.

### Disclaimer

This repository is intended for technical research, network testing, and automation learning. It does not operate or sell proxy servers. No guarantee is made regarding node ownership, safety, privacy, speed, legality, or availability. Only fetch and redistribute sources you are authorized to use, and comply with local laws, GitHub's terms, and upstream providers' policies.

### References

- [Mihomo](https://github.com/MetaCubeX/mihomo)
- [free18/v2ray](https://github.com/free18/v2ray)
- [AutoMergePublicNodes](https://github.com/chengaopan/AutoMergePublicNodes)
- [NoMoreWalls](https://github.com/peasoft/NoMoreWalls)
- [ConfigForge-V2Ray](https://github.com/ShatakVPN/ConfigForge-V2Ray)
