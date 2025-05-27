@echo off
rem Build script for Andon Server on Windows

echo Building Andon Server for Windows...

rem Create data directory
if not exist "data" mkdir data

rem Build the server
g++ -std=c++17 -Wall -Wextra -O2 -I. server.cpp output_handler.cpp -o andon_server.exe -lws2_32

if %errorlevel% equ 0 (
    echo Build successful! Created andon_server.exe
) else (
    echo Build failed!
    pause
    exit /b 1
)

pause