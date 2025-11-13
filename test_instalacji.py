"""
Test instalacji - sprawdza czy wszystkie biblioteki są zainstalowane
"""

print("=" * 60)
print("TEST INSTALACJI GFS DOWNLOADER")
print("=" * 60)
print()

# Test 1: Python
print("1. Sprawdzam wersję Python...")
import sys
print(f"   ✓ Python {sys.version.split()[0]}")

# Test 2: Podstawowe biblioteki
print("\n2. Sprawdzam podstawowe biblioteki...")
try:
    import pandas as pd
    print(f"   ✓ pandas {pd.__version__}")
except ImportError as e:
    print(f"   ✗ pandas - BRAK! Uruchom: pip install pandas")

try:
    import requests
    print(f"   ✓ requests")
except ImportError:
    print(f"   ✗ requests - BRAK! Uruchom: pip install requests")

try:
    import xarray as xr
    print(f"   ✓ xarray {xr.__version__}")
except ImportError:
    print(f"   ✗ xarray - BRAK! Uruchom: pip install xarray")

# Test 3: Baza danych
print("\n3. Sprawdzam biblioteki bazy danych...")
try:
    import sqlalchemy
    print(f"   ✓ sqlalchemy {sqlalchemy.__version__}")
except ImportError:
    print(f"   ✗ sqlalchemy - BRAK! Uruchom: pip install sqlalchemy")

try:
    import pymysql
    print(f"   ✓ pymysql")
except ImportError:
    print(f"   ✗ pymysql - BRAK! Uruchom: pip install pymysql")

# Test 4: GRIB2
print("\n4. Sprawdzam obsługę GRIB2...")
try:
    import cfgrib
    print(f"   ✓ cfgrib {cfgrib.__version__}")
except ImportError:
    print(f"   ✗ cfgrib - BRAK!")
    print("      Zainstaluj przez conda:")
    print("      conda install -c conda-forge cfgrib")

try:
    import eccodes
    print(f"   ✓ eccodes")
except ImportError:
    print(f"   ⚠ eccodes - BRAK!")
    print("      Zainstaluj przez conda:")
    print("      conda install -c conda-forge eccodes")

# Test 5: Plik konfiguracyjny
print("\n5. Sprawdzam plik konfiguracyjny...")
import os
if os.path.exists("config.ini"):
    print("   ✓ config.ini istnieje")
    import configparser
    config = configparser.ConfigParser()
    config.read("config.ini")
    
    if "database" in config:
        print("   ✓ Sekcja [database] OK")
    else:
        print("   ✗ Brak sekcji [database]")
    
    if "region" in config:
        print("   ✓ Sekcja [region] OK")
    else:
        print("   ✗ Brak sekcji [region]")
else:
    print("   ✗ config.ini NIE ISTNIEJE!")

# Test 6: Połączenie z MySQL
print("\n6. Sprawdzam połączenie z MySQL...")
try:
    config = configparser.ConfigParser()
    config.read("config.ini")
    
    from sqlalchemy import create_engine, text
    
    user = config["database"]["user"]
    password = config["database"]["password"]
    host = config["database"]["host"]
    database = config["database"]["database"]
    
    url = f"mysql+pymysql://{user}:{password}@{host}/{database}"
    engine = create_engine(url)
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print(f"   ✓ Połączenie z MySQL OK")
        print(f"   ✓ Baza: {database}")
except Exception as e:
    print(f"   ✗ Błąd połączenia z MySQL:")
    print(f"      {e}")
    print("      Sprawdź czy XAMPP/MySQL jest uruchomiony")

# Podsumowanie
print("\n" + "=" * 60)
print("PODSUMOWANIE")
print("=" * 60)
print()
print("Jeśli wszystkie testy przeszły pomyślnie (✓),")
print("możesz uruchomić główny skrypt:")
print()
print("  python gfs_downloader.py")
print()
print("Jeśli są błędy (✗), zainstaluj brakujące biblioteki")
print("zgodnie z instrukcją w INSTRUKCJA.md")
print("=" * 60)

input("\nNaciśnij Enter aby zakończyć...")
