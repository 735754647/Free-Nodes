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
$RuntimeDir = Join-Path $ProjectRoot ".runtime\python"
$Output = Join-Path $ProjectRoot "public-local"
$WorkDir = Join-Path $ProjectRoot ".work-local"

Push-Location $ProjectRoot
try {
    $PythonExe = $null
    $RuntimeArchive = Get-ChildItem -Path $ProjectRoot -Filter "python-*-runtime.zip" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($RuntimeArchive) {
        if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir "python.exe"))) {
            New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::ExtractToDirectory($RuntimeArchive.FullName, $RuntimeDir)
        }
        $PythonExe = Get-ChildItem -LiteralPath $RuntimeDir -Filter "python.exe" -File -Recurse |
            Select-Object -ExpandProperty FullName -First 1
    }
    if (-not $PythonExe) {
        $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($Launcher) {
            $LauncherOutput = & $Launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $LauncherOutput) {
                $PythonExe = ($LauncherOutput | Select-Object -Last 1).Trim()
            }
        }
    }
    if (-not $PythonExe) {
        $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($PythonCommand) { $PythonExe = $PythonCommand.Source }
    }
    if (-not $PythonExe) {
        throw "No bundled or system Python 3 installation was found."
    }

    $PythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ([version]$PythonVersion -lt [version]"3.11") {
        throw "Python $PythonVersion is too old; Python 3.11 or newer is required."
    }

    if ($RuntimeArchive -and $PythonExe.StartsWith($RuntimeDir, [StringComparison]::OrdinalIgnoreCase)) {
        & $PythonExe -c "import yaml, requests, subbench; print('Using bundled offline Python dependencies')"
    } else {
        & $PythonExe -m pip install -e .
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare the Python project."
    }

    if (-not (Test-Path $Mihomo)) {
        $BundledMihomo = Get-ChildItem -Path $ProjectRoot -Filter "mihomo.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -ne $Mihomo } |
            Select-Object -ExpandProperty FullName -First 1
        New-Item -ItemType Directory -Path (Split-Path -Parent $Mihomo) -Force | Out-Null
        if ($BundledMihomo) {
            Copy-Item -LiteralPath $BundledMihomo -Destination $Mihomo -Force
        } else {
            & $PythonExe scripts/install_mihomo.py --output $Mihomo
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to install Mihomo."
            }
        }
    }

    $env:MAX_NODES = "$MaxNodes"
    $env:MAX_OUTPUT_NODES = "$MaxNodes"
    $env:TCP_PREFILTER_ENABLED = "1"
    $env:TCP_CONNECT_TIMEOUT_SECONDS = "3"
    $env:TCP_CONNECT_ATTEMPTS = "2"
    $env:TCP_PREFILTER_WORKERS = "64"
    $env:MAX_LATENCY_MS = "$MaxLatencyMs"
    $env:LATENCY_TEST_ATTEMPTS = "2"
    $env:MIN_SPEED_MBPS = "$MinSpeedMbps"
    $env:GEOIP_WORKERS = "$LatencyWorkers"
    $env:SPEED_TEST_ENABLED = if ($EnableSpeedTest) { "1" } else { "0" }
    $env:SPEED_TEST_LIMIT = "0"
    $env:SPEED_TEST_BYTES = "$SpeedTestBytes"
    $env:SPEED_TIMEOUT_SECONDS = "8"
    $env:BENCHMARK_WORKERS = "$LatencyWorkers"
    $env:LATENCY_TEST_URL = "https://www.google.com/generate_204"
    $env:GEOIP_TEST_URLS = "https://www.cloudflare.com/cdn-cgi/trace,https://api.country.is/"

    & $PythonExe -m subbench run --mihomo $Mihomo --output $Output --workdir $WorkDir
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
