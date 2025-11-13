"""
GFS Weather Data Downloader - FIXED VERSION
Poprawiona obsługa plików GRIB2
"""

import xarray as xr
import pandas as pd
import requests
import io
import configparser
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import warnings
import tempfile
import os
warnings.filterwarnings('ignore')

print("=" * 60)
print("GFS Weather Data Downloader - Start")
print("=" * 60)

# === 1. Wczytanie konfiguracji ===
try:
    config = configparser.ConfigParser()
    config.read("config.ini", encoding='utf-8')
    
    MYSQL_USER = config["database"]["user"]
    MYSQL_PASSWORD = config["database"]["password"]
    MYSQL_HOST = config["database"]["host"]
    MYSQL_DATABASE = config["database"]["database"]
    
    lat_min = float(config["region"]["lat_min"])
    lat_max = float(config["region"]["lat_max"])
    lon_min = float(config["region"]["lon_min"])
    lon_max = float(config["region"]["lon_max"])
    
    print(f"✓ Konfiguracja wczytana")
    print(f"  Region: lat={lat_min}-{lat_max}, lon={lon_min}-{lon_max}")
    
except Exception as e:
    print(f"✗ BŁĄD wczytywania konfiguracji: {e}")
    print("  Upewnij się, że plik config.ini istnieje!")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 2. Budowanie URL do najnowszych danych GFS ===
try:
    now_utc = datetime.utcnow()
    hours_since_midnight = now_utc.hour
    run_hour = (hours_since_midnight // 6) * 6
    
    run_time = now_utc.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    if (now_utc - run_time).total_seconds() < 4 * 3600:
        run_time = run_time - timedelta(hours=6)
    
    RUN_DATE = run_time.strftime("%Y%m%d")
    RUN_HOUR = f"{run_time.hour:02d}"
    
    BASE_URL = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{RUN_DATE}/{RUN_HOUR}/atmos/"
    FILE_URL = BASE_URL + f"gfs.t{RUN_HOUR}z.pgrb2.0p25.f003"
    
    print(f"✓ URL przygotowany")
    print(f"  Run: {RUN_DATE} {RUN_HOUR}:00 UTC")
    print(f"  URL: {FILE_URL}")
    
except Exception as e:
    print(f"✗ BŁĄD przygotowania URL: {e}")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 3. Pobieranie danych GFS ===
try:
    print(f"\n⏳ Pobieranie danych (może zająć 1-2 minuty)...")
    r = requests.get(FILE_URL, timeout=300)
    r.raise_for_status()
    
    print(f"✓ Dane pobrane ({len(r.content) / 1024 / 1024:.1f} MB)")
    
except requests.exceptions.RequestException as e:
    print(f"✗ BŁĄD pobierania: {e}")
    print("  Sprawdź połączenie internetowe lub spróbuj później")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 4. Parsowanie danych GRIB2 - POPRAWIONA WERSJA ===
try:
    print(f"⏳ Parsowanie danych GRIB2...")
    
    # Metoda 1: Zapis do tymczasowego pliku (najbezpieczniejsza)
    with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as tmp_file:
        tmp_file.write(r.content)
        tmp_path = tmp_file.name
    
    try:
        # Otwórz z pliku tymczasowego
        ds = xr.open_dataset(tmp_path, engine="cfgrib", backend_kwargs={'indexpath': ''})
        
        # Wycinamy region
        ds_region = ds.sel(
            latitude=slice(lat_max, lat_min), 
            longitude=slice(lon_min, lon_max)
        )
        
        print(f"✓ Dane sparsowane (metoda: tymczasowy plik)")
        print(f"  Dostępne zmienne: {list(ds.data_vars.keys())[:10]}...")
        
    finally:
        # Usuń tymczasowy plik
        try:
            os.unlink(tmp_path)
        except:
            pass
    
except Exception as e:
    print(f"✗ BŁĄD parsowania GRIB2: {e}")
    print("\n  Próba alternatywnej metody...")
    
    # Metoda 2: Bezpośrednio z BytesIO (dla starszych wersji)
    try:
        bytes_io = io.BytesIO(r.content)
        ds = xr.open_dataset(bytes_io, engine="cfgrib")
        
        ds_region = ds.sel(
            latitude=slice(lat_max, lat_min), 
            longitude=slice(lon_min, lon_max)
        )
        
        print(f"✓ Dane sparsowane (metoda: BytesIO)")
        
    except Exception as e2:
        print(f"✗ Obie metody zawiodły:")
        print(f"  Błąd 1: {e}")
        print(f"  Błąd 2: {e2}")
        print("\n  Zainstaluj/zaktualizuj cfgrib przez conda:")
        print("  conda install -c conda-forge cfgrib eccodes")
        input("\nNaciśnij Enter aby zakończyć...")
        exit(1)

# === 5. Ekstrakcja parametrów pogodowych ===
try:
    print(f"\n⏳ Ekstrakcja parametrów pogodowych...")
    
    def safe_get(var_name, transform=None):
        try:
            if var_name not in ds_region.data_vars:
                return None
            data = ds_region[var_name]
            if transform:
                data = transform(data)
            return data
        except Exception as e:
            print(f"  ⚠ Nie można pobrać {var_name}: {e}")
            return None
    
    variables = {
        "t2m": safe_get("t2m", lambda x: x - 273.15),
        "d2m": safe_get("d2m", lambda x: x - 273.15),
        "rh": safe_get("r", None),
        "u10": safe_get("u10", None),
        "v10": safe_get("v10", None),
        "gust": safe_get("gust", None),
        "mslp": safe_get("prmsl", lambda x: x / 100),
        "tp": safe_get("tp", None),
        "prate": safe_get("prate", None),
        "tcc": safe_get("tcc", None),
        "lcc": safe_get("lcc", None),
        "mcc": safe_get("mcc", None),
        "hcc": safe_get("hcc", None),
        "vis": safe_get("vis", None),
        "dswrf": safe_get("dswrf", None),
        "t850": safe_get("t", None),
        "gh500": safe_get("gh", None),
        "cape": safe_get("cape", None),
        "cin": safe_get("cin", None),
        "pwat": safe_get("pwat", None),
    }
    
    variables = {k: v for k, v in variables.items() if v is not None}
    
    print(f"✓ Znaleziono {len(variables)} parametrów:")
    for name in list(variables.keys())[:10]:
        print(f"  - {name}")
    if len(variables) > 10:
        print(f"  ... i {len(variables) - 10} więcej")
    
except Exception as e:
    print(f"✗ BŁĄD ekstrakcji: {e}")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 6. Tworzenie DataFrame ===
try:
    print(f"\n⏳ Tworzenie tabeli danych...")
    
    df = None
    for name, da in variables.items():
        tmp = da.to_dataframe().reset_index()
        cols = ['latitude', 'longitude', 'time', name]
        tmp = tmp[[c for c in cols if c in tmp.columns]]
        
        if df is None:
            df = tmp
        else:
            df = df.merge(tmp, on=['latitude', 'longitude', 'time'], how='outer')
    
    df['run_time'] = run_time
    df['created_at'] = datetime.utcnow()
    
    df.rename(columns={
        'latitude': 'lat',
        'longitude': 'lon',
        'time': 'forecast_time'
    }, inplace=True)
    
    if 'u10' in df.columns and 'v10' in df.columns:
        df['wind_speed'] = (df['u10']**2 + df['v10']**2)**0.5
        import numpy as np
        df['wind_dir'] = (270 - np.arctan2(df['v10'], df['u10']) * 180 / np.pi) % 360
    
    print(f"✓ Tabela utworzona: {len(df)} wierszy")
    print(f"\nPrzykładowe dane:")
    print(df.head())
    
except Exception as e:
    print(f"✗ BŁĄD tworzenia DataFrame: {e}")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 7. Połączenie z MySQL ===
try:
    print(f"\n⏳ Łączenie z bazą MySQL...")
    
    MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"
    engine = create_engine(MYSQL_URL, echo=False)
    
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    
    print(f"✓ Połączono z bazą: {MYSQL_DATABASE}")
    
except Exception as e:
    print(f"✗ BŁĄD połączenia z MySQL: {e}")
    print("  Sprawdź czy:")
    print("  1. XAMPP/MySQL jest uruchomiony")
    print("  2. Baza danych 'dane_gfs' istnieje")
    print("  3. Dane w config.ini są poprawne")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 8. Zapis do bazy danych ===
try:
    print(f"\n⏳ Zapisywanie do bazy danych...")
    
    df.to_sql("gfs_forecast", engine, if_exists="replace", index=False, chunksize=1000)
    
    print(f"✓ Zapisano {len(df)} rekordów do tabeli 'gfs_forecast'")
    
except Exception as e:
    print(f"✗ BŁĄD zapisu: {e}")
    input("\nNaciśnij Enter aby zakończyć...")
    exit(1)

# === 9. Czyszczenie starych danych ===
try:
    print(f"\n⏳ Czyszczenie starych prognoz...")
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM gfs_forecast 
            WHERE run_time < DATE_SUB(NOW(), INTERVAL 12 HOUR)
        """))
        conn.commit()
        
        print(f"✓ Usunięto {result.rowcount} starych rekordów")
    
except Exception as e:
    print(f"⚠ Ostrzeżenie przy czyszczeniu: {e}")

# === 10. Podsumowanie ===
print("\n" + "=" * 60)
print("✓✓✓ SUKCES! Dane GFS pobrane i zapisane")
print("=" * 60)
print(f"Run time:      {run_time}")
print(f"Rekordów:      {len(df)}")
print(f"Parametrów:    {len(variables)}")
print(f"Tabela:        gfs_forecast")
print(f"Baza:          {MYSQL_DATABASE}")
print("=" * 60)

input("\nNaciśnij Enter aby zakończyć...")
