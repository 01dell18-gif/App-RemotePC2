@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title FYJ Channel Remote - Target Client Agent
cd /d "%~dp0"

echo ========================================================
echo        FYJ CHANNEL REMOTE - TARGET CLIENT AGENT
echo ========================================================
echo.

:: 1. Cek Python
set "PYTHON_CMD="
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
) else (
    py -3 --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py -3"
    )
)

if "%PYTHON_CMD%"=="" (
    for %%p in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
        "C:\Program Files\Python310\python.exe"
    ) do (
        if exist %%p (
            set "PYTHON_CMD=%%~p"
            for %%d in (%%~dp) do set "PATH=%%~d;%%~dScripts;!PATH!"
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo [!] Python belum terpasang. Menginstal otomatis...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '$env:TEMP\py_inst.exe')"
    "%TEMP%\py_inst.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    timeout /t 5 /nobreak >nul
    set "PYTHON_CMD=python"
)

:: 2. Cek Dependensi
%PYTHON_CMD% -c "import websockets, PIL, psutil" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Memasang dependensi agent...
    %PYTHON_CMD% -m pip install -r requirements.txt --quiet
)

:: 3. Jalankan Agent
%PYTHON_CMD% agent\fyj_agent.py %*
pause
