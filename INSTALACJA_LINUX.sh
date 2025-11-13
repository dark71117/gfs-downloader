#!/bin/bash
# Skrypt instalacji GFS Downloader na Linux
# Użycie: bash INSTALACJA_LINUX.sh

set -e  # Zatrzymaj przy błędzie

echo "=========================================="
echo "GFS Downloader - Instalacja na Linux"
echo "=========================================="
echo ""

# Sprawdź czy jesteś w odpowiednim katalogu
if [ ! -f "gfs_downloader_daemon.py" ]; then
    echo "❌ Błąd: Uruchom skrypt w katalogu z plikami projektu!"
    exit 1
fi

# Sprawdź Python
echo "📦 Sprawdzam Python..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 nie jest zainstalowany!"
    echo "   Zainstaluj: sudo apt-get install python3 python3-venv"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "✓ Python $PYTHON_VERSION znaleziony"

# Utwórz środowisko wirtualne
echo ""
echo "🔧 Tworzę środowisko wirtualne..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Środowisko wirtualne utworzone"
else
    echo "✓ Środowisko wirtualne już istnieje"
fi

# Aktywuj środowisko
echo ""
echo "📥 Aktywuję środowisko i instaluję zależności..."
source venv/bin/activate

# Zaktualizuj pip
pip install --upgrade pip --quiet

# Zainstaluj zależności
if [ -f "requirements.txt" ]; then
    echo "   Instaluję biblioteki z requirements.txt..."
    pip install -r requirements.txt
    echo "✓ Biblioteki zainstalowane"
else
    echo "⚠ requirements.txt nie znaleziony - pomijam instalację bibliotek"
fi

# Utwórz katalogi
echo ""
echo "📁 Tworzę katalogi..."
mkdir -p logs temp/csv_backup
chmod 755 logs temp temp/csv_backup
echo "✓ Katalogi utworzone"

# Sprawdź config.ini
echo ""
echo "⚙️  Sprawdzam config.ini..."
if [ ! -f "config.ini" ]; then
    echo "⚠ config.ini nie istnieje - utworzę przykładowy..."
    cat > config.ini << EOF
[database]
user = root
password = 
host = localhost
database = dane_gfs

[region]
lat_min = 49.0
lat_max = 55.0
lon_min = 14.0
lon_max = 24.0
EOF
    echo "✓ Przykładowy config.ini utworzony"
    echo "   ⚠️  PAMIĘTAJ: Edytuj config.ini i ustaw poprawne dane bazy!"
else
    echo "✓ config.ini istnieje"
fi

# Sprawdź czy baza danych istnieje
echo ""
echo "🗄️  Sprawdzam bazę danych..."
if command -v mysql &> /dev/null; then
    echo "   MySQL/MariaDB znaleziony"
    echo "   ⚠️  PAMIĘTAJ: Utwórz bazę danych i wykonaj create_database_complete.sql"
else
    echo "   ⚠️  MySQL/MariaDB nie znaleziony w PATH"
    echo "   Upewnij się, że baza danych jest dostępna"
fi

echo ""
echo "=========================================="
echo "✅ Instalacja zakończona!"
echo "=========================================="
echo ""
echo "Następne kroki:"
echo "1. Edytuj config.ini: nano config.ini"
echo "2. Utwórz bazę danych i wykonaj create_database_complete.sql"
echo "3. Przetestuj: source venv/bin/activate && python gfs_downloader_daemon.py"
echo "4. Uruchom jako service: patrz MIGRACJA_LINUX.md"
echo ""

