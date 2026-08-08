param(
    [string]$SourceRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$RuntimeRoot
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "stage_service_runtime_windows.ps1 can only run on Windows."
}

$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$RuntimeRoot = Get-OpcRuntimeRoot $RuntimeRoot
$components = @("OPC-Console") + @($script:OpcServices.Values)
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

foreach ($component in $components) {
    $source = Join-Path $SourceRoot $component
    $destination = Join-Path $RuntimeRoot $component
    if (-not (Test-Path $source -PathType Container)) {
        throw "Missing component: $source"
    }
    $destinationExisted = Test-Path $destination -PathType Container
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    $excludedDirectories = @(".git", ".venv", ".pytest_cache", "__pycache__", "runtime", "runs")
    if ($destinationExisted) {
        $excludedDirectories += @("agent_config", "browser-profile", "config", "data", "projects", "run_logs")
    }
    $arguments = @(
        $source,
        $destination,
        "/MIR", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
        "/XD"
    ) + $excludedDirectories
    & robocopy.exe @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Failed to stage $component (robocopy exit code $LASTEXITCODE)."
    }
}

$runtimeScripts = Join-Path $RuntimeRoot "scripts"
New-Item -ItemType Directory -Force -Path $runtimeScripts | Out-Null
& robocopy.exe (Join-Path $SourceRoot "scripts") $runtimeScripts /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Failed to stage scripts (robocopy exit code $LASTEXITCODE)."
}

$storageTemplate = Join-Path $RuntimeRoot "storage-template"
New-Item -ItemType Directory -Force -Path $storageTemplate | Out-Null
& robocopy.exe (Join-Path $SourceRoot "storage-template") $storageTemplate /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Failed to stage storage-template (robocopy exit code $LASTEXITCODE)."
}

Write-Output $RuntimeRoot
