$ErrorActionPreference = "Stop"

$Services = @(
    @("控制台", 8888, "health"),
    @("视频采集", 9991, "api/state"),
    @("脚本解析", 9992, "api/status"),
    @("脚本产出", 9993, "api/outputs"),
    @("脚本适配", 9994, "api/outputs?target_model=veo"),
    @("片段产出", 9995, "health"),
    @("成品管理", 9996, "api/state"),
    @("产品脚本改写", 9997, "api/state"),
    @("片段合成", 9998, "api/state"),
    @("钩子与CTA脚本适配", 9999, "api/scripts?target_model=omni"),
    @("AI＋实拍混剪", 10000, "api/library"),
    @("混剪参考视频采集", 10001, "api/state"),
    @("混剪参考视频解析", 10002, "api/status"),
    @("钩子与CTA脚本复刻裂变", 10003, "api/outputs"),
    @("配音", 10004, "api/library"),
    @("自动发布流水线", 10005, "api/state")
)

$Failed = $false
foreach ($Service in $Services) {
    $Url = "http://127.0.0.1:$($Service[1])/$($Service[2])"
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 30
        if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 300) { throw "HTTP $($Response.StatusCode)" }
        Write-Host "OK    $($Service[0]) $Url ($($Response.StatusCode))"
    } catch {
        Write-Host "FAIL  $($Service[0]) $Url"
        $Failed = $true
    }
}
if ($Failed) { exit 1 }
