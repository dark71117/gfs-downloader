@echo off
REM ========================================
REM Skrypt do uruchamiania GFS Downloader
REM Uzywa srodowiska conda 'gfs' z Python 3.11
REM ========================================

echo.
echo ========================================
echo   GFS Weather Data Downloader
echo ========================================
echo.

REM Sprawdz czy conda jest dostepna
where conda >nul 2>&1
if errorlevel 1 (
    echo BLAD: Conda nie jest zainstalowana lub nie jest w PATH!
    echo Upewnij sie, ze miniconda/anaconda jest zainstalowana.
    pause
    exit /b 1
)

REM Sprawdz czy config.ini istnieje
if not exist "config.ini" (
    echo UWAGA: Plik config.ini nie istnieje!
    echo.
    if exist "config.ini.example" (
        echo Tworze config.ini z pliku config.ini.example...
        copy "config.ini.example" "config.ini" >nul
        echo.
        echo OK: Plik config.ini utworzony!
        echo   Edytuj config.ini i ustaw haslo do MySQL (jesli masz).
        echo.
        pause
    ) else (
        echo BLAD: Brak pliku config.ini.example!
        echo Utworz plik config.ini recznie.
        pause
        exit /b 1
    )
)

REM Uruchom skrypt Python uzywajac srodowiska conda
echo Uruchamiam pobieranie danych GFS (srodowisko conda: gfs314, Python 3.14.0)...
echo.
conda run -n gfs314 python gfs_downloader.py

echo.
echo ========================================
echo   Koniec
echo ========================================
echo.
pause
