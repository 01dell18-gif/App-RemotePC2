@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title FYJ Channel Remote - Universal Web Master & Client Launcher

echo ========================================================================
echo        FYJ CHANNEL REMOTE - WEB & CLASSROOM REMOTE LAUNCHER
echo ========================================================================
echo.

set "INSTALLER_DIR=%~dp0installer"
set "PACKAGES_DIR=%INSTALLER_DIR%\packages"

REM -------------------------------------------------------------------------
REM 1. PENGECEKAN PYTHON PADA SISTEM
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

REM Cari di direktori instalasi standar Windows
if exist "%LOCALAPPDATA%\Programs\Python\Python315\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python315\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe" & goto python_ready
if exist "C:\Python315\python.exe" set "PYTHON_EXE=C:\Python315\python.exe" & goto python_ready
if exist "C:\Python311\python.exe" set "PYTHON_EXE=C:\Python311\python.exe" & goto python_ready
if exist "C:\Program Files\Python315\python.exe" set "PYTHON_EXE=C:\Program Files\Python315\python.exe" & goto python_ready
if exist "C:\Program Files\Python313\python.exe" set "PYTHON_EXE=C:\Program Files\Python313\python.exe" & goto python_ready
if exist "C:\Program Files\Python312\python.exe" set "PYTHON_EXE=C:\Program Files\Python312\python.exe" & goto python_ready
if exist "C:\Program Files\Python311\python.exe" set "PYTHON_EXE=C:\Program Files\Python311\python.exe" & goto python_ready
if exist "C:\Program Files\Python310\python.exe" set "PYTHON_EXE=C:\Program Files\Python310\python.exe" & goto python_ready

REM -------------------------------------------------------------------------
REM JIKA BELUM ADA PYTHON: PASANG DARI FOLDER INSTALLER
REM -------------------------------------------------------------------------
echo.
echo [!] PERINGATAN: Python belum terpasang di perangkat ini.

set "LOCAL_PY_INST="
if exist "%INSTALLER_DIR%\python-3.11.9-amd64.exe" (
    set "LOCAL_PY_INST=%INSTALLER_DIR%\python-3.11.9-amd64.exe"
) else (
    for %%f in ("%INSTALLER_DIR%\python-*.exe") do (
        set "LOCAL_PY_INST=%%~ff"
    )
)

if defined LOCAL_PY_INST (
    echo [*] Menggunakan installer offline dari folder installer:
    echo     !LOCAL_PY_INST!
    echo [*] Memasang Python secara otomatis (silent background mode)...
    "!LOCAL_PY_INST!" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    timeout /t 6 /nobreak >nul
) else (
    echo [!] Installer lokal tidak ditemukan di folder installer.
    echo [*] Mengunduh installer resmi Python 3.11 dari internet...
    set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    set "LOCAL_PY_INST=%TEMP%\python_setup_fyj.exe"
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('!PY_URL!', '!LOCAL_PY_INST!')"
    
    if not exist "!LOCAL_PY_INST!" (
        echo [ERROR] Gagal mengunduh installer Python. Pastikan komputer terhubung ke internet.
        pause
        exit /b 1
    )
    echo [*] Memasang Python secara otomatis...
    "!LOCAL_PY_INST!" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    timeout /t 6 /nobreak >nul
)

REM Deteksi ulang setelah pemasangan
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto python_ready
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto python_ready
)

where python >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    goto python_ready
)

echo [!] Instalasi selesai. Silakan tutup dan buka kembali file ini untuk memperbarui PATH Windows.
pause
exit /b 0

:python_ready
echo [OK] Python siap digunakan: %PYTHON_EXE%

REM -------------------------------------------------------------------------
REM 2. PENGECEKAN DEPENDENSI PUSTAKA (OFFLINE DARI FOLDER INSTALLER)
REM -------------------------------------------------------------------------
echo.
echo [*] Memeriksa pustaka Python yang dibutuhkan...

"%PYTHON_EXE%" -c "import websockets, PIL, psutil, mss, win32gui" >nul 2>&1
if !errorlevel! neq 0 (
    echo [!] Dependensi pustaka belum lengkap di perangkat ini.
    
    if exist "%PACKAGES_DIR%" (
        echo [*] Memasang paket pustaka dari folder installer\packages (mode offline)...
        "%PYTHON_EXE%" -m pip install --no-index --find-links="%PACKAGES_DIR%" -r requirements.txt --quiet
    )
    
    REM Verifikasi kembali apakah sudah berhasil
    "%PYTHON_EXE%" -c "import websockets, PIL, psutil, mss, win32gui" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [*] Pustaka offline belum mencukupi, mengunduh dari PyPI resmi...
        "%PYTHON_EXE%" -m pip install -r requirements.txt --quiet
        if !errorlevel! neq 0 (
            "%PYTHON_EXE%" -m pip install websockets pillow psutil mss pywin32 --quiet
        )
    )
    echo [OK] Seluruh dependensi pustaka berhasil dipasang!
) else (
    echo [OK] Seluruh dependensi pustaka sudah lengkap!
)

REM -------------------------------------------------------------------------
REM 3. MENJALANKAN FYJ REMOTE UNIVERSAL LAUNCHER (AUTO DETECT MASTER / AGENT)
REM -------------------------------------------------------------------------
echo.
echo [*] Memulai FYJ Channel Remote...
echo ------------------------------------------------------------------------
"%PYTHON_EXE%" -u launcher.py %*

REM Jika program berhenti
echo.
echo [!] Program telah dinonaktifkan.
pause
