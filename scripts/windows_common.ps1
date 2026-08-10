Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:OpcTaskPath = "\OPC-Agent-Suite\"
$script:OpcConsoleTaskName = "console-8888"
$script:OpcServices = [ordered]@{
    collect = "Video-Collection"
    analyze = "Script-Analysis"
    script = "Script-Generation"
    adapt = "Script-Adaptation"
    assemble = "Video-Generation"
    finished = "Finished-Video-Manager"
    rewrite = "Product-Script-Rewrite"
    compose = "Video-Assembly-hd"
    hybrid_adapt = "Hybrid-Script-Adaptation"
    hybrid_mix = "Hybrid-Video-Mixer"
    hybrid_collect = "Hybrid-Video-Collection"
    hybrid_analyze = "Hybrid-Script-Analysis"
    hybrid_script = "Hybrid-Script-Generation"
    hybrid_voice = "Hybrid-Audio-Generation"
    auto_publish = "Auto-Publish-Pipeline"
}

function Get-OpcConfigRoot {
    if (-not $env:LOCALAPPDATA) {
        throw "LOCALAPPDATA is not available. Run this installer as a normal Windows user."
    }
    return Join-Path $env:LOCALAPPDATA "OPC-Agent-Suite"
}

function Get-OpcRuntimeRoot {
    param([string]$RuntimeRoot)
    if ($RuntimeRoot) {
        return [IO.Path]::GetFullPath($RuntimeRoot)
    }
    return Join-Path (Get-OpcConfigRoot) "Service-Runtime"
}

function Get-OpcVenvPython {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$Component
    )
    return Join-Path $RuntimeRoot "$Component\.venv\Scripts\python.exe"
}

function Find-OpcPython312 {
    $candidates = @()
    if ($env:OPC_PYTHON_BIN) {
        $candidates += [pscustomobject]@{ Executable = $env:OPC_PYTHON_BIN; Prefix = @() }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += [pscustomobject]@{ Executable = $py.Source; Prefix = @("-3.12") }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += [pscustomobject]@{ Executable = $python.Source; Prefix = @() }
    }

    foreach ($candidate in $candidates) {
        $versionArguments = @($candidate.Prefix) + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        $version = & $candidate.Executable @versionArguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $version.Trim() -eq "3.12") {
            return $candidate
        }
    }
    throw "Python 3.12 was not found."
}

function Invoke-OpcPython {
    param(
        [Parameter(Mandatory = $true)]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $allArguments = @($Python.Prefix) + $Arguments
    & $Python.Executable @allArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

function ConvertTo-OpcTaskArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}
