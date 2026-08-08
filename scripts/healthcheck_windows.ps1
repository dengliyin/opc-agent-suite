param(
    [switch]$ConsoleOnly,
    [int]$WaitSeconds = 0
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "healthcheck_windows.ps1 can only run on Windows."
}

$checks = [ordered]@{
    "8888" = "/"
}
if (-not $ConsoleOnly) {
    $checks["9991"] = "/api/state"
    $checks["9992"] = "/api/status"
    $checks["9993"] = "/api/outputs"
    $checks["9994"] = "/api/outputs?target_model=veo"
    $checks["9995"] = "/api/catalog"
    $checks["9996"] = "/api/state"
    $checks["9997"] = "/api/state"
    $checks["9998"] = "/api/state"
    $checks["9999"] = "/api/scripts?target_model=omni"
    $checks["10000"] = "/api/library"
    $checks["10001"] = "/api/state"
    $checks["10002"] = "/api/status"
    $checks["10003"] = "/api/outputs"
    $checks["10004"] = "/api/library"
}

$deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
$failures = @()
foreach ($entry in $checks.GetEnumerator()) {
    $url = "http://127.0.0.1:$($entry.Key)$($entry.Value)"
    $healthy = $false
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
            $healthy = $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
        } catch {
            $healthy = $false
        }
        if (-not $healthy -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 500
        }
    } while (-not $healthy -and [DateTime]::UtcNow -lt $deadline)

    if ($healthy) {
        Write-Host "OK   $url"
    } else {
        Write-Host "FAIL $url"
        $failures += $url
    }
}

$expectedTasks = @($script:OpcConsoleTaskName) + @($script:OpcServices.Keys | ForEach-Object { "agent-$_" })
foreach ($taskName in $expectedTasks) {
    $task = Get-ScheduledTask -TaskPath $script:OpcTaskPath -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "FAIL scheduled task $taskName"
        $failures += "task:$taskName"
    }
}

$envFile = Join-Path (Get-OpcConfigRoot) ".env"
if (-not (Test-Path $envFile -PathType Leaf)) {
    Write-Host "FAIL configuration $envFile"
    $failures += "config:$envFile"
} else {
    $vaultLine = Get-Content -Encoding UTF8 $envFile | Where-Object { $_ -match '^\s*OPC_VAULT_ROOT\s*=' } | Select-Object -First 1
    if (-not $vaultLine) {
        Write-Host "FAIL OPC_VAULT_ROOT is not configured"
        $failures += "config:OPC_VAULT_ROOT"
    } else {
        $vaultValue = ($vaultLine -split '=', 2)[1].Trim()
        if ($vaultValue.StartsWith('"') -and $vaultValue.EndsWith('"')) {
            $vaultValue = ConvertFrom-Json $vaultValue
        }
        if (Test-Path $vaultValue -PathType Container) {
            Write-Host "OK   external storage $vaultValue"
        } else {
            Write-Host "FAIL external storage $vaultValue"
            $failures += "storage:$vaultValue"
        }
    }
}

if ($failures.Count -gt 0) {
    throw "Windows health check failed: $($failures -join ', ')"
}
Write-Host "Windows health check passed."
