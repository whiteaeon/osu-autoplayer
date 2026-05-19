@echo off
title osu! Mania Autoplayer
cd /d "%~dp0"

:menu
cls
echo.
echo ========================================
echo   osu! Autoplayer - Mode & Profile Menu
echo ========================================
echo.
echo Select game mode and profile:
echo.
echo [1] MANIA - ROBOT         - Perfect timing, no variance
echo [2] MANIA - STREAMY       - High variance, fast presses
echo [3] MANIA - STAMINA       - Medium variance, long holds
echo [4] MANIA - AGGRESSIVE    - Low variance, tight timing
echo [5] STANDARD - ROBOT      - Perfect clicks, no aim error
echo [6] STANDARD - PRECISE    - Tight click timing, 5px aim error
echo [7] STANDARD - CASUAL     - High variance, 15px aim error
echo [8] CUSTOM                - Run with custom arguments
echo [0] EXIT
echo.
set /p choice="Enter your choice (0-8): "

if "%choice%"=="1" (
    python main.py --mode mania --profile robot --offset 0 --break-tap-interval 400
) else if "%choice%"=="2" (
    python main.py --mode mania --profile streamy --offset 0 --break-tap-interval 400
) else if "%choice%"=="3" (
    python main.py --mode mania --profile stamina --offset 0 --break-tap-interval 400
) else if "%choice%"=="4" (
    python main.py --mode mania --profile aggressive --offset 0 --break-tap-interval 400
) else if "%choice%"=="5" (
    python main.py --mode standard --profile robot --offset 0
) else if "%choice%"=="6" (
    python main.py --mode standard --profile precise --offset 0
) else if "%choice%"=="7" (
    python main.py --mode standard --profile casual --offset 0
) else if "%choice%"=="8" (
    set /p args="Enter custom arguments (e.g. --mode mania --profile streamy): "
    python main.py %args%
) else if "%choice%"=="0" (
    exit /b 0
) else (
    echo Invalid choice. Please try again.
    timeout /t 2 /nobreak
    goto menu
)

echo.
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to return to menu...
    pause >nul
    goto menu
) else (
    echo.
    echo Map completed. Press any key to return to menu...
    pause >nul
    goto menu
)
