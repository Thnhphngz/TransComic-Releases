@echo off
setlocal
chcp 65001 >nul
if /I "%~1"=="--publish-first-internal-0.1.1" goto first_release
echo STAGE B1 — PREFLIGHT ONLY
echo INTERNAL RELEASE READINESS
echo DRY RUN - NO BUILD, INSTALL, TAG, UPLOAD OR PUBLISH
goto launch
:first_release
echo AUTHORIZED FIRST INTERNAL RELEASE v0.1.1 ONLY
:launch
set "TRANSCOMIC_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "TRANSCOMIC_PYTHON=%~dp0.venv\Scripts\python.exe"
"%TRANSCOMIC_PYTHON%" "%~dp0scripts\release_transcomic.py" %*
exit /b %errorlevel%
