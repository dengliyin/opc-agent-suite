$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RootDir ".env"

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "缺少 $EnvFile，请复制 .env.docker.example 并填写真实路径。"
}

$Settings = @{}
foreach ($Line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*["'']?(.*?)["'']?\s*$') {
        $Settings[$Matches[1]] = $Matches[2]
    }
}

foreach ($Name in @("OPC_VAULT_ROOT", "OPC_DOCKER_DATA_ROOT", "VIDEO_ASSEMBLY_WORK_ROOT")) {
    $Value = $Settings[$Name]
    if (-not $Value -or -not (Test-Path -LiteralPath $Value -PathType Container)) {
        throw "$Name 必须指向已挂载的目录：$Value"
    }
    $Probe = Join-Path $Value ".opc-write-test-$PID"
    try { [System.IO.File]::WriteAllText($Probe, "ok") } finally { Remove-Item -LiteralPath $Probe -Force -ErrorAction SilentlyContinue }
}

foreach ($Name in @("config", "finished-video-data", "video-assembly-data", "auto-publish-data")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Settings["OPC_DOCKER_DATA_ROOT"] $Name) | Out-Null
}

docker compose --project-directory $RootDir config --quiet
if ($LASTEXITCODE -ne 0) { throw "Docker Compose 配置校验失败。" }
docker compose --project-directory $RootDir up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { throw "Docker Compose 启动失败。" }
& (Join-Path $PSScriptRoot "docker_health.ps1")
