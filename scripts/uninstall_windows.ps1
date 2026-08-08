param(
    [string]$RuntimeRoot,
    [switch]$RemoveRuntime,
    [switch]$RemoveConfiguration
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "uninstall_windows.ps1 can only run on Windows."
}

$taskNames = @($script:OpcConsoleTaskName) + @($script:OpcServices.Keys | ForEach-Object { "agent-$_" })
foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $taskName -Confirm:$false
    }
}

try {
    $scheduler = New-Object -ComObject "Schedule.Service"
    $scheduler.Connect()
    $scheduler.GetFolder("\").DeleteFolder($script:OpcTaskPath.Trim("\"), 0)
} catch {
    Write-Verbose "Scheduled task folder was already absent or could not be removed: $_"
}

$configRoot = Get-OpcConfigRoot
if ($RemoveRuntime) {
    Remove-Item -Recurse -Force (Get-OpcRuntimeRoot $RuntimeRoot) -ErrorAction SilentlyContinue
}
if ($RemoveConfiguration) {
    Remove-Item -Recurse -Force $configRoot -ErrorAction SilentlyContinue
}

Write-Host "Removed the 15 OPC Windows scheduled tasks."
if (-not $RemoveRuntime) { Write-Host "Runtime preserved at $(Join-Path $configRoot 'Service-Runtime')" }
if (-not $RemoveConfiguration) { Write-Host "Configuration and logs preserved at $configRoot" }
