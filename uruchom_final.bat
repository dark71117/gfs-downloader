@echo off
REM ========================================
REM GFS Downloader - FINAL WORKING VERSION
REM Używa środowiska conda 'gfs' z Python 3.11
REM ========================================

echo.
echo ========================================
echo   GFS Weather Data Downloader
echo   FINAL VERSION
echo ========================================
echo.

REM Sprawdź czy conda jest dostępna
where conda >nul 2>&1
if errorlevel 1 (
    echo BLAD: Conda nie jest zainstalowana lub nie jest w PATH!
    echo Upewnij się, że miniconda/anaconda jest zainstalowana.
    pause
    exit /b 1
)

REM Sprawdź czy config.ini istnieje
if not exist "config.ini" (
    echo UWAGA: Plik config.ini nie istnieje!
    echo.
    if exist "config.ini.example" (
        echo Tworze config.ini z pliku config.ini.example...
        copy "config.ini.example" "config.ini" >nul
        echo.
        echo ✓ Plik config.ini utworzony!
        echo   Edytuj config.ini i ustaw haslo do MySQL (jeśli masz).
        echo.
        pause
    ) else (
        echo BLAD: Brak pliku config.ini.example!
        echo Utworz plik config.ini recznie.
        pause
        exit /b 1
    )
)

echo Uruchamiam FINAL VERSION (srodowisko conda: gfs314, Python 3.14.0)...
echo.
conda run -n gfs314 python --version
echo.

REM Uruchom FINAL VERSION
conda run -n gfs314 python gfs_downloader_final.py
