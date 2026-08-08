param(
    [string]$VaultRoot,
    [string]$RuntimeRoot,
    [switch]$SkipPlaywrightBrowserInstall,
    [switch]$SkipHyperFramesBrowserInstall,
    [switch]$SkipWhisperModelDownload,
    [switch]$NoStart
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "bootstrap_windows.ps1 can only run on Windows."
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$sourceRoot = Split-Path $PSScriptRoot -Parent
$configRoot = Get-OpcConfigRoot
$RuntimeRoot = Get-OpcRuntimeRoot $RuntimeRoot
$envFile = Join-Path $configRoot ".env"
$logDir = Join-Path $configRoot "Logs"
New-Item -ItemType Directory -Force -Path $configRoot, $logDir | Out-Null

try {
    $python = Find-OpcPython312
} catch {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.12 is required and winget is unavailable. Install Python 3.12, then rerun this script."
    }
    Write-Host "Installing Python 3.12 for the current user..."
    & $winget.Source install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 installation failed." }
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $python = Find-OpcPython312
}

if (-not (Test-Path $envFile -PathType Leaf)) {
    if (-not $VaultRoot) {
        throw "First installation requires -VaultRoot, for example: -VaultRoot 'D:\Obsidian Vault'"
    }
    if (-not (Test-Path $VaultRoot -PathType Container)) {
        throw "Vault path does not exist: $VaultRoot"
    }
    $resolvedVault = (Resolve-Path $VaultRoot).Path.Replace("\", "/")
    $resolvedRuntime = $RuntimeRoot.Replace("\", "/")
    $template = Get-Content -Raw -Encoding UTF8 (Join-Path $sourceRoot ".env.windows.example")
    $template = $template -replace '(?m)^OPC_VAULT_ROOT=.*$', "OPC_VAULT_ROOT=`"$resolvedVault`""
    $template = $template -replace '(?m)^OPC_SERVICE_RUNTIME_ROOT=.*$', "OPC_SERVICE_RUNTIME_ROOT=`"$resolvedRuntime`""
    [IO.File]::WriteAllText($envFile, $template, [Text.UTF8Encoding]::new($false))
    Write-Host "Created Windows configuration: $envFile"
}

Write-Host "Staging the Windows service runtime..."
& (Join-Path $PSScriptRoot "stage_service_runtime_windows.ps1") -SourceRoot $sourceRoot -RuntimeRoot $RuntimeRoot | Out-Null

$components = @("OPC-Console") + @($script:OpcServices.Values)
foreach ($component in $components) {
    $componentRoot = Join-Path $RuntimeRoot $component
    $venvPython = Get-OpcVenvPython $RuntimeRoot $component
    if (-not (Test-Path $venvPython -PathType Leaf)) {
        Write-Host "Creating $component Windows Python environment..."
        Invoke-OpcPython -Python $python -Arguments @("-m", "venv", (Join-Path $componentRoot ".venv"))
    }
    Write-Host "Installing $component dependencies..."
    & $venvPython -m pip install --disable-pip-version-check --requirement (Join-Path $componentRoot "requirements.lock.txt")
    if ($LASTEXITCODE -ne 0) { throw "$component dependency installation failed." }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "$component dependency check failed." }
}

if (-not $SkipPlaywrightBrowserInstall) {
    $collectorPython = Get-OpcVenvPython $RuntimeRoot "Video-Collection"
    & $collectorPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium installation failed." }
}

& (Join-Path $PSScriptRoot "install_video_assembly_runtime_windows.ps1") `
    -RuntimeRoot $RuntimeRoot `
    -SkipBrowserInstall:$SkipHyperFramesBrowserInstall `
    -SkipWhisperModelDownload:$SkipWhisperModelDownload

& (Join-Path $PSScriptRoot "install_windows_tasks.ps1") `
    -RuntimeRoot $RuntimeRoot `
    -EnvFile $envFile `
    -LogDir $logDir

if (-not $NoStart) {
    Start-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $script:OpcConsoleTaskName
    & (Join-Path $PSScriptRoot "healthcheck_windows.ps1") -ConsoleOnly -WaitSeconds 30
}

Write-Host "Windows installation completed. Console: http://127.0.0.1:8888/"
