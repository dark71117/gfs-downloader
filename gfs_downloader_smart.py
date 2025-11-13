"""
GFS Weather Data Downloader - SMART V2 FIXED
Poprawione sprawdzanie dostępności
"""

import xarray as xr
import pandas as pd
import numpy as np
import requests
import os
import configparser
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import warnings
import time
warnings.filterwarnings('ignore')

print("=" * 60)
print("GFS Weather Data Downloader - SMART V2")
print("=" * 60)

# === 1. Konfiguracja ===
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
    
    print(f"✓ Konfiguracja OK")
    print(f"  Region: {lat_min}°-{lat_max}°N, {lon_min}°-{lon_max}°E")
    
except Exception as e:
    print(f"✗ BŁĄD konfiguracji: {e}")
    input("\nEnter...")
    exit(1)

# === 2. SPRAWDŹ CO MAMy W BAZIE ===
try:
    print(f"\n⏳ Łączenie z MySQL...")
    
    MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"
    engine = create_engine(MYSQL_URL, echo=False)
    
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    
    print(f"✓ MySQL OK: {MYSQL_DATABASE}")
    
    print(f"\n⏳ Sprawdzam ostatnie dane w bazie...")
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT MAX(run_time) as last_run,
                   COUNT(*) as record_count,
                   MAX(created_at) as last_update
            FROM gfs_forecast
        """))
        row = result.fetchone()
        
        if row and row[0]:
            last_run_in_db = row[0]
            record_count = row[1]
            last_update = row[2]
            
            print(f"✓ Ostatni run w bazie: {last_run_in_db}")
            print(f"  Rekordów: {record_count}")
            print(f"  Aktualizacja: {last_update}")
            print(f"  Wiek: {(datetime.utcnow() - last_run_in_db).total_seconds() / 3600:.1f}h")
        else:
            print(f"⚠ Baza pusta - pierwszy pobór")
            last_run_in_db = None
    
except Exception as e:
    print(f"⚠ BŁĄD MySQL: {e}")
    print(f"  Kontynuuję bez sprawdzania bazy...")
    last_run_in_db = None

# === 3. POPRAWIONA FUNKCJA SPRAWDZANIA ===
def check_gfs_availability(date_str, hour_str, verbose=False):
    """
    Sprawdza czy dany run GFS jest dostępny
    Używa GET zamiast HEAD (bardziej niezawodne)
    """
    url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p25.f003"
    
    try:
        # Użyj GET z stream=True (pobiera tylko nagłówki + trochę danych)
        response = requests.get(url, stream=True, timeout=15)
        
        if verbose:
            print(f"\n  DEBUG: Status code: {response.status_code}")
            print(f"  DEBUG: URL: {url}")
            print(f"  DEBUG: Content-Type: {response.headers.get('content-type', 'unknown')}")
        
        # Zamknij połączenie natychmiast (nie pobieraj całego pliku)
        response.close()
        
        # Plik jest dostępny jeśli:
        # 1. Status 200 (OK)
        # 2. Content-Type to application/octet-stream lub nie zawiera 'text/html' (błędy są HTML)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            
            # Jeśli jest HTML, to strona błędu
            if 'text/html' in content_type:
                if verbose:
                    print(f"  DEBUG: Wykryto HTML (strona błędu)")
                return False
            
            return True
        
        return False
        
    except requests.exceptions.Timeout:
        if verbose:
            print(f"  DEBUG: Timeout")
        return False
    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"  DEBUG: Błąd: {e}")
        return False

def find_latest_gfs_run(skip_before=None):
    """Znajduje najnowszy dostępny run GFS"""
    now_utc = datetime.utcnow()
    
    print(f"\n⏳ Szukam nowych danych GFS...")
    print(f"  Czas UTC: {now_utc.strftime('%Y-%m-%d %H:%M')}")
    
    if skip_before:
        print(f"  Szukam nowszych niż: {skip_before.strftime('%Y-%m-%d %H:%M')}")
    
    current_run_hour = (now_utc.hour // 6) * 6
    run_time = now_utc.replace(hour=current_run_hour, minute=0, second=0, microsecond=0)
    
    # Sprawdź maksymalnie 4 run'y wstecz
    for i in range(4):
        check_time = run_time - timedelta(hours=i * 6)
        
        # Pomiń jeśli już mamy w bazie
        if skip_before and check_time <= skip_before:
            print(f"  → {check_time.strftime('%Y-%m-%d %H:00')} UTC - pomijam (już w bazie)")
            continue
        
        date_str = check_time.strftime("%Y%m%d")
        hour_str = f"{check_time.hour:02d}"
        
        print(f"  → Sprawdzam: {check_time.strftime('%Y-%m-%d %H:00')} UTC...", end=' ')
        
        # Sprawdź z verbose=True dla pierwszego sprawdzenia (debug)
        is_available = check_gfs_availability(date_str, hour_str, verbose=(i==0))
        
        if is_available:
            print(f"✓ DOSTĘPNY!")
            hours_old = (now_utc - check_time).total_seconds() / 3600
            print(f"     Wiek: {hours_old:.1f}h")
            return check_time, date_str, hour_str
        else:
            print(f"⚠ niedostępny")
            
            # Dla najnowszego run'u, sprawdź czy już minęło 4h
            if i == 0:
                hours_since_run = (now_utc - check_time).total_seconds() / 3600
                if hours_since_run < 3.5:
                    print(f"     (minęło dopiero {hours_since_run:.1f}h, normalnie dostępny po ~3.5h)")
    
    return None, None, None

try:
    run_time, RUN_DATE, RUN_HOUR = find_latest_gfs_run(skip_before=last_run_in_db)
    
    if run_time is None:
        print("\n" + "=" * 60)
        print("ℹ️  BRAK NOWYCH DANYCH")
        print("=" * 60)
        if last_run_in_db:
            print(f"Ostatni run w bazie: {last_run_in_db.strftime('%Y-%m-%d %H:%M')} UTC")
            print(f"Wiek danych: {(datetime.utcnow() - last_run_in_db).total_seconds() / 3600:.1f}h")
            print(f"\nDane są aktualne! 🎉")
            print(f"Następny run GFS: {(last_run_in_db + timedelta(hours=6)).strftime('%H:00 UTC')}")
            
            # Oblicz kiedy będzie dostępny
            next_run = last_run_in_db + timedelta(hours=6)
            next_available = next_run + timedelta(hours=3.5)
            print(f"Będzie dostępny około: {next_available.strftime('%Y-%m-%d %H:%M UTC')}")
        else:
            print(f"Nie znaleziono żadnych dostępnych danych GFS.")
            print(f"Spróbuj ponownie za 30 minut.")
        print("=" * 60)
        input("\nNaciśnij Enter...")
        exit(0)
    
    FILE_URL = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{RUN_DATE}/{RUN_HOUR}/atmos/gfs.t{RUN_HOUR}z.pgrb2.0p25.f003"
    
    print(f"\n✓ NOWY RUN ZNALEZIONY!")
    print(f"  Run: {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    if last_run_in_db:
        print(f"  Poprzedni: {last_run_in_db.strftime('%Y-%m-%d %H:00')} UTC")
        hours_newer = (run_time - last_run_in_db).total_seconds() / 3600
        print(f"  Świeższy o: {hours_newer:.1f}h")
    print(f"  URL: {FILE_URL[:70]}...")
    
except Exception as e:
    print(f"✗ BŁĄD: {e}")
    input("\nEnter...")
    exit(1)

# === 4. Pobieranie ===
try:
    print(f"\n⏳ Pobieranie nowych danych GFS...")
    print(f"  (~500 MB, 1-3 minuty)")
    
    response = requests.get(FILE_URL, stream=True, timeout=300)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    chunk_size = 1024 * 1024
    
    content = bytearray()
    
    for chunk in response.iter_content(chunk_size=chunk_size):
        if chunk:
            content.extend(chunk)
            downloaded += len(chunk)
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                mb_downloaded = downloaded / 1024 / 1024
                mb_total = total_size / 1024 / 1024
                print(f"\r  Pobrano: {mb_downloaded:.1f}/{mb_total:.1f} MB ({percent:.1f}%)", end='')
    
    print()
    print(f"✓ Pobrano {len(content) / 1024 / 1024:.1f} MB")
    
except requests.exceptions.RequestException as e:
    print(f"\n✗ BŁĄD pobierania: {e}")
    input("\nEnter...")
    exit(1)

# === 5. Zapis lokalny ===
try:
    if not os.path.exists('temp'):
        os.makedirs('temp')
    
    grib_file = os.path.join('temp', f'gfs_{RUN_DATE}_{RUN_HOUR}.grib2')
    
    print(f"⏳ Zapisywanie: {grib_file}")
    with open(grib_file, 'wb') as f:
        f.write(content)
    print(f"✓ Zapisano")
    
except Exception as e:
    print(f"✗ BŁĄD zapisu: {e}")
    input("\nEnter...")
    exit(1)

# === 6. Parsowanie ===
print(f"\n⏳ Parsowanie GRIB2...")

all_datasets = []

filters_config = [
    {'name': 'mslp', 'filter': {'typeOfLevel': 'meanSea', 'stepType': 'instant'}, 'vars': ['prmsl']},
    {'name': 'precip', 'filter': {'typeOfLevel': 'surface', 'stepType': 'accum'}, 'vars': ['tp']},
    {'name': 'clouds', 'filter': {'typeOfLevel': 'surface', 'stepType': 'instant'}, 'vars': ['tcc']},
    {'name': 't2m', 'filter': {'typeOfLevel': 'heightAboveGround', 'level': 2, 'stepType': 'instant'}, 'vars': ['t2m', 'd2m', 'r2']},
    {'name': 'wind10', 'filter': {'typeOfLevel': 'heightAboveGround', 'level': 10, 'stepType': 'instant'}, 'vars': ['u10', 'v10', 'gust']},
    {'name': 'wind80', 'filter': {'typeOfLevel': 'heightAboveGround', 'level': 80, 'stepType': 'instant'}, 'vars': ['u', 'v', 't']},
    {'name': 'cape', 'filter': {'typeOfLevel': 'atmosphere', 'stepType': 'instant'}, 'vars': ['cape', 'cin', 'pwat']},
    {'name': 't850', 'filter': {'typeOfLevel': 'isobaricInhPa', 'level': 850}, 'vars': ['t', 'gh']},
    {'name': 'gh500', 'filter': {'typeOfLevel': 'isobaricInhPa', 'level': 500}, 'vars': ['gh']},
]

try:
    for flt_cfg in filters_config:
        name = flt_cfg['name']
        print(f"  → {name}...", end=' ')
        
        try:
            ds = xr.open_dataset(grib_file, engine='cfgrib',
                backend_kwargs={'filter_by_keys': flt_cfg['filter'], 'indexpath': ''})
            
            ds_region = ds.sel(latitude=slice(lat_max, lat_min), longitude=slice(lon_min, lon_max))
            
            all_datasets.append({'name': name, 'dataset': ds_region, 'vars': flt_cfg['vars']})
            
            found = [v for v in flt_cfg['vars'] if v in ds_region.data_vars]
            print(f"✓ ({', '.join(found) if found else 'pusty'})")
            
        except Exception as e:
            print(f"⚠")
            continue
    
    print(f"\n✓ Otworto {len(all_datasets)} dataset(ów)")
    
except Exception as e:
    print(f"✗ BŁĄD: {e}")
    input("\nEnter...")
    exit(1)

# === 7. Konwersja ===
print(f"\n⏳ Konwersja do DataFrame...")

try:
    df = None
    
    for ds_info in all_datasets:
        ds = ds_info['dataset']
        level_name = ds_info['name']
        
        for var in ds_info['vars']:
            if var not in ds.data_vars:
                continue
            
            try:
                data = ds[var]
                
                if var in ['t2m', 'd2m', 't']:
                    data = data - 273.15
                elif var == 'prmsl':
                    data = data / 100
                elif var == 'tcc':
                    data = data * 100
                
                tmp = data.to_dataframe().reset_index()
                coords = [c for c in ['latitude', 'longitude', 'time'] if c in tmp.columns]
                
                new_name = var
                if var in ['t', 'gh', 'u', 'v'] and level_name not in ['t2m', 'wind10']:
                    new_name = f"{var}_{level_name}"
                
                if var in tmp.columns:
                    tmp.rename(columns={var: new_name}, inplace=True)
                
                cols = coords + [new_name]
                tmp = tmp[cols]
                
                if df is None:
                    df = tmp
                else:
                    df = df.merge(tmp, on=coords, how='outer')
                
            except Exception as e:
                pass
    
    df['run_time'] = run_time
    df['created_at'] = datetime.utcnow()
    
    df.rename(columns={'latitude': 'lat', 'longitude': 'lon', 'time': 'forecast_time'}, inplace=True)
    
    if 'u10' in df.columns and 'v10' in df.columns:
        df['wind_speed'] = np.sqrt(df['u10']**2 + df['v10']**2)
        df['wind_dir'] = (270 - np.arctan2(df['v10'], df['u10']) * 180 / np.pi) % 360
    
    print(f"✓ Tabela: {len(df)} wierszy, {len(df.columns)} kolumn")
    
except Exception as e:
    print(f"✗ BŁĄD: {e}")
    import traceback
    traceback.print_exc()
    input("\nEnter...")
    exit(1)

# === 8. Zamknij i usuń ===
try:
    for ds_info in all_datasets:
        ds_info['dataset'].close()
    
    if os.path.exists(grib_file):
        os.remove(grib_file)
        print(f"✓ Plik tymczasowy usunięty")
    
except:
    pass

# === 9. Zapis do bazy ===
try:
    print(f"\n⏳ Zapisywanie do bazy...")
    
    df.to_sql("gfs_forecast", engine, if_exists="replace", index=False, chunksize=1000)
    
    print(f"✓ Zapisano {len(df)} rekordów")
    
except Exception as e:
    print(f"✗ BŁĄD: {e}")
    input("\nEnter...")
    exit(1)

# === 10. Czyszczenie ===
try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM gfs_forecast 
            WHERE run_time < DATE_SUB(NOW(), INTERVAL 24 HOUR)
        """))
        conn.commit()
        print(f"✓ Wyczyszczono {result.rowcount} starych rekordów")
    
except:
    pass

# === 11. Podsumowanie ===
print("\n" + "=" * 60)
print("✓✓✓ SUKCES - NOWE DANE ZAPISANE!")
print("=" * 60)
print(f"Run GFS:     {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
print(f"Wiek danych: {(datetime.utcnow() - run_time).total_seconds() / 3600:.1f}h")
print(f"Rekordów:    {len(df)}")
print(f"Tabela:      gfs_forecast")
print(f"Baza:        {MYSQL_DATABASE}")
print("=" * 60)

if last_run_in_db:
    hours_newer = (run_time - last_run_in_db).total_seconds() / 3600
    print(f"\n💡 Dane świeższe o {hours_newer:.1f}h od poprzednich!")

print(f"\n📅 Następny run GFS: {(run_time + timedelta(hours=6)).strftime('%H:00 UTC')}")
next_available = run_time + timedelta(hours=9, minutes=30)
print(f"   Będzie dostępny około: {next_available.strftime('%H:%M UTC')}")

input("\n\nNaciśnij Enter...")
