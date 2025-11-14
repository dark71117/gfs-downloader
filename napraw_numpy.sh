#!/bin/bash
# Skrypt naprawy problemu z numpy na Linux
# Użycie: bash napraw_numpy.sh

echo "🔧 Naprawa problemu z numpy..."
echo ""

# Sprawdź czy venv jest aktywne
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Środowisko wirtualne nie jest aktywne!"
    echo "   Uruchom: source venv_new/bin/activate"
    exit 1
fi

echo "📦 Odinstalowuję numpy i zależności..."
pip uninstall -y numpy xarray pandas 2>/dev/null || true

echo ""
echo "📥 Instaluję numpy 1.26.4 (kompatybilne z Python 3.9)..."
pip install --no-cache-dir numpy==1.26.4

echo ""
echo "📥 Instaluję xarray i pandas..."
pip install --no-cache-dir xarray==2024.1.0 pandas==2.2.0

echo ""
echo "📥 Instaluję pozostałe zależności..."
pip install --no-cache-dir -r requirements.txt

echo ""
echo "✅ Testuję instalację..."
python -c "import numpy; print(f'✓ numpy {numpy.__version__} OK')" || {
    echo "❌ Błąd importu numpy!"
    exit 1
}

python -c "import xarray; print('✓ xarray OK')" || {
    echo "❌ Błąd importu xarray!"
    exit 1
}

python -c "import pandas; print('✓ pandas OK')" || {
    echo "❌ Błąd importu pandas!"
    exit 1
}

echo ""
echo "✅ Naprawa zakończona pomyślnie!"
echo ""
echo "Teraz spróbuj uruchomić:"
echo "  python gfs_downloader_daemon.py"


