@echo off
REM One-click installer — double-click this file or run from cmd.
REM Launches setup.ps1 with execution policy bypass.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if %ERRORLEVEL% NEQ 0 pause
