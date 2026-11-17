@echo off
rem ============================================================
rem  BPI-R3 tool: bam dup de chay.
rem  Tu tim board: gateway cua may tinh, 192.168.2.1 (Wi-Fi BPI-R3 / day LAN)
rem  hoac 192.168.1.24 (Wi-Fi nha VQH).
rem  Chay truc tiep 1 lenh: bpir3.bat deploy | link | web | public | log | restart | newlink | ssh
rem ============================================================
setlocal
cd /d "%~dp0"
set "SSHBASE=-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o LogLevel=ERROR -o ConnectTimeout=5"
rem -n: ssh khong doc ban phim khi chay lenh, de khong "an" mat phim chon menu.
set "SSHOPT=-n %SSHBASE%"

call :findboard
if not defined BOARD (
    echo [LOI] Khong tim thay board - da thu gateway, 192.168.2.1, 192.168.1.24.
    echo       Kiem tra board da cam dien, may tinh da bat Wi-Fi BPI-R3/VQH hoac cam day LAN.
    pause
    exit /b 1
)

if not "%~1"=="" (
    call :do_%~1
    exit /b
)

:menu
echo.
echo ===========  BPI-R3  (board: %BOARD%)  ===========
echo   1. Deploy code len board (app.py, index.html)
echo   2. Xem link cong khai (Internet)
echo   3. Mo trang web trong mang
echo   4. Mo trang web qua link cong khai
echo   5. Xem log server
echo   6. Khoi dong lai server
echo   7. Tao link cong khai moi
echo   8. Mo SSH vao board
echo   0. Thoat
echo ==================================================
choice /c 123456780 /n /m "Bam phim (0-8): "
set "K=%ERRORLEVEL%"
echo.
if "%K%"=="1" call :do_deploy
if "%K%"=="2" call :do_link
if "%K%"=="3" call :do_web
if "%K%"=="4" call :do_public
if "%K%"=="5" call :do_log
if "%K%"=="6" call :do_restart
if "%K%"=="7" call :do_newlink
if "%K%"=="8" call :do_ssh
if "%K%"=="9" exit /b 0
rem choice tra ve 0 hoac 255 khi khong doc duoc phim (vd. bi Ctrl+C) -> thoat.
if %K% GEQ 10 exit /b 1
if "%K%"=="0" exit /b 1
goto menu

rem ------------------------------------------------------------
:findboard
rem Tim board ke ca khi da doi IP LAN (xem find-board.ps1).
set "BOARD="
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find-board.ps1" > "%TEMP%\bpir3_ip.txt" 2>nul
set /p BOARD=<"%TEMP%\bpir3_ip.txt"
del "%TEMP%\bpir3_ip.txt" >nul 2>&1
exit /b

:do_deploy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -Board %BOARD%
exit /b

:do_link
set "URL="
ssh %SSHOPT% root@%BOARD% "service cftunnel url" > "%TEMP%\bpir3_url.txt"
set /p URL=<"%TEMP%\bpir3_url.txt"
del "%TEMP%\bpir3_url.txt" >nul 2>&1
if defined URL (echo Link cong khai: %URL%) else (echo Chua co link. Chon 7 de tao link moi.)
exit /b

:do_web
start "" "http://%BOARD%:8080"
exit /b

:do_public
set "URL="
call :do_link
if defined URL start "" "%URL%"
exit /b

:do_log
ssh %SSHOPT% root@%BOARD% "logread -e python3 | tail -20"
exit /b

:do_restart
ssh %SSHOPT% root@%BOARD% "service myserver restart && echo Da khoi dong lai server."
exit /b

:do_newlink
echo Dang tao link moi (khoang 10 giay)...
ssh %SSHOPT% root@%BOARD% "service cftunnel restart; for i in 1 2 3 4 5 6 7 8 9 10; do sleep 2; u=$(service cftunnel url); [ -n \"$u\" ] && break; done; echo Link moi: $u"
exit /b

:do_ssh
echo Go "exit" de quay lai menu.
ssh %SSHBASE% root@%BOARD%
exit /b
