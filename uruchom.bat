@echo off
REM ========================================
REM Skrypt do uruchamiania GFS Downloader
REM ========================================

echo.
echo ========================================
echo   GFS Weather Data Downloader
echo ========================================
echo.

REM Sprawdź czy Python jest zainstalowany
python --version >nul 2>&1
if errorlevel 1 (
    echo BLAD: Python nie jest zainstalowany!
    echo Zainstaluj Python z https://www.python.org
    pause
    exit /b 1
)

REM Uruchom skrypt Python
echo Uruchamiam pobieranie danych GFS...
echo.
python gfs_downloader.py

echo.
echo ========================================
echo   Koniec
echo ========================================
echo.
pause
