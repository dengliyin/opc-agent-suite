param(
    [string]$VaultRoot
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$EnvFile = if ($env:OPC_ENV_FILE) { $env:OPC_ENV_FILE } else { Join-Path $RootDir ".env" }
$TemplateRoot = Join-Path $RootDir "storage-template"

if (-not $VaultRoot -and (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    foreach ($Line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        if ($Line -match '^\s*OPC_VAULT_ROOT\s*=\s*["'']?(.*?)["'']?\s*$') {
            $VaultRoot = $Matches[1]
            break
        }
    }
}

if (-not $VaultRoot) {
    throw "OPC_VAULT_ROOT 未配置。"
}
if (-not (Test-Path -LiteralPath $TemplateRoot -PathType Container)) {
    throw "资料库目录模板不存在：$TemplateRoot"
}
if (Test-Path -LiteralPath $VaultRoot -PathType Leaf) {
    throw "资料库根路径不是目录：$VaultRoot"
}
if (-not (Test-Path -LiteralPath $VaultRoot -PathType Container)) {
    $Parent = Split-Path -Parent $VaultRoot
    if (-not $Parent -or -not (Test-Path -LiteralPath $Parent -PathType Container)) {
        throw "资料库上一级目录或外置盘必须已经存在：$Parent"
    }
    New-Item -ItemType Directory -Path $VaultRoot | Out-Null
}

$Probe = Join-Path $VaultRoot ".opc-write-test-$PID"
try { [System.IO.File]::WriteAllText($Probe, "ok") } finally { Remove-Item -LiteralPath $Probe -Force -ErrorAction SilentlyContinue }

$TemplatePrefix = $TemplateRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
foreach ($TemplateDirectory in Get-ChildItem -LiteralPath $TemplateRoot -Directory -Recurse) {
    $RelativePath = $TemplateDirectory.FullName.Substring($TemplatePrefix.Length)
    New-Item -ItemType Directory -Force -Path (Join-Path $VaultRoot $RelativePath) | Out-Null
}

Write-Host "资料库空目录结构已就绪：$VaultRoot"
