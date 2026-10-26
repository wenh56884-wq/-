@echo off
REM Double-click launcher for init_qihang.ps1  (ASCII only, safe on any locale)
REM Creates the folder skeleton of project QIHANG at D:\qihang

set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%init_qihang.ps1" -Root "D:\qihang"
echo.
pause
