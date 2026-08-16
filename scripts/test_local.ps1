param(
    [int]$MaxNodes = 0,
    [int]$MaxLatencyMs = 3000,
    [double]$MinSpeedMbps = 0.1,
    [int]$SpeedTestBytes = 1000000,
    [int]$LatencyWorkers = 8,
    [switch]$EnableSpeedTest
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Mihomo = Join-Path $ProjectRoot ".bin\mihomo.exe"
$Output = Join-Path $ProjectRoot "public-local"
$WorkDir = Join-Path $ProjectRoot ".work-local"

Push-Location $ProjectRoot
try {
    python -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the Python project."
    }

    if (-not (Test-Path $Mihomo)) {
        python scripts/install_mihomo.py --output $Mihomo
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install Mihomo."
        }
    }

    $env:MAX_NODES = "$MaxNodes"
    $env:MAX_OUTPUT_NODES = "$MaxNodes"
    $env:TCP_PREFILTER_ENABLED = "1"
    $env:TCP_CONNECT_TIMEOUT_SECONDS = "3"
    $env:TCP_PREFILTER_WORKERS = "64"
    $env:MAX_LATENCY_MS = "$MaxLatencyMs"
    $env:MIN_SPEED_MBPS = "$MinSpeedMbps"
    $env:GEOIP_WORKERS = "$LatencyWorkers"
    $env:SPEED_TEST_ENABLED = if ($EnableSpeedTest) { "1" } else { "0" }
    $env:SPEED_TEST_LIMIT = "0"
    $env:SPEED_TEST_BYTES = "$SpeedTestBytes"
    $env:SPEED_TIMEOUT_SECONDS = "8"
    $env:BENCHMARK_WORKERS = "$LatencyWorkers"
    $env:LATENCY_TEST_URL = "https://www.google.com/generate_204"
    $env:GEOIP_TEST_URLS = "https://www.cloudflare.com/cdn-cgi/trace,https://api.country.is/"

    python -m subbench run --mihomo $Mihomo --output $Output --workdir $WorkDir
    if ($LASTEXITCODE -ne 0) {
        throw "Local benchmark failed."
    }

    Write-Host "Local benchmark complete."
    Write-Host "V2Ray: $Output\v2ray.txt"
    Write-Host "Clash: $Output\clash.yaml"
    Write-Host "Report: $Output\report.json"
}
finally {
    Pop-Location
}
