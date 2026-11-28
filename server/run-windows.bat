@echo off
rem Kho linh kien + IoT tren Windows 10/11 (64-bit). Can Python 3.10+ (python.org, tick "Add python.exe to PATH").
rem Bam dup file nay de chay. Them tham so: run-windows.bat --restore ..\data-backup\bpi-data-....tar.gz.enc
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if errorlevel 1 (
  echo Chua co Python 3.10+. Tai tai https://www.python.org/downloads/windows/ , khi cai tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist data\.deps-ok (
  echo Cai thu vien lan dau: paho-mqtt, cryptography ...
  %PY% -m pip install --user -q -r requirements-desktop.txt && (mkdir data 2>nul & echo ok> data\.deps-ok)
)
%PY% desktop.py %*
pause
