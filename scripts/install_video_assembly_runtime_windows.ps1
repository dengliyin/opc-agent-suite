param(
    [string]$RuntimeRoot,
    [switch]$SkipBrowserInstall,
    [switch]$SkipWhisperModelDownload
)

. (Join-Path $PSScriptRoot "windows_common.ps1")

if ($env:OS -ne "Windows_NT") {
    throw "install_video_assembly_runtime_windows.ps1 can only run on Windows."
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "The Windows video assembly runtime requires 64-bit Windows."
}
if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
    throw "The Windows video assembly runtime currently supports x64 Windows only."
}

$RuntimeRoot = Get-OpcRuntimeRoot $RuntimeRoot
$assemblyRoot = Join-Path $RuntimeRoot "Video-Assembly-hd"
$runtime = Join-Path $assemblyRoot "runtime"
$bin = Join-Path $runtime "bin"
$downloads = Join-Path $runtime "downloads"
New-Item -ItemType Directory -Force -Path $bin, $downloads | Out-Null

$nodeVersion = "22.23.0"
$nodeArchiveName = "node-v$nodeVersion-win-x64.zip"
$nodeArchive = Join-Path $downloads $nodeArchiveName
$nodeRoot = Join-Path $runtime "node"
if (-not (Test-Path (Join-Path $nodeRoot "node.exe") -PathType Leaf)) {
    $nodeUrl = "https://nodejs.org/dist/v$nodeVersion/$nodeArchiveName"
    $checksumsUrl = "https://nodejs.org/dist/v$nodeVersion/SHASUMS256.txt"
    Write-Host "Downloading Node.js $nodeVersion..."
    Invoke-WebRequest -UseBasicParsing -Uri $nodeUrl -OutFile $nodeArchive
    $checksums = (Invoke-WebRequest -UseBasicParsing -Uri $checksumsUrl).Content
    $checksumLine = ($checksums -split "`n" | Where-Object { $_ -match "\s$([regex]::Escape($nodeArchiveName))\s*$" } | Select-Object -First 1)
    if (-not $checksumLine) { throw "Node.js checksum was not found." }
    $expectedHash = ($checksumLine.Trim() -split "\s+")[0].ToUpperInvariant()
    $actualHash = (Get-FileHash -Algorithm SHA256 $nodeArchive).Hash.ToUpperInvariant()
    if ($actualHash -ne $expectedHash) { throw "Node.js archive checksum mismatch." }
    $nodeStaging = Join-Path $downloads "node-staging"
    Remove-Item -Recurse -Force $nodeStaging -ErrorAction SilentlyContinue
    Expand-Archive -Force $nodeArchive $nodeStaging
    $expandedNode = Get-ChildItem $nodeStaging -Directory | Select-Object -First 1
    if (-not $expandedNode) { throw "Node.js archive is empty." }
    Remove-Item -Recurse -Force $nodeRoot -ErrorAction SilentlyContinue
    Move-Item $expandedNode.FullName $nodeRoot
    Remove-Item -Recurse -Force $nodeStaging
}
Copy-Item -Force (Join-Path $nodeRoot "node.exe") (Join-Path $bin "node.exe")

$ffmpeg = Join-Path $bin "ffmpeg.exe"
$ffprobe = Join-Path $bin "ffprobe.exe"
if (-not (Test-Path $ffmpeg -PathType Leaf) -or -not (Test-Path $ffprobe -PathType Leaf)) {
    $ffmpegArchive = Join-Path $downloads "ffmpeg-release-essentials.zip"
    $ffmpegStaging = Join-Path $downloads "ffmpeg-staging"
    Write-Host "Downloading the FFmpeg Windows essentials build..."
    Invoke-WebRequest -UseBasicParsing -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $ffmpegArchive
    Remove-Item -Recurse -Force $ffmpegStaging -ErrorAction SilentlyContinue
    Expand-Archive -Force $ffmpegArchive $ffmpegStaging
    $downloadedFfmpeg = Get-ChildItem $ffmpegStaging -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    $downloadedFfprobe = Get-ChildItem $ffmpegStaging -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
    if (-not $downloadedFfmpeg -or -not $downloadedFfprobe) {
        throw "The FFmpeg archive does not contain ffmpeg.exe and ffprobe.exe."
    }
    Copy-Item -Force $downloadedFfmpeg.FullName $ffmpeg
    Copy-Item -Force $downloadedFfprobe.FullName $ffprobe
    Remove-Item -Recurse -Force $ffmpegStaging
}
$ffmpegFilters = (& $ffmpeg -hide_banner -filters 2>&1 | Out-String)
if ($ffmpegFilters -notmatch '\bsubtitles\b' -or $ffmpegFilters -notmatch '\bdrawtext\b') {
    throw "The installed FFmpeg build is missing the subtitles or drawtext filter required by 9998."
}

$npmCli = Join-Path $nodeRoot "node_modules\npm\bin\npm-cli.js"
$hyperframesRoot = Join-Path $runtime "hyperframes"
$hyperframesCli = Join-Path $hyperframesRoot "node_modules\hyperframes\dist\cli.js"
if (-not (Test-Path $hyperframesCli -PathType Leaf)) {
    Write-Host "Installing HyperFrames 0.7.44..."
    $env:Path = "$nodeRoot;$bin;$env:Path"
    & (Join-Path $nodeRoot "node.exe") $npmCli install --prefix $hyperframesRoot "hyperframes@0.7.44"
    if ($LASTEXITCODE -ne 0) { throw "HyperFrames installation failed." }
}

if (-not $SkipBrowserInstall) {
    $env:Path = "$nodeRoot;$bin;$env:Path"
    $env:HYPERFRAMES_FFMPEG_PATH = $ffmpeg
    $env:HYPERFRAMES_FFPROBE_PATH = $ffprobe
    & (Join-Path $nodeRoot "node.exe") $hyperframesCli browser
    if ($LASTEXITCODE -ne 0) { throw "HyperFrames browser installation failed." }
}

$assemblyPython = Get-OpcVenvPython $RuntimeRoot "Video-Assembly-hd"
if (-not (Test-Path $assemblyPython -PathType Leaf)) {
    throw "Video-Assembly-hd Python environment is missing: $assemblyPython"
}
if (-not $SkipWhisperModelDownload) {
    $env:HF_HOME = Join-Path $runtime "cache\huggingface"
    New-Item -ItemType Directory -Force -Path $env:HF_HOME | Out-Null
    Write-Host "Downloading the faster-whisper medium model..."
    & $assemblyPython -c "import os; from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8', download_root=os.environ['HF_HOME'])"
    if ($LASTEXITCODE -ne 0) { throw "faster-whisper model download failed." }
}

& $ffmpeg -version | Select-Object -First 1
& (Join-Path $nodeRoot "node.exe") --version
Write-Host "Windows video assembly runtime installed at $runtime"
