# start_chrome_cdp.ps1
# 一键启动带远程调试端口 (9222) 的 Chrome，供 CareerCrew (Boss直聘 + 猎聘) CDP 接管。

$candidates = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "${env:LocalAppData}\Google\Chrome\Application\chrome.exe"
)

$chromePath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chromePath) {
    Write-Host "未找到 Chrome 浏览器安装路径，请手动安装 Chrome 或修改本脚本中的路径。" -ForegroundColor Red
    exit 1
}

$userDataDir = "C:\ChromeDevData"
if (-not (Test-Path $userDataDir)) {
    New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  CareerCrew Chrome CDP 调试启动器" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Chrome 路径: $chromePath" -ForegroundColor Green
Write-Host "调试端口:   9222" -ForegroundColor Green
Write-Host "数据目录:   $userDataDir" -ForegroundColor Green
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow
Write-Host "正在启动 Chrome..." -ForegroundColor Yellow

$arguments = @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$userDataDir",
    "--no-first-run",
    "--no-default-browser-check",
    "https://www.zhipin.com",
    "https://www.liepin.com"
)

Start-Process -FilePath $chromePath -ArgumentList $arguments

Write-Host "Chrome 已成功启动！" -ForegroundColor Green
Write-Host "请在打开的浏览器标签中完成登录：" -ForegroundColor White
Write-Host "  1. 登录 Boss直聘 (https://www.zhipin.com)" -ForegroundColor White
Write-Host "  2. 登录 猎聘 (https://www.liepin.com)" -ForegroundColor White
Write-Host "登录完成后保持浏览器开启，CareerCrew 即可自动采集岗位！" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
