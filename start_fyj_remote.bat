@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title FYJ Channel Remote - Web Master Controller

echo ========================================================================
echo        FYJ CHANNEL REMOTE - WEB MASTER CONTROLLER LAUNCHER
echo ========================================================================
echo.

REM -------------------------------------------------------------------------
REM 1. PENGECEKAN PYTHON
REM -------------------------------------------------------------------------
echo [*] Memeriksa instalasi Python di komputer ini...

set "PYTHON_EXE="

where python >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    goto python_ready
)

where py >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=py"
    goto python_ready
)

REM Cari di direktori instalasi standar Windows jika belum masuk PATH
if exist "%LOCALAPPDATA%\Programs\Python\Python315\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python315\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe" & goto python_ready
if exist "C:\Program Files\Python315\python.exe" set "PYTHON_EXE=C:\Program Files\Python315\python.exe" & goto python_ready
if exist "C:\Program Files\Python313\python.exe" set "PYTHON_EXE=C:\Program Files\Python313\python.exe" & goto python_ready
if exist "C:\Program Files\Python312\python.exe" set "PYTHON_EXE=C:\Program Files\Python312\python.exe" & goto python_ready
if exist "C:\Program Files\Python311\python.exe" set "PYTHON_EXE=C:\Program Files\Python311\python.exe" & goto python_ready
if exist "C:\Program Files\Python310\python.exe" set "PYTHON_EXE=C:\Program Files\Python310\python.exe" & goto python_ready

REM Jika Python benar-benar belum terpasang di komputer baru, instal otomatis
echo.
echo [!] PERINGATAN: Python belum terpasang di komputer ini.
echo [*] Mengunduh installer resmi Python 3.11...

set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PY_INST=%TEMP%\python_setup_fyj.exe"

powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%PY_URL%', '%PY_INST%')"

if not exist "%PY_INST%" (
    echo [ERROR] Gagal mengunduh installer Python. Pastikan komputer terhubung ke internet.
    pause
    exit /b 1
)

echo [*] Memasang Python secara otomatis (silent mode)...
"%PY_INST%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
timeout /t 6 /nobreak >nul

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto python_ready
)

echo [!] Instalasi selesai. Silakan jalankan kembali file ini.
pause
exit /b 0

:python_ready
echo [OK] Python siap digunakan: %PYTHON_EXE%

REM -------------------------------------------------------------------------
REM 2. PENGECEKAN DEPENDENSI PUSTAKA
REM -------------------------------------------------------------------------
echo.
echo [*] Memeriksa pustaka Python yang dibutuhkan...

"%PYTHON_EXE%" -c "import websockets, PIL, psutil" >nul 2>&1
if !errorlevel! neq 0 (
    echo [*] Memasang pustaka: websockets, pillow, psutil, mss, pywin32...
    "%PYTHON_EXE%" -m pip install -r requirements.txt --quiet
    if !errorlevel! neq 0 (
        "%PYTHON_EXE%" -m pip install websockets pillow psutil mss pywin32 --quiet
    )
    echo [OK] Seluruh dependensi pustaka berhasil dipasang!
) else (
    echo [OK] Seluruh dependensi pustaka sudah lengkap!
)

REM -------------------------------------------------------------------------
REM 3. MENJALANKAN FYJ REMOTE SMART LAUNCHER (AUTO DETECT MASTER / AGENT)
REM -------------------------------------------------------------------------
echo.
echo [*] Memulai FYJ Channel Remote...
echo ------------------------------------------------------------------------
"%PYTHON_EXE%" -u launcher.py %*

REM Jika program berhenti
echo.
echo [!] Program telah dinonaktifkan.
pause
