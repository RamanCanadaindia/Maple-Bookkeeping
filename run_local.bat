@echo off
echo ===================================================
echo   Starting Standalone Resend Email Reminder System
echo ===================================================

cd /d "%~dp0"

:: Check if Node.js is installed
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed or not in your PATH.
    echo Please install Node.js v18 or higher and try again.
    pause
    exit /b 1
)

:: Install dependencies if node_modules doesn't exist
if not exist node_modules (
    echo Installing dependencies from package.json...
    call npm install
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

:: Open browser in background after a slight delay
echo Launching local dashboard in browser...
start http://localhost:3000

:: Start Node.js application
echo Launching Node.js Express server...
node server.js

pause
