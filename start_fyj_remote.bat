@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title FYJ Channel Remote - Auto-Setup and Web Master Launcher

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
    goto python_found
)

where py >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=py"
    goto python_found
)

REM Cari di direktori instalasi standar Windows
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto python_found
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto python_found
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto python_found
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe" & goto python_found
if exist "C:\Program Files\Python313\python.exe" set "PYTHON_EXE=C:\Program Files\Python313\python.exe" & goto python_found
if exist "C:\Program Files\Python312\python.exe" set "PYTHON_EXE=C:\Program Files\Python312\python.exe" & goto python_found
if exist "C:\Program Files\Python311\python.exe" set "PYTHON_EXE=C:\Program Files\Python311\python.exe" & goto python_found
if exist "C:\Program Files\Python310\python.exe" set "PYTHON_EXE=C:\Program Files\Python310\python.exe" & goto python_found

REM Jika Python belum terpasang, unduh dan pasang otomatis
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
    goto python_found
)

echo [!] Instalasi selesai. Silakan jalankan kembali file ini.
pause
exit /b 0

:python_found
echo [OK] Python siap digunakan: %PYTHON_EXE%

REM -------------------------------------------------------------------------
REM 2. PENGECEKAN DEPENDENSI PUSTAKA
REM -------------------------------------------------------------------------
echo.
echo [*] Memeriksa pustaka Python yang dibutuhkan...

"%PYTHON_EXE%" -c "import websockets, PIL, psutil" >nul 2>&1
if !errorlevel! neq 0 (
    echo [*] Memasang dependensi pustaka: websockets, pillow, psutil...
    "%PYTHON_EXE%" -m pip install -r requirements.txt --quiet
    if !errorlevel! neq 0 (
        "%PYTHON_EXE%" -m pip install websockets pillow psutil mss pywin32 --quiet
    )
    echo [OK] Seluruh dependensi berhasil dipasang!
) else (
    echo [OK] Seluruh dependensi pustaka sudah lengkap!
)

REM -------------------------------------------------------------------------
REM 3. DETEKSI IP JARINGAN LAN
REM -------------------------------------------------------------------------
set "LAN_IP=127.0.0.1"
for /f "tokens=*" %%a in ('%PYTHON_EXE% -c "import socket; ips=[i for i in socket.gethostbyname_ex(socket.gethostname())[2] if not i.startswith('127.')]; ips.sort(key=lambda x: 1 if x.startswith('192.168.56.') else 0); print(ips[0] if ips else '127.0.0.1')"') do (
    set "LAN_IP=%%a"
)

REM -------------------------------------------------------------------------
REM 4. PENGECEKAN & MENJALANKAN SERVER
REM -------------------------------------------------------------------------
echo.
echo [*] Memeriksa Web Server di Port 8080...

netstat -ano | findstr /R ":8080 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo [OK] Server Web Master sudah aktif di port 8080.
) else (
    echo [*] Menyalakan Server Web Master di latar belakang...
    start /B "" "%PYTHON_EXE%" server\server.py >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo [OK] Server berhasil dinyalakan!
)

REM -------------------------------------------------------------------------
REM 5. MEMBUKA BROWSER OTOMATIS
REM -------------------------------------------------------------------------
echo [*] Membuka FYJ Channel Remote di browser...
start "" http://localhost:8080

REM -------------------------------------------------------------------------
REM 6. TAMPILAN DASHBOARD KONSOL
REM -------------------------------------------------------------------------
cls
echo ========================================================================
echo        FYJ CHANNEL REMOTE - WEB MASTER CONTROLLER SIAP
echo ========================================================================
echo.
echo  [OK] STATUS: SERVER AKTIF DAN DASHBOARD TELAH DIBUKA DI BROWSER!
echo.
echo  [1] AKSES DARI KOMPUTER INI (SERVER LOKAL):
echo      http://localhost:8080
echo.
echo  [2] AKSES DARI PERANGKAT LAIN (LAPTOP / HP / TABLET DI LAN / WI-FI):
echo      http://!LAN_IP!:8080
echo.
echo  [3] KONEKSI KOMPUTER KLIEN / SISWA (AGENT):
echo      ws://!LAN_IP!:8081
echo      (Jalankan 'run_agent.bat' atau 'run_agent_gui.bat' di PC siswa)
echo.
echo ========================================================================
echo  Tips: Buka link (2) dari browser HP/Laptop lain di jaringan yang sama
echo  untuk memonitor lab secara mobile tanpa perlu instal aplikasi tambahan.
echo.
echo  Tekan tombol apa saja untuk menutup jendela informasi ini.
echo  (Server akan tetap aktif melayani di latar belakang).
echo ========================================================================
pause >nul
