# Skrypt naprawy problemu z eccodes/cfgrib
# Użycie: .\naprawa_eccodes.ps1

Write-Host ""
Write-Host "========================================"
Write-Host "  NAPRAWA PROBLEMU Z ECCODES/CFGRIB"
Write-Host "========================================"
Write-Host ""

# Sprawdź czy conda jest dostępna
$condaExists = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaExists) {
    Write-Host "BLAD: Conda nie jest zainstalowana!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Rozwiązanie:" -ForegroundColor Yellow
    Write-Host "1. Pobierz Miniconda: https://docs.conda.io/en/latest/miniconda.html"
    Write-Host "2. Zainstaluj Miniconda (zaznacz 'Add Miniconda3 to PATH')"
    Write-Host "3. Uruchom ponownie ten skrypt"
    Write-Host ""
    Write-Host "LUB jeśli masz conda, ale nie jest w PATH:"
    Write-Host "  - Otwórz 'Anaconda PowerShell Prompt'"
    Write-Host "  - Przejdź do katalogu projektu"
    Write-Host "  - Uruchom: conda install -n gfs314 -c conda-forge eccodes cfgrib -y"
    Write-Host ""
    Read-Host "Naciśnij Enter aby zakończyć"
    exit 1
}

Write-Host "✓ Conda znaleziona!" -ForegroundColor Green
Write-Host ""

# Sprawdź czy środowisko gfs314 istnieje
$envExists = conda env list | Select-String "gfs314"
if (-not $envExists) {
    Write-Host "Tworzenie środowiska conda 'gfs314' z Python 3.14.0..." -ForegroundColor Yellow
    conda create -n gfs314 python=3.14.0 -y
    if ($LASTEXITCODE -ne 0) {
        Write-Host "BLAD: Nie udało się utworzyć środowiska!" -ForegroundColor Red
        Read-Host "Naciśnij Enter aby zakończyć"
        exit 1
    }
    Write-Host "✓ Środowisko utworzone!" -ForegroundColor Green
    Write-Host ""
}

Write-Host "Instalowanie eccodes i cfgrib przez conda-forge..." -ForegroundColor Yellow
Write-Host "(To może zająć 2-3 minuty...)"
Write-Host ""

conda install -n gfs314 -c conda-forge eccodes cfgrib -y
if ($LASTEXITCODE -ne 0) {
    Write-Host "BLAD: Nie udało się zainstalować eccodes/cfgrib!" -ForegroundColor Red
    Read-Host "Naciśnij Enter aby zakończyć"
    exit 1
}

Write-Host ""
Write-Host "Instalowanie pozostałych bibliotek z requirements.txt..." -ForegroundColor Yellow
conda run -n gfs314 pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "UWAGA: Niektóre biblioteki mogły się nie zainstalować!" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Sprawdzanie instalacji..." -ForegroundColor Yellow
$testResult = conda run -n gfs314 python -c "import eccodes; import cfgrib; import xarray; print('OK')" 2>&1
if ($testResult -match "OK") {
    Write-Host ""
    Write-Host "✓✓✓ WSZYSTKO DZIAŁA POPRAWNIE!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Teraz możesz uruchomić program:" -ForegroundColor Yellow
    Write-Host "  conda activate gfs314"
    Write-Host "  python gfs_downloader_filtered_daemon.py"
    Write-Host ""
    Write-Host "LUB użyj skryptu:" -ForegroundColor Yellow
    Write-Host "  .\uruchom_filtered_daemon.ps1"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "BLAD: Instalacja nie powiodła się!" -ForegroundColor Red
    Write-Host "Sprawdź błędy powyżej."
    Write-Host ""
}

Read-Host "Naciśnij Enter aby zakończyć"

