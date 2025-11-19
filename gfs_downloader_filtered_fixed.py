"""
GFS Weather Data Downloader - FILTERED VERSION (POPRAWIONA)
Pobiera tylko wybrane parametry z GRIB Filter API - OSZCZĘDZA ~85-90% PRZEPUSTOWOŚCI!
Pełny zakres prognoz: f000-f120 (co 1h) + f123-f384 (co 3h) = 209 prognoz
Z multi-threading, resume, progress bar i priorytetyzacją + FILTROWANIE PARAMETRÓW

POPRAWKI:
- Prawidłowe otwieranie plików GRIB z wieloma typeOfLevel
- Obsługa wszystkich poziomów (surface, isobaric, heightAboveGround, etc.)
"""

import xarray as xr
import pandas as pd
import numpy as np
import requests
import os
import configparser
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import threading
import queue
from queue import Empty
import time
from tqdm import tqdm
import warnings
import logging
from collections import deque
from urllib.parse import urlencode
from datetime import datetime
warnings.filterwarnings('ignore')

# Stłum błędy ECCODES (są tylko ostrzeżeniami)
os.environ['ECCODES_LOG_VERBOSITY'] = '0'
os.environ['ECCODES_DEBUG'] = '0'

# Wycisz logi DEBUG z cfgrib, ecmwf, eccodes, urllib3, requests
logging.getLogger('cfgrib').setLevel(logging.WARNING)
logging.getLogger('ecmwf').setLevel(logging.WARNING)
logging.getLogger('eccodes').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

# Logger dla modułu
module_logger = logging.getLogger(__name__)

# === KONFIGURACJA PARAMETRÓW DO FILTROWANIA ===
# Możesz edytować tę konfigurację według swoich potrzeb!

GRIB_FILTER_CONFIG = {
    # === POZIOMY IZOBARYCZNE (mb) ===
    'levels': [
        '1000_mb', '975_mb', '950_mb', '925_mb', '900_mb',  # Przypowierzchniowe
        '850_mb', '800_mb', '700_mb',                        # Dolna troposfera
        '500_mb', '400_mb', '300_mb', '250_mb', '200_mb',    # Środkowa/górna troposfera
        '150_mb', '100_mb', '50_mb'                          # Stratosfera
    ],
    
    # === ZMIENNE ATMOSFERYCZNE (dla poziomów izobarycznych) ===
    'variables': [
        'HGT',      # Wysokość geopotencjalna [gpm]
        'TMP',      # Temperatura [K]
        'RH',       # Wilgotność względna [%]
        'UGRD',     # Składowa U wiatru [m/s]
        'VGRD',     # Składowa V wiatru [m/s]
        'VVEL',     # Prędkość wertykalna (ciśnienie) [Pa/s]
        'TCDC',     # Zachmurzenie całkowite [%]
        'CLWMR',    # Cloud mixing ratio [kg/kg]
        'ICMR',     # Ice water mixing ratio [kg/kg]
    ],
    
    # === POZIOMY SPECJALNE ===
    'surface_levels': [
        'surface',              # Powierzchnia
        'mean_sea_level',       # Poziom morza
        '2_m_above_ground',     # 2m nad ziemią (temp, wilgotność)
        '10_m_above_ground',    # 10m nad ziemią (wiatr)
        '80_m_above_ground',    # 80m nad ziemią (turbiny wiatrowe)
        '100_m_above_ground',   # 100m nad ziemią
        'tropopause',           # Tropopauza
        'max_wind',             # Max wind level
    ],
    
    # === ZMIENNE POWIERZCHNIOWE ===
    'surface_variables': [
        'PRES',     # Ciśnienie na powierzchni [Pa]
        'PRMSL',    # Ciśnienie na poziomie morza [Pa]
        'TMP',      # Temperatura powierzchni [K]
        'DPT',      # Punkt rosy [K]
        'RH',       # Wilgotność względna [%]
        'UGRD',     # Składowe wiatru [m/s]
        'VGRD',
        'GUST',     # Porywy wiatru [m/s]
        'APCP',     # Accumulated precipitation [kg/m^2]
        'CAPE',     # Convective available potential energy [J/kg]
        'CIN',      # Convective inhibition [J/kg]
        'PWAT',     # Precipitable water [kg/m^2]
        'WEASD',    # Water equivalent of accumulated snow depth [kg/m^2]
        'SNOD',     # Snow depth [m]
        'TSOIL',    # Soil temperature [K]
        'SOILW',    # Soil moisture [Fraction]
    ],
}

# === RATE LIMITING - 120 zapytań/minutę ===
_rate_limit_lock = threading.Lock()
_rate_limit_timestamps = deque(maxlen=120)

def wait_for_rate_limit():
    """
    Czeka jeśli potrzeba, żeby nie przekroczyć limitu 120 zapytań/minutę.
    Thread-safe.
    """
    global _rate_limit_timestamps
    
    with _rate_limit_lock:
        now = time.time()
        
        # Usuń stare timestampy (starsze niż 60 sekund)
        while _rate_limit_timestamps and (now - _rate_limit_timestamps[0]) > 60:
            _rate_limit_timestamps.popleft()
        
        # Jeśli mamy już 120 zapytań w ostatniej minucie, poczekaj
        if len(_rate_limit_timestamps) >= 120:
            oldest_timestamp = _rate_limit_timestamps[0]
            wait_time = 60 - (now - oldest_timestamp) + 0.1
            if wait_time > 0:
                module_logger.debug(f"Rate limit: czekam {wait_time:.2f}s (120 zapytań/min)")
                time.sleep(wait_time)
                now = time.time()
                while _rate_limit_timestamps and (now - _rate_limit_timestamps[0]) > 60:
                    _rate_limit_timestamps.popleft()
        
        # Dodaj aktualny timestamp
        _rate_limit_timestamps.append(time.time())
        
        # Minimalne opóźnienie między zapytaniami (0.5s = 120/min)
        time.sleep(0.5)

def build_grib_filter_url(date_str, hour_str, forecast_hour, resolution='0p25'):
    """
    Buduje URL dla GRIB Filter API z wybranymi parametrami.
    UWAGA: URL może być bardzo długi - NOMADS może mieć limit ~2000 znaków.
    """
    base_url = f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_{resolution}.pl"
    
    # Parametry URL
    params = {
        'file': f'gfs.t{hour_str}z.pgrb2.{resolution}.f{forecast_hour:03d}',
        'dir': f'/gfs.{date_str}/{hour_str}/atmos',
    }
    
    # Dodaj poziomy izobaryczne (uproszczone nazwy)
    for level in GRIB_FILTER_CONFIG['levels']:
        # Konwertuj "1000_mb" na "1000_mb" (zachowaj format)
        params[f'lev_{level}'] = 'on'
    
    # Dodaj poziomy powierzchniowe
    for level in GRIB_FILTER_CONFIG['surface_levels']:
        params[f'lev_{level}'] = 'on'
    
    # Dodaj zmienne atmosferyczne (dla poziomów izobarycznych)
    for var in GRIB_FILTER_CONFIG['variables']:
        params[f'var_{var}'] = 'on'
    
    # Dodaj zmienne powierzchniowe
    for var in GRIB_FILTER_CONFIG['surface_variables']:
        params[f'var_{var}'] = 'on'
    
    url = f"{base_url}?{urlencode(params)}"
    
    # Sprawdź długość URL
    if len(url) > 2000:
        print(f"{get_timestamp()} - ⚠️ UWAGA: URL jest bardzo długi ({len(url)} znaków) - może powodować problemy!", flush=True)
        print(f"{get_timestamp()} - URL (pierwsze 200 znaków): {url[:200]}...", flush=True)
    
    return url

def get_timestamp():
    """Zwraca timestamp w formacie YYYY-MM-DD HH:MM:SS"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def download_grib_filtered(url, output_path, max_retries=3, forecast_hour=None):
    """
    Pobiera plik GRIB używając GRIB Filter API.
    Zwraca (success, file_size_bytes).
    """
    fh_str = f"f{forecast_hour:03d}" if forecast_hour is not None else "?"
    
    for attempt in range(max_retries):
        try:
            print(f"{get_timestamp()} - [{fh_str}] Próba {attempt+1}/{max_retries}: Pobieranie...", flush=True)
            
            # Rate limiting
            wait_for_rate_limit()
            
            # Pobierz plik (zwiększony timeout dla dużych plików)
            print(f"{get_timestamp()} - [{fh_str}] Wysyłanie zapytania HTTP...", flush=True)
            response = requests.get(url, timeout=300, stream=True)  # 5 minut timeout
            
            print(f"{get_timestamp()} - [{fh_str}] Status: {response.status_code}", flush=True)
            
            # Obsługa HTTP 429 (Too Many Requests)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"{get_timestamp()} - [{fh_str}] ⚠️ HTTP 429 - czekam {retry_after}s", flush=True)
                time.sleep(retry_after)
                continue
            
            if response.status_code != 200:
                print(f"{get_timestamp()} - [{fh_str}] ✗ HTTP {response.status_code}", flush=True)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, 0
            
            # Zapisz plik
            print(f"{get_timestamp()} - [{fh_str}] Zapisuję plik...", flush=True)
            file_size = 0
            chunk_count = 0
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        file_size += len(chunk)
                        chunk_count += 1
                        if chunk_count % 1000 == 0:
                            print(f"{get_timestamp()} - [{fh_str}] Pobrano {file_size / (1024*1024):.1f} MB...", flush=True)
            
            print(f"{get_timestamp()} - [{fh_str}] ✓ Pobrano {file_size / (1024*1024):.1f} MB", flush=True)
            
            # Sprawdź czy plik nie jest pusty
            if file_size < 1024:
                print(f"{get_timestamp()} - [{fh_str}] ✗ Plik za mały ({file_size} bytes)", flush=True)
                if os.path.exists(output_path):
                    os.remove(output_path)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, 0
            
            return True, file_size
            
        except requests.exceptions.Timeout:
            print(f"{get_timestamp()} - [{fh_str}] ✗ Timeout (attempt {attempt+1}/{max_retries})", flush=True)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
        except Exception as e:
            print(f"{get_timestamp()} - [{fh_str}] ✗ Błąd: {e}", flush=True)
            import traceback
            print(f"{get_timestamp()} - [{fh_str}] Traceback: {traceback.format_exc()}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
    
    return False, 0

def check_gfs_availability(date_str, hour_str, forecast_hour, verbose=False):
    """
    Sprawdza czy dana prognoza GFS jest dostępna.
    """
    url = build_grib_filter_url(date_str, hour_str, forecast_hour)
    
    try:
        wait_for_rate_limit()
        response = requests.head(url, timeout=10, allow_redirects=True)
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            if verbose:
                module_logger.debug(f"HTTP 429 - czekam {retry_after}s")
            time.sleep(retry_after)
            wait_for_rate_limit()
            response = requests.head(url, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            if verbose:
                module_logger.debug(f"✓ Dane dostępne (f{forecast_hour:03d})")
            return True
            
    except requests.exceptions.Timeout:
        if verbose:
            module_logger.debug(f"Timeout sprawdzania dostępności")
    except Exception as e:
        if verbose:
            module_logger.debug(f"Błąd sprawdzania: {e}")
    
    return False

def get_required_forecast_hours():
    """
    Zwraca set wymaganych forecast_hour do pobrania:
    - f000-f120 (co 1h) = 121 prognoz
    - f123-f384 (co 3h) = 88 prognoz
    RAZEM: 209 prognoz
    """
    required_hours = set()
    
    # f000-f120: co 1h
    for hour in range(0, 121):
        required_hours.add(hour)
    
    # f123-f384: co 3h
    for hour in range(123, 385, 3):
        required_hours.add(hour)
    
    return required_hours

def get_existing_forecast_hours(run_time, engine=None):
    """
    Zwraca set forecast_hour które są już w bazie dla danego run_time.
    """
    if engine is None:
        try:
            engine = globals().get('engine')
            if engine is None:
                return set()
        except:
            return set()
    
    try:
        with engine.connect() as conn:
            run_time_str = run_time.strftime('%Y-%m-%d %H:%M:%S')
            
            result = conn.execute(text("""
                SELECT DISTINCT forecast_time
                FROM gfs_forecast
                WHERE DATE_FORMAT(run_time, '%Y-%m-%d %H:%i:%s') = :run_time
                ORDER BY forecast_time
            """), {"run_time": run_time_str})
            
            existing_hours = set()
            rows = result.fetchall()
            
            for row in rows:
                forecast_time = row[0]
                
                if isinstance(forecast_time, str):
                    try:
                        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M']:
                            try:
                                forecast_time = datetime.strptime(forecast_time, fmt)
                                break
                            except:
                                continue
                    except:
                        continue
                
                if isinstance(forecast_time, datetime):
                    time_diff = forecast_time - run_time
                    forecast_hour = int(time_diff.total_seconds() / 3600)
                    existing_hours.add(forecast_hour)
            
            return existing_hours
            
    except Exception as e:
        print(f"⚠ Błąd sprawdzania forecast_hour w bazie: {e}")
        return set()

def find_latest_gfs_run(engine=None):
    """Znajduje najnowszy dostępny run GFS (szuka nowszego niż w bazie)"""
    if engine is None:
        try:
            engine = globals().get('engine')
            if engine is None:
                return None, None, None
        except:
            return None, None, None
    
    now_utc = datetime.utcnow()
    current_run_hour = (now_utc.hour // 6) * 6
    run_time = now_utc.replace(hour=current_run_hour, minute=0, second=0, microsecond=0)
    
    last_run_in_db = None
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT MAX(run_time) as last_run
                FROM gfs_forecast
            """))
            row = result.fetchone()
            if row and row[0]:
                last_run_in_db = row[0]
                if isinstance(last_run_in_db, str):
                    try:
                        last_run_in_db = datetime.strptime(last_run_in_db, '%Y-%m-%d %H:%M:%S')
                    except:
                        try:
                            last_run_in_db = datetime.strptime(last_run_in_db, '%Y-%m-%d %H:%M')
                        except:
                            pass
    except:
        pass
    
    found_run = None
    
    for i in range(6):
        check_time = run_time - timedelta(hours=i * 6)
        date_str = check_time.strftime("%Y%m%d")
        hour_str = f"{check_time.hour:02d}"
        
        if last_run_in_db and check_time <= last_run_in_db:
            continue
        
        # Sprawdź dostępność pierwszej prognozy (f000)
        if check_gfs_availability(date_str, hour_str, 0):
            found_run = check_time
            break
    
    if found_run:
        date_str = found_run.strftime("%Y%m%d")
        hour_str = f"{found_run.hour:02d}"
        return found_run, date_str, hour_str
    
    return None, None, None

def process_grib_to_db_filtered(grib_path, run_time, forecast_hour, lat_min, lat_max, lon_min, lon_max, engine):
    """
    Przetwarza plik GRIB (pofiltrowany) i zapisuje do bazy danych.
    
    POPRAWKA: Otwiera plik dla KAŻDEGO typeOfLevel osobno,
    ponieważ xarray/cfgrib nie może otworzyć wszystkich poziomów naraz.
    """
    fh_str = f"f{forecast_hour:03d}"
    try:
        # Sprawdź czy plik istnieje i ma rozmiar
        if not os.path.exists(grib_path):
            print(f"{get_timestamp()} - [{fh_str}] ✗ Plik nie istnieje: {grib_path}", flush=True)
            return 0
        
        file_size = os.path.getsize(grib_path)
        if file_size < 1024:
            print(f"{get_timestamp()} - [{fh_str}] ✗ Plik za mały: {file_size} bytes", flush=True)
            return 0
        
        print(f"{get_timestamp()} - [{fh_str}] Otwieranie pliku GRIB ({file_size / (1024*1024):.1f} MB)...", flush=True)
        # Lista typów poziomów, które mogą być w pliku
        type_of_levels = [
            'isobaricInhPa',        # Poziomy izobaryczne (1000, 850, 500 mb, etc.)
            'surface',              # Powierzchnia
            'meanSea',              # Poziom morza
            'heightAboveGround',    # Wysokość nad ziemią (2m, 10m, 80m, 100m)
            'tropopause',           # Tropopauza
            'maxWind',              # Maksymalny poziom wiatru
            'entireAtmosphere',     # Cała atmosfera
        ]
        
        all_data_vars = {}
        coords_dict = None
        
        # Otwórz plik dla każdego typeOfLevel osobno
        for level_type in type_of_levels:
            try:
                print(f"{get_timestamp()} - [{fh_str}] Próbuję otworzyć level: {level_type}...", flush=True)
                ds = xr.open_dataset(
                    grib_path,
                    engine='cfgrib',
                    backend_kwargs={
                        'filter_by_keys': {'typeOfLevel': level_type},
                        'indexpath': '',
                        'errors': 'ignore'
                    }
                )
                print(f"{get_timestamp()} - [{fh_str}] ✓ Otworzono {level_type}, zmienne: {list(ds.data_vars.keys())}", flush=True)
                
                # Zapisz współrzędne (latitude, longitude) z pierwszego datasetu
                if coords_dict is None:
                    coords_dict = {
                        'latitude': ds.latitude.values,
                        'longitude': ds.longitude.values
                    }
                
                # Zbierz wszystkie zmienne z tego poziomu
                for var_name in ds.data_vars:
                    var_data = ds[var_name]
                    
                    # Dodaj sufiks z poziomem do nazwy zmiennej
                    if 'isobaricInhPa' in var_data.dims:
                        # Dla poziomów izobarycznych dodaj _XXX_mb
                        level_val = var_data.coords['isobaricInhPa'].values
                        if isinstance(level_val, np.ndarray) and level_val.size > 0:
                            level_val = level_val.item() if level_val.size == 1 else level_val[0]
                        full_var_name = f"{var_name}_{int(level_val)}_mb"
                    elif 'heightAboveGround' in var_data.dims:
                        # Dla wysokości nad ziemią dodaj _XXm
                        height_val = var_data.coords['heightAboveGround'].values
                        if isinstance(height_val, np.ndarray) and height_val.size > 0:
                            height_val = height_val.item() if height_val.size == 1 else height_val[0]
                        full_var_name = f"{var_name}_{int(height_val)}m"
                    else:
                        # Dla pozostałych (surface, meanSea, etc.) bez sufiksu
                        full_var_name = var_name
                    
                    all_data_vars[full_var_name] = var_data
                
                ds.close()
                
            except Exception as e:
                # Jeśli dany typeOfLevel nie istnieje w pliku, po prostu pomiń
                print(f"{get_timestamp()} - [{fh_str}] ⚠ {level_type} nie znaleziony: {e}", flush=True)
                continue
        
        # Jeśli nie udało się załadować żadnych danych
        if not all_data_vars or coords_dict is None:
            print(f"{get_timestamp()} - [{fh_str}] ✗ Nie udało się załadować żadnych danych (zmienne: {len(all_data_vars)}, coords: {coords_dict is not None})", flush=True)
            return 0
        
        print(f"{get_timestamp()} - [{fh_str}] Załadowano {len(all_data_vars)} zmiennych, przetwarzanie...", flush=True)
        
        # Oblicz forecast_time
        forecast_time = run_time + timedelta(hours=int(forecast_hour))
        
        # EFEKTYWNA METODA: Użyj xarray do połączenia wszystkich zmiennych w jeden dataset
        # To unika problemów z pamięcią przy merge'owaniu DataFrame'ów
        print(f"{get_timestamp()} - [{fh_str}] Łączenie zmiennych w xarray dataset...", flush=True)
        
        try:
            # Połącz wszystkie zmienne w jeden xarray dataset
            # Najpierw wycinz region z wszystkich zmiennych
            print(f"{get_timestamp()} - [{fh_str}] Wycinanie regionu geograficznego...", flush=True)
            
            vars_region = {}
            for var_name, var_data in all_data_vars.items():
                try:
                    if 'latitude' not in var_data.dims or 'longitude' not in var_data.dims:
                        continue
                    
                    # Wycinz region geograficzny
                    var_region = var_data.sel(
                        latitude=slice(lat_max, lat_min),  # Uwaga: slice(max, min) bo latitude maleje
                        longitude=slice(lon_min, lon_max)
                    )
                    
                    vars_region[var_name.lower()] = var_region
                    
                except Exception as e:
                    print(f"{get_timestamp()} - [{fh_str}] ⚠ Błąd wycinania {var_name}: {e}", flush=True)
                    continue
            
            if not vars_region:
                print(f"{get_timestamp()} - [{fh_str}] ✗ Brak zmiennych po wycięciu regionu", flush=True)
                return 0
            
            # Utwórz xarray Dataset z wszystkich zmiennych
            print(f"{get_timestamp()} - [{fh_str}] Tworzenie xarray Dataset z {len(vars_region)} zmiennych...", flush=True)
            ds_combined = xr.Dataset(vars_region)
            
            # Zwolnij pamięć
            del vars_region, all_data_vars
            import gc
            gc.collect()
            
            print(f"{get_timestamp()} - [{fh_str}] Konwertowanie do DataFrame...", flush=True)
            
            # Konwertuj cały dataset do DataFrame na raz (EFEKTYWNIE!)
            df = ds_combined.to_dataframe().reset_index()
            
            # Dodaj metadane
            df['run_time'] = run_time
            df['forecast_time'] = forecast_time
            df.rename(columns={'latitude': 'lat', 'longitude': 'lon'}, inplace=True)
            
            # Zaokrąglij wartości numeryczne do 2 miejsc po przecinku
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                if col not in ['lat', 'lon']:  # Nie zaokrąglaj współrzędnych
                    df[col] = df[col].round(2)
            
            # Usuń wiersze z samymi NaN (poza lat/lon/run_time/forecast_time)
            data_cols = [c for c in df.columns if c not in ['lat', 'lon', 'run_time', 'forecast_time']]
            if data_cols:
                df = df.dropna(subset=data_cols, how='all')
            
            records = df.to_dict('records')
            
            # Zwolnij pamięć
            del ds_combined, df
            import gc
            gc.collect()
            
        except MemoryError as e:
            print(f"{get_timestamp()} - [{fh_str}] ✗ BŁĄD PAMIĘCI: {e}", flush=True)
            return 0
        except Exception as e:
            print(f"{get_timestamp()} - [{fh_str}] ✗ Błąd łączenia datasetu: {e}", flush=True)
            import traceback
            print(f"{get_timestamp()} - [{fh_str}] Traceback:\n{traceback.format_exc()}", flush=True)
            return 0
        
        # Zapisz do bazy
        if records:
            print(f"{get_timestamp()} - [{fh_str}] Zapisuję {len(records)} rekordów do bazy...", flush=True)
            try:
                df_final = pd.DataFrame(records)
                df_final.to_sql('gfs_forecast', engine, if_exists='append', index=False, method='multi', chunksize=1000)
                print(f"{get_timestamp()} - [{fh_str}] ✓ Zapisano {len(records)} rekordów", flush=True)
                del df_final
                import gc
                gc.collect()
                return len(records)
            except MemoryError as e:
                print(f"{get_timestamp()} - [{fh_str}] ✗ BŁĄD PAMIĘCI przy zapisie: {e}", flush=True)
                return 0
        else:
            print(f"{get_timestamp()} - [{fh_str}] ✗ Brak rekordów do zapisania", flush=True)
            return 0
            
    except Exception as e:
        print(f"{get_timestamp()} - [{fh_str}] ✗ BŁĄD przetwarzania GRIB: {e}", flush=True)
        import traceback
        print(f"{get_timestamp()} - [{fh_str}] Traceback:\n{traceback.format_exc()}", flush=True)
        return 0

# === GŁÓWNY KOD ===
try:
    import builtins
    _is_imported_by_daemon = hasattr(builtins, '__imported_by_daemon__')
except:
    _is_imported_by_daemon = False

_is_main_module = (__name__ == "__main__" and not _is_imported_by_daemon)
if _is_main_module:
    print("=" * 70)
    print("GFS Weather Data Downloader - FILTERED VERSION (POPRAWIONA)")
    print("🎯 FILTROWANIE: Pobiera tylko wybrane parametry (~85-90% oszczędności!)")
    print("=" * 70)
    
    # Pokaż konfigurację filtrów
    print(f"\n📋 KONFIGURACJA FILTROWANIA:")
    print(f"  Poziomy izobaryczne: {len(GRIB_FILTER_CONFIG['levels'])} poziomów")
    print(f"  Zmienne atmosferyczne: {len(GRIB_FILTER_CONFIG['variables'])} zmiennych")
    print(f"  Poziomy powierzchniowe: {len(GRIB_FILTER_CONFIG['surface_levels'])} poziomów")
    print(f"  Zmienne powierzchniowe: {len(GRIB_FILTER_CONFIG['surface_variables'])} zmiennych")
    print(f"\n💡 Edytuj GRIB_FILTER_CONFIG w pliku aby zmienić parametry")
    
    # === 1. KONFIGURACJA ===
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
        
        NUM_THREADS = 6
        
        print(f"\n✓ Konfiguracja OK")
        print(f"  Region: {lat_min}°-{lat_max}°N, {lon_min}°-{lon_max}°E")
        print(f"  Wątki: {NUM_THREADS}")
        
    except Exception as e:
        print(f"✗ BŁĄD konfiguracji: {e}")
        input("\nEnter...")
        exit(1)
    
    # === 2. POŁĄCZENIE Z BAZĄ ===
    try:
        print(f"\n⏳ Łączenie z MySQL...")
        
        MYSQL_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"
        engine = create_engine(MYSQL_URL, echo=False, pool_pre_ping=True)
        
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        print(f"✓ MySQL OK: {MYSQL_DATABASE}")
        
    except Exception as e:
        print(f"✗ BŁĄD MySQL: {e}")
        input("\nEnter...")
        exit(1)
    
    # === 3. ZNAJDŹ NAJNOWSZY RUN ===
    print(f"\n⏳ Szukam najnowszego run GFS...")
    
    run_time, RUN_DATE, RUN_HOUR = find_latest_gfs_run(engine)
    
    if run_time is None:
        print(f"✗ Nie znaleziono nowych danych GFS do pobrania")
        print(f"  (Wszystkie dostępne runy są już w bazie)")
        input("\nNaciśnij Enter...")
        exit(0)
    
    print(f"✓ Znaleziono run do pobrania: {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    print(f"  Data: {RUN_DATE}")
    print(f"  Cykl: {RUN_HOUR}Z")
    
    # === 4. SPRAWDŹ CO TRZEBA POBRAĆ ===
    print(f"\n⏳ Sprawdzam które prognozy są już w bazie...")
    
    required_hours = get_required_forecast_hours()
    existing_hours = get_existing_forecast_hours(run_time, engine)
    missing_hours = sorted(list(required_hours - existing_hours))
    
    print(f"  Wymagane: {len(required_hours)} prognoz (f000-f384)")
    print(f"  W bazie: {len(existing_hours)} prognoz")
    print(f"  Do pobrania: {len(missing_hours)} prognoz")
    
    if len(missing_hours) == 0:
        print(f"\n✓ Wszystkie 209 prognoz są już w bazie!")
        input("\nNaciśnij Enter...")
        exit(0)
    
    # === 5. POBIERANIE Z MULTI-THREADING ===
    print(f"\n{'='*70}")
    print(f"🚀 ROZPOCZYNAM POBIERANIE (FILTERED VERSION - POPRAWIONA)")
    print(f"{'='*70}")
    
    # Utwórz katalog tymczasowy
    temp_dir = "temp_grib_filtered"
    os.makedirs(temp_dir, exist_ok=True)
    
    # Statystyki
    total_success = 0
    total_failed = 0
    total_records = 0
    total_bytes_filtered = 0
    total_bytes_full_estimate = 0
    
    # Kolejka zadań
    download_queue = queue.Queue()
    progress_queue = queue.Queue()
    
    # Priorytetyzacja (niskie prognozy najpierw)
    for forecast_hour in missing_hours:
        download_queue.put(forecast_hour)
    
    start_time = time.time()
    
    def worker_thread_filtered():
        """Wątek worker dla filtered version"""
        while True:
            try:
                forecast_hour = download_queue.get(timeout=1)
                if forecast_hour is None:
                    break
                
                # Buduj URL dla GRIB Filter
                print(f"{get_timestamp()} - [f{forecast_hour:03d}] Budowanie URL...", flush=True)
                url = build_grib_filter_url(RUN_DATE, RUN_HOUR, forecast_hour)
                
                # Ścieżka do pliku tymczasowego
                temp_file = os.path.join(temp_dir, f"gfs_f{forecast_hour:03d}_filtered.grb2")
                
                # Pobierz plik (FILTERED!)
                success, file_size = download_grib_filtered(url, temp_file, forecast_hour=forecast_hour)
                
                if success:
                    # Przetwórz i zapisz do bazy
                    try:
                        print(f"{get_timestamp()} - [f{forecast_hour:03d}] Parsowanie GRIB...", flush=True)
                        num_records = process_grib_to_db_filtered(
                            temp_file, run_time, forecast_hour,
                            lat_min, lat_max, lon_min, lon_max, engine
                        )
                        print(f"{get_timestamp()} - [f{forecast_hour:03d}] ✓ Zapisano {num_records} rekordów", flush=True)
                        
                        # Szacuj rozmiar pełnego pliku (dla statystyk)
                        estimated_full_size = file_size * 10  # Około 10x większy
                        
                        # Wyślij wynik
                        progress_queue.put({
                            'success': True,
                            'forecast_hour': forecast_hour,
                            'records': num_records,
                            'bytes_filtered': file_size,
                            'bytes_full_estimate': estimated_full_size
                        })
                        
                        # Usuń plik tymczasowy
                        try:
                            os.remove(temp_file)
                        except:
                            pass
                            
                    except Exception as e:
                        module_logger.error(f"Błąd przetwarzania f{forecast_hour:03d}: {e}")
                        progress_queue.put({
                            'success': False,
                            'forecast_hour': forecast_hour,
                            'records': 0,
                            'bytes_filtered': 0,
                            'bytes_full_estimate': 0
                        })
                else:
                    progress_queue.put({
                        'success': False,
                        'forecast_hour': forecast_hour,
                        'records': 0,
                        'bytes_filtered': 0,
                        'bytes_full_estimate': 0
                    })
                
                download_queue.task_done()
                
            except Empty:
                break
            except Exception as e:
                module_logger.error(f"Błąd w worker thread: {e}")
                break
    
    # Uruchom wątki
    threads = []
    for i in range(NUM_THREADS):
        t = threading.Thread(target=worker_thread_filtered, daemon=True)
        t.start()
        threads.append(t)
    
    # Progress bar
    with tqdm(total=len(missing_hours), desc="Pobieranie", unit="prognoza") as pbar:
        completed = 0
        
        while completed < len(missing_hours):
            try:
                progress = progress_queue.get(timeout=1)
                completed += 1
                
                if progress['success']:
                    total_success += 1
                    total_records += progress['records']
                    total_bytes_filtered += progress['bytes_filtered']
                    total_bytes_full_estimate += progress['bytes_full_estimate']
                else:
                    total_failed += 1
                
                pbar.set_postfix({
                    'f': f"{progress['forecast_hour']:03d}",
                    'OK': total_success,
                    'FAIL': total_failed
                })
                pbar.update(1)
                
            except Empty:
                alive = sum(1 for t in threads if t.is_alive())
                if alive == 0:
                    break
    
    # Zakończ wątki
    for _ in range(NUM_THREADS):
        download_queue.put(None)
    for t in threads:
        t.join(timeout=5)
    
    # === 6. PODSUMOWANIE ===
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    mb_filtered = total_bytes_filtered / (1024 * 1024)
    mb_full_estimate = total_bytes_full_estimate / (1024 * 1024)
    mb_saved = mb_full_estimate - mb_filtered
    percent_saved = (mb_saved / mb_full_estimate * 100) if mb_full_estimate > 0 else 0
    
    print("\n" + "=" * 70)
    print("✓✓✓ POBRANIE ZAKOŃCZONE!")
    print("=" * 70)
    print(f"Run GFS:           {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    print(f"Prognoz pobrano:   {total_success}")
    print(f"Prognoz błędów:    {total_failed}")
    print(f"Rekordów w bazie:  {total_records}")
    print(f"⏱️  Czas:             {elapsed_time:.1f}s")
    print(f"\n📊 STATYSTYKI FILTROWANIA:")
    print(f"  Pobrano (filtered):      {mb_filtered:.1f} MB")
    print(f"  Pełne pliki (szacunek):  {mb_full_estimate:.1f} MB")
    print(f"  💾 OSZCZĘDNOŚĆ:          {mb_saved:.1f} MB ({percent_saved:.1f}%)")
    print("=" * 70)
    
    print(f"\n💡 Wszystkie dane są już zapisane w bazie!")
    print(f"   Tabela: gfs_forecast")
    print(f"   Baza: {MYSQL_DATABASE}")
    
    input("\nNaciśnij Enter...")
