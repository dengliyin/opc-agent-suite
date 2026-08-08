param(
    [string]$RuntimeRoot,
    [string]$EnvFile,
    [string]$LogDir
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "install_windows_tasks.ps1 can only run on Windows."
}

$RuntimeRoot = Get-OpcRuntimeRoot $RuntimeRoot
$configRoot = Get-OpcConfigRoot
if (-not $EnvFile) { $EnvFile = Join-Path $configRoot ".env" }
if (-not $LogDir) { $LogDir = Join-Path $configRoot "Logs" }
$taskRunner = Join-Path $RuntimeRoot "scripts\run_windows_task.ps1"
if (-not (Test-Path $taskRunner -PathType Leaf)) {
    throw "Windows task runner is missing: $taskRunner"
}
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$scheduler = New-Object -ComObject "Schedule.Service"
$scheduler.Connect()
$taskFolderName = $script:OpcTaskPath.Trim("\")
try {
    $null = $scheduler.GetFolder($script:OpcTaskPath)
} catch {
    $null = $scheduler.GetFolder("\").CreateFolder($taskFolderName)
}

$powershell = (Get-Process -Id $PID).Path
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 100 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

function Register-OpcTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$Mode,
        [string]$ServiceId,
        $Trigger
    )
    $argumentParts = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (ConvertTo-OpcTaskArgument $taskRunner),
        "-Mode", $Mode,
        "-RuntimeRoot", (ConvertTo-OpcTaskArgument $RuntimeRoot),
        "-EnvFile", (ConvertTo-OpcTaskArgument $EnvFile),
        "-LogDir", (ConvertTo-OpcTaskArgument $LogDir)
    )
    if ($ServiceId) {
        $argumentParts += @("-ServiceId", $ServiceId)
    }
    $action = New-ScheduledTaskAction -Execute $powershell -Argument ($argumentParts -join " ") -WorkingDirectory $RuntimeRoot
    $taskArguments = @{
        TaskName = $TaskName
        TaskPath = $script:OpcTaskPath
        Action = $action
        Settings = $settings
        Principal = $principal
        Force = $true
    }
    if ($Trigger) { $taskArguments.Trigger = $Trigger }
    Register-ScheduledTask @taskArguments | Out-Null
}

$consoleTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
Register-OpcTask -TaskName $script:OpcConsoleTaskName -Mode "Console" -Trigger $consoleTrigger
foreach ($serviceId in $script:OpcServices.Keys) {
    Register-OpcTask -TaskName "agent-$serviceId" -Mode "Agent" -ServiceId $serviceId
}

Write-Host "Installed 15 OPC scheduled tasks in $($script:OpcTaskPath)."
