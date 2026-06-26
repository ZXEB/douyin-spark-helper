# 一键安装 Chrome + chromedriver
# 需要以管理员身份运行

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Chrome + chromedriver 一键安装脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查是否已安装 Chrome
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (Test-Path $chromePath) {
    Write-Host "[√] Chrome 已安装" -ForegroundColor Green
    $chromeVersion = (Get-Item $chromePath).VersionInfo.ProductVersion
    Write-Host "    版本: $chromeVersion" -ForegroundColor Gray
} else {
    Write-Host "[*] 正在下载 Chrome..." -ForegroundColor Yellow
    
    $chromeInstaller = "$env:TEMP\chrome_installer.exe"
    $chromeUrl = "https://dl.google.com/chrome/install/latest/chrome_installer.exe"
    
    try {
        Invoke-WebRequest -Uri $chromeUrl -OutFile $chromeInstaller -UseBasicParsing
        Write-Host "[*] 正在安装 Chrome..." -ForegroundColor Yellow
        Start-Process -FilePath $chromeInstaller -Args "/silent /install" -Wait
        Remove-Item $chromeInstaller -Force -ErrorAction SilentlyContinue
        
        # 等待安装完成
        Start-Sleep -Seconds 10
        
        if (Test-Path $chromePath) {
            Write-Host "[√] Chrome 安装成功" -ForegroundColor Green
            $chromeVersion = (Get-Item $chromePath).VersionInfo.ProductVersion
            Write-Host "    版本: $chromeVersion" -ForegroundColor Gray
        } else {
            Write-Host "[×] Chrome 安装失败，请手动安装" -ForegroundColor Red
            Write-Host "    下载地址: https://www.google.com/chrome/" -ForegroundColor Gray
            exit 1
        }
    } catch {
        Write-Host "[×] 下载 Chrome 失败: $_" -ForegroundColor Red
        Write-Host "    请手动下载安装: https://www.google.com/chrome/" -ForegroundColor Gray
        exit 1
    }
}

Write-Host ""

# 2. 获取 Chrome 主版本号
$chromeVersion = (Get-Item $chromePath).VersionInfo.ProductVersion
$majorVersion = $chromeVersion.Split('.')[0]
Write-Host "[*] Chrome 主版本号: $majorVersion" -ForegroundColor Yellow

# 3. 检查 chromedriver
$driverPath = "C:\Windows\System32\chromedriver.exe"
$needInstall = $false

if (Test-Path $driverPath) {
    try {
        $driverVersion = & $driverPath --version 2>&1
        $driverVersion = $driverVersion -replace 'ChromeDriver ', ''
        $driverMajor = $driverVersion.Split('.')[0]
        
        if ($driverMajor -eq $majorVersion) {
            Write-Host "[√] chromedriver 已安装且版本匹配" -ForegroundColor Green
            Write-Host "    版本: $driverVersion" -ForegroundColor Gray
        } else {
            Write-Host "[!] chromedriver 版本不匹配 (当前: $driverMajor, 需要: $majorVersion)" -ForegroundColor Yellow
            $needInstall = $true
        }
    } catch {
        $needInstall = $true
    }
} else {
    Write-Host "[*] chromedriver 未安装" -ForegroundColor Yellow
    $needInstall = $true
}

if ($needInstall) {
    Write-Host "[*] 正在下载 chromedriver..." -ForegroundColor Yellow
    
    # Chrome 115+ 使用新的下载方式
    $driverMajorInt = [int]$majorVersion
    if ($driverMajorInt -ge 115) {
        # 新版 Chrome 使用 Chrome for Testing
        $versionUrl = "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_$majorVersion"
        try {
            $latestVersion = (Invoke-WebRequest -Uri $versionUrl -UseBasicParsing).Content.Trim()
            $downloadUrl = "https://storage.googleapis.com/chrome-for-testing-public/$latestVersion/win64/chromedriver-win64.zip"
        } catch {
            Write-Host "[×] 获取 chromedriver 版本失败" -ForegroundColor Red
            Write-Host "    请手动下载: https://chromedriver.chromium.org/downloads" -ForegroundColor Gray
            exit 1
        }
    } else {
        # 旧版 Chrome
        $latestVersion = (Invoke-WebRequest -Uri "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$majorVersion" -UseBasicParsing).Content.Trim()
        $downloadUrl = "https://chromedriver.storage.googleapis.com/$latestVersion/chromedriver_win32.zip"
    }
    
    $zipPath = "$env:TEMP\chromedriver.zip"
    $extractPath = "$env:TEMP\chromedriver_extract"
    
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
        
        # 解压
        if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
        
        # 查找 chromedriver.exe
        $driverFile = Get-ChildItem -Path $extractPath -Filter "chromedriver.exe" -Recurse | Select-Object -First 1
        
        if ($driverFile) {
            # 复制到系统目录
            Copy-Item $driverFile.FullName $driverPath -Force
            Write-Host "[√] chromedriver 安装成功" -ForegroundColor Green
            $newVersion = & $driverPath --version 2>&1
            Write-Host "    版本: $($newVersion -replace 'ChromeDriver ', '')" -ForegroundColor Gray
        } else {
            Write-Host "[×] 未找到 chromedriver.exe" -ForegroundColor Red
            exit 1
        }
        
        # 清理
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $extractPath -Recurse -Force -ErrorAction SilentlyContinue
        
    } catch {
        Write-Host "[×] 下载 chromedriver 失败: $_" -ForegroundColor Red
        Write-Host "    请手动下载: https://chromedriver.chromium.org/downloads" -ForegroundColor Gray
        exit 1
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "现在可以运行 抖音火花助手.exe 了" -ForegroundColor Cyan
