param(
    [Parameter(Mandatory = $true)][ValidateSet("Console", "Agent")][string]$Mode,
    [string]$ServiceId,
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [Parameter(Mandatory = $true)][string]$LogDir
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:OPC_ENV_FILE = $EnvFile
$env:OPC_SERVICE_RUNTIME_ROOT = $RuntimeRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"
$assemblyRuntime = Join-Path $RuntimeRoot "Video-Assembly-hd\runtime"
$assemblyBin = Join-Path $assemblyRuntime "bin"
$nodeRoot = Join-Path $assemblyRuntime "node"
$env:Path = "$assemblyBin;$nodeRoot;$env:Path"
$env:FFMPEG_BIN = Join-Path $assemblyBin "ffmpeg.exe"
$env:FFPROBE_BIN = Join-Path $assemblyBin "ffprobe.exe"
$env:HYPERFRAMES_FFMPEG_PATH = $env:FFMPEG_BIN
$env:HYPERFRAMES_FFPROBE_PATH = $env:FFPROBE_BIN
$env:HYPERFRAMES_NODE_BIN = Join-Path $nodeRoot "node.exe"
$env:HYPERFRAMES_CLI_PATH = Join-Path $assemblyRuntime "hyperframes\node_modules\hyperframes\dist\cli.js"

if ($Mode -eq "Console") {
    $python = Get-OpcVenvPython $RuntimeRoot "OPC-Console"
    $launcher = Join-Path $RuntimeRoot "scripts\run_console_foreground.py"
    $arguments = @($launcher)
    $name = "console"
} else {
    if (-not $script:OpcServices.Contains($ServiceId)) {
        throw "Unknown Agent service: $ServiceId"
    }
    $python = Get-OpcVenvPython $RuntimeRoot $script:OpcServices[$ServiceId]
    $launcher = Join-Path $RuntimeRoot "scripts\run_agent_foreground.py"
    $arguments = @($launcher, $ServiceId)
    $name = $ServiceId
}

if (-not (Test-Path $python -PathType Leaf)) {
    throw "Python runtime is missing: $python"
}
if (-not (Test-Path $launcher -PathType Leaf)) {
    throw "Launcher is missing: $launcher"
}

$outLog = Join-Path $LogDir "$name.log"
$errLog = Join-Path $LogDir "$name.err.log"
& $python @arguments 1>> $outLog 2>> $errLog
exit $LASTEXITCODE
