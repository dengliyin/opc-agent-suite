$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
docker compose --project-directory $RootDir stop
if ($LASTEXITCODE -ne 0) { throw "Docker Compose 停止失败。" }
