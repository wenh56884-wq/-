@echo off
chcp 936 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM  启航 · 开发环境一键启动（后端 8000 + 前端 5173，带热更新）
REM  双击本文件即可；关闭弹出的两个黑窗口即停止对应服务。
REM  生产单端口模式请用 scripts\start_qihang.bat
REM ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "BE_PORT=8000"
set "FE_PORT=5173"

echo ==========================================================
echo   启航 · 开发环境一键启动
echo   后端 %BE_PORT%   前端 %FE_PORT%
echo ==========================================================
echo.

REM ---------- 1. 环境检查 ----------
echo [1/4] 检查运行环境
if not exist "%PY%" (
    echo       [错误] 未找到 .venv\Scripts\python.exe
    echo       请先创建虚拟环境并安装 requirements.txt
    echo.
    pause
    exit /b 1
)
echo       Python 虚拟环境 OK

if not exist "%ROOT%web\node_modules" (
    echo       [错误] 未找到 web\node_modules
    echo       请先执行：cd web 然后 npm install
    echo.
    pause
    exit /b 1
)
echo       前端依赖 OK

REM ---------- 2. 启动后端 ----------
echo.
echo [2/4] 启动后端（端口 %BE_PORT%）
set "BE_BUSY=0"
for /f %%i in ('powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort %BE_PORT% -State Listen -ErrorAction SilentlyContinue){1}else{0}"') do set "BE_BUSY=%%i"
if "!BE_BUSY!"=="1" (
    echo       端口已被占用，复用现有后端，不重复启动
) else (
    start "启航·后端 %BE_PORT%" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %BE_PORT%
    echo       已在新窗口启动，日志看那个窗口
)

REM ---------- 3. 启动前端 ----------
echo.
echo [3/4] 启动前端（端口 %FE_PORT%）
set "FE_BUSY=0"
for /f %%i in ('powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort %FE_PORT% -State Listen -ErrorAction SilentlyContinue){1}else{0}"') do set "FE_BUSY=%%i"
if "!FE_BUSY!"=="1" (
    echo       端口已被占用，复用现有前端，不重复启动
) else (
    pushd "%ROOT%web"
    start "启航·前端 %FE_PORT%" cmd /c "npm run dev"
    popd
    echo       已在新窗口启动，日志看那个窗口
)

REM ---------- 4. 等待就绪（都已在跑就跳过，避免无谓等待） ----------
echo.
if "!BE_BUSY!"=="1" if "!FE_BUSY!"=="1" (
    echo [4/4] 两个服务都在运行，跳过等待
) else (
    echo [4/4] 等待服务就绪（最多约 60 秒）
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$be=$false; $fe=$false; for($i=0;$i -lt 40;$i++){ Start-Sleep -Milliseconds 1200; if(-not $be){ try{ $r=Invoke-WebRequest -Uri 'http://127.0.0.1:%BE_PORT%/health' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){ $be=$true } }catch{} }; if(-not $fe){ try{ $f=Invoke-WebRequest -Uri 'http://127.0.0.1:%FE_PORT%/' -UseBasicParsing -TimeoutSec 2; if($f.StatusCode -eq 200){ $fe=$true } }catch{} }; if($be -and $fe){ break } }; $b = if($be){'就绪'}else{'未就绪'}; $f2 = if($fe){'就绪'}else{'未就绪'}; Write-Host ('      后端 ' + $b + '   前端 ' + $f2)"
)

echo.
echo 打开浏览器 http://localhost:%FE_PORT%/
start "" "http://localhost:%FE_PORT%/"

echo.
echo ==========================================================
echo   启动完成
echo   前端页面  http://localhost:%FE_PORT%/
echo   接口文档  http://127.0.0.1:%BE_PORT%/docs
echo.
echo   演示账号（统一口令 = 123456h）
echo     大一  AI20260004     123456h        未选方向，可看新生引导
echo     大二  AI20250001     123456h
echo     大三  AI20240004     123456h
echo     大四  AI20230001     123456h
echo     教师  T001           123456h
echo.
echo   关闭「启航·后端」和「启航·前端」两个窗口即停止服务
echo ==========================================================
echo.
pause
