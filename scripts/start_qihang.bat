@echo off
REM ================================================================
REM 启航 · 一键启动  (UTF-8, run with chcp 65001)
REM Usage: start_qihang.bat [port] [lan]
REM        port  服务端口，默认 8000
REM        lan   绑 0.0.0.0，供手机/平板经局域网访问；不带则只绑 127.0.0.1
REM Steps: check env -> check frontend -> start uvicorn -> wait health
REM        -> open browser -> print demo accounts
REM ================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion

set "PORT=%~1"
if not defined PORT set "PORT=8000"

REM 第二个参数 lan：绑 0.0.0.0 开放局域网；默认只绑回环地址（仅本机能访问）
set "HOST=127.0.0.1"
set "LANMODE=0"
set "LANIP="
if /i "%~2"=="lan" (
    set "HOST=0.0.0.0"
    set "LANMODE=1"
)

REM lan 模式取本机局域网 IPv4：排除回环、169.254 与 VMware / 虚拟机网卡，
REM 按 InterfaceMetric 升序取第一个（通常是真实以太网或 WiFi）
if "!LANMODE!"=="1" (
    for /f "usebackq tokens=*" %%A in (`powershell -NoProfile -Command "$ip=Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue ^| Where-Object {$_.IPAddress -notmatch '^(127^|169\.254)' -and $_.InterfaceAlias -notmatch 'VMware^|VirtualBox^|Hyper-V^|vEthernet'} ^| Sort-Object InterfaceMetric ^| Select-Object -First 1 -ExpandProperty IPAddress; if($ip){$ip}else{'未获取到'}"`) do set "LANIP=%%A"
)

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"
set "PY=%ROOT%\.venv\Scripts\python.exe"

echo ==========================================================
echo   启航 · 学业预警与职业发展助手
if "!LANMODE!"=="1" (
    echo   一键启动   端口 %PORT%   模式 局域网（%HOST%）
) else (
    echo   一键启动   端口 %PORT%   模式 本机（%HOST%）
)
echo ==========================================================
echo.

REM --- 1. 环境检查 ------------------------------------------------
echo [1/5] 检查运行环境
if not exist "%PY%" (
    echo       [错误] 未找到虚拟环境：%PY%
    echo       请先创建 .venv 并安装 requirements.txt
    echo.
    pause
    exit /b 1
)
echo       Python 虚拟环境 OK

if not exist "%ROOT%\.env" (
    echo       [警告] 未找到 .env，数据库连接与 DeepSeek 密钥将读不到
) else (
    echo       配置文件 .env OK
)

REM --- 2. 前端产物检查 -------------------------------------------
echo.
echo [2/5] 检查前端构建产物
if exist "%ROOT%\web\dist\index.html" (
    echo       web\dist 已就绪
) else (
    echo       未找到 web\dist\index.html，页面版将不可用（仅 API 可用）
    set "ANS=N"
    set /p "ANS=现在构建前端？首次需联网装依赖，直接回车跳过 [Y/N]: "
    if /i "!ANS!"=="Y" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\build_web.ps1"
    ) else (
        echo       已跳过，稍后可运行 scripts\build_web.ps1 构建
    )
)

REM --- 3. 启动服务 ------------------------------------------------
echo.
echo [3/5] 启动后端服务
netstat -ano | findstr ":%PORT% " | findstr /i "LISTENING" >nul
if !errorlevel!==0 (
    echo       端口 %PORT% 已被占用，服务已在运行，直接复用
) else (
    echo       新窗口启动 uvicorn（该窗口可直接看日志，关闭即停服务）
    start "启航·后端服务 %PORT%" "%PY%" -m uvicorn app.main:app --host %HOST% --port %PORT%
)

REM --- 4. 等待健康检查 -------------------------------------------
echo.
echo [4/5] 等待服务就绪
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ok=$false; for($i=0;$i -lt 40;$i++){ Start-Sleep -Milliseconds 1500; try{ $r=Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/health' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){ $ok=$true; break } }catch{} }; if($ok){ $j=$r.Content | ConvertFrom-Json; Write-Host ('      服务就绪  db=' + $j.db + '  duckdb=' + $j.duckdb + '  llm=' + $j.llm) -ForegroundColor Green; exit 0 } else { Write-Host '      等待超时，请查看服务窗口日志' -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

REM --- 5. 打开浏览器 ---------------------------------------------
echo.
echo [5/5] 打开浏览器
start "" "http://127.0.0.1:%PORT%/"

echo.
echo ================== 演示账号（口令区分大小写）==================
echo.
echo   年级     账号            口令            姓名      说明
echo   ------   -------------   -------------   --------  ------------------
echo   大一     AI20260001      123456h         黄明      12 门成绩
echo   大二     AI20250001      123456h         谢静      24 门成绩 · 考编
echo   大三     AI20240004      123456h         孙鹏      36 门成绩 · 考公
echo   大四     AI20230001      123456h         陈燕      48 门成绩 · 考研
echo   教师     T001            123456h         演示教师  任教 40 个班
echo.
echo   演示账号统一口令 = 123456h（本地/答辩演示，正式部署请改强口令）
echo   登录页选「学生」或「教师」后填入上方账号与口令
echo ==============================================================
echo.
echo 本机访问 http://127.0.0.1:%PORT%/   接口文档 http://127.0.0.1:%PORT%/docs
if "!LANMODE!"=="1" (
    echo.
    echo 手机/平板访问  http://!LANIP!:%PORT%/
    echo   —— 手机需与本电脑连同一个 WiFi。
    echo      若连不上，多半是 Windows 防火墙拦了 %PORT% 端口：首次运行弹出
    echo      「是否允许访问」时选允许（专用网络）；没有弹窗就手动加一条
    echo      %PORT% 端口的入站规则。
)
echo 关闭弹出的「启航·后端服务」窗口即可停止服务
echo.
pause
endlocal
