param(
    [switch]$NoOpen,
    [int]$WaitSeconds = 30
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "start_console_windows.ps1 can only run on Windows."
}
$task = Get-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $script:OpcConsoleTaskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "The OPC console task is not installed. Run scripts\bootstrap_windows.ps1 first."
}
Start-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $script:OpcConsoleTaskName
& (Join-Path $PSScriptRoot "healthcheck_windows.ps1") -ConsoleOnly -WaitSeconds $WaitSeconds
if (-not $NoOpen) {
    Start-Process "http://127.0.0.1:8888/"
}
