$ErrorActionPreference = "Stop"

$Services = @(
    @("控制台", 8888, "health"),
    @("脚本解析", 9992, "health"),
    @("脚本产出", 9993, "health"),
    @("脚本适配", 9994, "health"),
    @("片段产出", 9995, "health"),
    @("成品管理", 9996, "health"),
    @("产品脚本改写", 9997, "health"),
    @("钩子与CTA脚本适配", 9999, "health"),
    @("AI＋实拍混剪", 10000, "health"),
    @("混剪参考视频解析", 10002, "health"),
    @("钩子与CTA脚本复刻裂变", 10003, "health"),
    @("配音", 10004, "health"),
    @("自动发布流水线", 10005, "health"),
    @("脚本创作与适配", 10006, "health")
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
