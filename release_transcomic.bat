@echo off
setlocal
chcp 65001 >nul
echo STAGE B1 — PREFLIGHT ONLY
echo B2.1 — ENVIRONMENT AND SECURITY PREFLIGHT ONLY
echo Không build hoặc phát hành trong giai đoạn này
echo DRY RUN - KHONG BUILD, KHONG UPLOAD, KHONG PUBLISH
set "TRANSCOMIC_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "TRANSCOMIC_PYTHON=%~dp0.venv\Scripts\python.exe"
"%TRANSCOMIC_PYTHON%" "%~dp0scripts\release_transcomic.py" %*
exit /b %errorlevel%
