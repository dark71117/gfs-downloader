@echo off
REM ========================================
REM GFS Downloader - FINAL WORKING VERSION
REM ========================================

echo.
echo ========================================
echo   GFS Weather Data Downloader
echo   FINAL VERSION
echo ========================================
echo.

REM Aktywuj środowisko conda
echo Aktywuje srodowisko conda 'gfs'...
call conda activate gfs

if errorlevel 1 (
    echo.
    echo BLAD: Nie mozna aktywowac srodowiska!
    echo.
    pause
    exit /b 1
)

echo.
python --version
echo.

REM Uruchom FINAL VERSION
python gfs_downloader_final.py
