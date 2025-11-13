"""
GFS Weather Data Downloader
Pobiera najnowsze dane z modelu GFS i zapisuje do bazy MySQL
"""

import xarray as xr
import pandas as pd
import requests
import io
import configparser
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import warnings
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
    exit(1)

# === 2. Budowanie URL do najnowszych danych GFS ===
try:
    # GFS jest publikowany co 6 godzin: 00, 06, 12, 18 UTC
    now_utc = datetime.utcnow()
    
    # Znajdujemy najbliższy dostępny run (z opóźnieniem ~3-4h)
    hours_since_midnight = now_utc.hour
    run_hour = (hours_since_midnight // 6) * 6
    
    # Jeśli run jest zbyt świeży, cofamy się o 6h
    run_time = now_utc.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    if (now_utc - run_time).total_seconds() < 4 * 3600:  # Mniej niż 4h
        run_time = run_time - timedelta(hours=6)
    
    RUN_DATE = run_time.strftime("%Y%m%d")
    RUN_HOUR = f"{run_time.hour:02d}"
    
    # URL do danych (prognoza +3h jako przykład, można zmienić na f000-f384)
    BASE_URL = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{RUN_DATE}/{RUN_HOUR}/atmos/"
    FILE_URL = BASE_URL + f"gfs.t{RUN_HOUR}z.pgrb2.0p25.f003"
    
    print(f"✓ URL przygotowany")
    print(f"  Run: {RUN_DATE} {RUN_HOUR}:00 UTC")
    print(f"  URL: {FILE_URL}")
    
except Exception as e:
    print(f"✗ BŁĄD przygotowania URL: {e}")
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
    exit(1)

# === 4. Parsowanie danych GRIB2 ===
try:
    print(f"⏳ Parsowanie danych GRIB2...")
    ds = xr.open_dataset(io.BytesIO(r.content), engine="cfgrib")
    
    # Wycinamy region Polski/Europy
    ds_region = ds.sel(
        latitude=slice(lat_max, lat_min), 
        longitude=slice(lon_min, lon_max)
    )
    
    print(f"✓ Dane sparsowane")
    print(f"  Dostępne zmienne: {list(ds.data_vars.keys())}")
    
except Exception as e:
    print(f"✗ BŁĄD parsowania GRIB2: {e}")
    print("  Zainstaluj cfgrib i eccodes (patrz instrukcja)")
    exit(1)

# === 5. Ekstrakcja parametrów pogodowych ===
try:
    print(f"\n⏳ Ekstrakcja parametrów pogodowych...")
    
    # Bezpieczna funkcja do pobierania zmiennych
    def safe_get(var_name, transform=None):
        try:
            data = ds_region[var_name]
            if transform:
                data = transform(data)
            return data
        except:
            return None
    
    # Słownik wszystkich parametrów (automatycznie pomija brakujące)
    variables = {
        "t2m": safe_get("t2m", lambda x: x - 273.15),  # Temperatura 2m (°C)
        "d2m": safe_get("d2m", lambda x: x - 273.15),  # Punkt rosy 2m (°C)
        "rh": safe_get("r", None),                      # Wilgotność względna (%)
        "u10": safe_get("u10", None),                   # Wiatr U 10m (m/s)
        "v10": safe_get("v10", None),                   # Wiatr V 10m (m/s)
        "gust": safe_get("gust", None),                 # Porywy wiatru (m/s)
        "mslp": safe_get("prmsl", lambda x: x / 100),   # Ciśnienie (hPa)
        "tp": safe_get("tp", None),                     # Opady (mm)
        "prate": safe_get("prate", None),               # Intensywność opadów
        "tcc": safe_get("tcc", None),                   # Zachmurzenie całkowite (%)
        "lcc": safe_get("lcc", None),                   # Zachmurzenie niskie
        "mcc": safe_get("mcc", None),                   # Zachmurzenie średnie
        "hcc": safe_get("hcc", None),                   # Zachmurzenie wysokie
        "vis": safe_get("vis", None),                   # Widzialność (m)
        "dswrf": safe_get("dswrf", None),               # Promieniowanie słoneczne
        "t850": safe_get("t", None),                    # Temperatura 850 hPa
        "gh500": safe_get("gh", None),                  # Geopotencjał 500 hPa
        "cape": safe_get("cape", None),                 # CAPE (J/kg)
        "cin": safe_get("cin", None),                   # CIN (J/kg)
        "pwat": safe_get("pwat", None),                 # Woda opadowa (kg/m²)
    }
    
    # Usuwamy puste wartości
    variables = {k: v for k, v in variables.items() if v is not None}
    
    print(f"✓ Znaleziono {len(variables)} parametrów:")
    for name in variables.keys():
        print(f"  - {name}")
    
except Exception as e:
    print(f"✗ BŁĄD ekstrakcji: {e}")
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
    
    # Dodajemy metadane
    df['run_time'] = run_time
    df['created_at'] = datetime.utcnow()
    
    # Zmieniamy nazwy kolumn
    df.rename(columns={
        'latitude': 'lat',
        'longitude': 'lon',
        'time': 'forecast_time'
    }, inplace=True)
    
    # Obliczamy prędkość wiatru
    if 'u10' in df.columns and 'v10' in df.columns:
        df['wind_speed'] = (df['u10']**2 + df['v10']**2)**0.5
        df['wind_dir'] = (270 - pd.np.arctan2(df['v10'], df['u10']) * 180 / pd.np.pi) % 360
    
    print(f"✓ Tabela utworzona: {len(df)} wierszy")
    print(f"\nPrzykładowe dane:")
    print(df.head())
    
except Exception as e:
    print(f"✗ BŁĄD tworzenia DataFrame: {e}")
    exit(1)

# === 7. Połączenie z MySQL ===
try:
    print(f"\n⏳ Łączenie z bazą MySQL...")
    
    MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"
    engine = create_engine(MYSQL_URL, echo=False)
    
    # Test połączenia
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    
    print(f"✓ Połączono z bazą: {MYSQL_DATABASE}")
    
except Exception as e:
    print(f"✗ BŁĄD połączenia z MySQL: {e}")
    print("  Sprawdź czy:")
    print("  1. XAMPP/MySQL jest uruchomiony")
    print("  2. Baza danych 'dane_gfs' istnieje")
    print("  3. Dane w config.ini są poprawne")
    exit(1)

# === 8. Zapis do bazy danych ===
try:
    print(f"\n⏳ Zapisywanie do bazy danych...")
    
    # Zapisujemy dane (zastępujemy starą tabelę)
    df.to_sql("gfs_forecast", engine, if_exists="replace", index=False, chunksize=1000)
    
    print(f"✓ Zapisano {len(df)} rekordów do tabeli 'gfs_forecast'")
    
except Exception as e:
    print(f"✗ BŁĄD zapisu: {e}")
    exit(1)

# === 9. Czyszczenie starych danych (opcjonalne) ===
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
