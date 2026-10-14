@echo off
setlocal
chcp 65001 >nul
echo TRANSCOMIC AUTOMATIC RELEASE SYSTEM V2
set "TRANSCOMIC_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "TRANSCOMIC_PYTHON=%~dp0.venv\Scripts\python.exe"
"%TRANSCOMIC_PYTHON%" "%~dp0scripts\automatic_release.py" %*
exit /b %errorlevel%
