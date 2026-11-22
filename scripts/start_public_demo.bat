@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0.."

if not exist ".venv\Scripts\python.exe" goto missing_python

".venv\Scripts\python.exe" "scripts\start_public_demo.py"
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" pause
exit /b %RESULT%

:missing_python
echo [ERROR] Project Python environment was not found: .venv
popd
pause
exit /b 1
