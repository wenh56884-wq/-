# scripts\build_web.ps1
# 职责：构建 Vue 前端到 web\dist（演示前执行一次，由 FastAPI 托管）
# 依赖：Node 22+ / npm / web\package.json
# 说明：首次会先 npm install（镜像 registry.npmmirror.com），再 npm run build；产物 = web\dist\index.html

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "web"
if (-not (Test-Path $web)) {
    Write-Host "[FAIL] 未找到前端目录：$web" -ForegroundColor Red
    exit 1
}

Set-Location $web

Write-Host "== 依赖检查 ==" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $web "node_modules"))) {
    Write-Host "首次构建，先安装依赖（镜像 registry.npmmirror.com）..."
    npm config set registry https://registry.npmmirror.com
    npm install
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] npm install 失败" -ForegroundColor Red; exit 1 }
}

Write-Host "== 构建 ==" -ForegroundColor Cyan
npm run build
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] npm run build 失败" -ForegroundColor Red; exit 1 }

$index = Join-Path $web "dist\index.html"
if (-not (Test-Path $index)) {
    Write-Host "[FAIL] 构建完成但未产出 dist\index.html" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[OK] 构建产物：$index" -ForegroundColor Green
Write-Host "启动方式：.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000" -ForegroundColor Yellow
Write-Host "演示地址：http://127.0.0.1:8000/  （FRONTEND_DIST 为空时不托管静态页）" -ForegroundColor Yellow
exit 0
