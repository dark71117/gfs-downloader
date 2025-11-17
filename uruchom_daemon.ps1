# Skrypt PowerShell do uruchamiania GFS Downloader Daemon
# Uzycie: .\uruchom_daemon.ps1

Write-Host ""
Write-Host "========================================"
Write-Host "  GFS Weather Data Downloader"
Write-Host "  DAEMON VERSION"
Write-Host "========================================"
Write-Host ""

# Sprawdz czy conda jest dostepna
$condaExists = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaExists) {
    Write-Host "BLAD: Conda nie jest zainstalowana lub nie jest w PATH!" -ForegroundColor Red
    Write-Host "Upewnij sie, ze miniconda/anaconda jest zainstalowana."
    Read-Host "Nacisnij Enter aby zakonczyc"
    exit 1
}

# Sprawdz czy config.ini istnieje
if (-not (Test-Path "config.ini")) {
    Write-Host "UWAGA: Plik config.ini nie istnieje!" -ForegroundColor Yellow
    Write-Host ""
    if (Test-Path "config.ini.example") {
        Write-Host "Tworze config.ini z pliku config.ini.example..."
        Copy-Item "config.ini.example" "config.ini"
        Write-Host ""
        Write-Host "OK: Plik config.ini utworzony!" -ForegroundColor Green
        Write-Host "  Edytuj config.ini i ustaw haslo do MySQL (jesli masz)."
        Write-Host ""
        Read-Host "Nacisnij Enter aby kontynuowac"
    } else {
        Write-Host "BLAD: Brak pliku config.ini.example!" -ForegroundColor Red
        Write-Host "Utworz plik config.ini recznie."
        Read-Host "Nacisnij Enter aby zakonczyc"
        exit 1
    }
}

# Uruchom skrypt Python uzywajac srodowiska conda
Write-Host "Uruchamiam daemon (srodowisko conda: gfs314, Python 3.14.0)..."
Write-Host "Daemon bedzie dzialal w tle i sprawdzal nowe dane co 20 minut."
Write-Host "Aby zatrzymac, nacisnij Ctrl+C"
Write-Host ""
conda run -n gfs314 python gfs_downloader_daemon.py
