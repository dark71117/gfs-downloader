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
from urllib.parse import urlencode, urlparse, parse_qs, unquote
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

def load_parameters_config(config_file='config.ini'):
    """
    Wczytuje konfigurację parametrów z config.ini.
    Zwraca słownik mapujący: config_name -> {db_column, level_type, level_value, transformation}
    oraz mapowanie cfgrib_name -> config_name
    """
    try:
        config = configparser.ConfigParser()
        config.read(config_file, encoding='utf-8')
        
        params_map = {}
        cfgrib_to_config = {}  # Mapowanie nazw cfgrib na nazwy z konfiguracji
        
        if 'gfs_parameters' in config:
            print(f"DEBUG load_parameters_config: Znaleziono sekcję [gfs_parameters] z {len(config['gfs_parameters'])} parametrami", flush=True)
            for config_name, value in config['gfs_parameters'].items():
                parts = [p.strip() for p in value.split(',')]
                if len(parts) == 4:
                    db_column, level_type, level_value, transformation = parts
                    params_map[config_name] = {
                        'db_column': db_column,
                        'level_type': level_type,
                        'level_value': int(level_value) if level_value.isdigit() else level_value,
                        'transformation': transformation
                    }
                    
                    # Mapowanie nazw cfgrib na nazwy z konfiguracji
                    # cfgrib używa małych liter i innych nazw niż NOMADS
                    cfgrib_name = None
                    if config_name == 't2m':
                        cfgrib_name = 't2m'
                    elif config_name == 'd2m':
                        cfgrib_name = 'd2m'
                    elif config_name == 'r2':
                        cfgrib_name = 'r2'
                    elif config_name == 'u10':
                        cfgrib_name = 'u10'
                    elif config_name == 'v10':
                        cfgrib_name = 'v10'
                    elif config_name == 'u80':
                        cfgrib_name = 'u'
                    elif config_name == 'v80':
                        cfgrib_name = 'v'
                    elif config_name == 't80':
                        cfgrib_name = 't'
                    elif config_name == 'gust':
                        cfgrib_name = 'gust'
                    elif config_name == 'prmsl':
                        cfgrib_name = 'prmsl'
                    elif config_name == 'tp':
                        cfgrib_name = 'tp'
                    elif config_name == 'prate':
                        cfgrib_name = 'prate'
                    elif config_name == 'tcc':
                        cfgrib_name = 'tcc'
                    elif config_name == 'lcc':
                        cfgrib_name = 'lcc'
                    elif config_name == 'mcc':
                        cfgrib_name = 'mcc'
                    elif config_name == 'hcc':
                        cfgrib_name = 'hcc'
                    elif config_name == 'vis':
                        cfgrib_name = 'vis'
                    elif config_name == 'dswrf':
                        cfgrib_name = 'dswrf'
                    elif config_name == 'cape':
                        cfgrib_name = 'cape'
                    elif config_name == 'cin':
                        cfgrib_name = 'cin'
                    elif config_name == 'pwat':
                        cfgrib_name = 'pwat'
                    elif config_name == 't_850':
                        cfgrib_name = 't'
                    elif config_name == 'gh_850':
                        cfgrib_name = 'gh'
                    elif config_name == 'gh_500':
                        cfgrib_name = 'gh'
                    else:
                        # Jeśli parametr nie jest w mapowaniu, użyj nazwy z config jako cfgrib_name
                        print(f"DEBUG load_parameters_config: ⚠ Parametr '{config_name}' nie ma mapowania cfgrib_name - używam '{config_name}' jako cfgrib_name", flush=True)
                        cfgrib_name = config_name
                    
                    if cfgrib_name:
                        # Dla zmiennych z poziomami, dodaj poziom do klucza
                        if level_type == 'isobaricInhPa' and isinstance(params_map[config_name]['level_value'], int):
                            key = (cfgrib_name, level_type, params_map[config_name]['level_value'])
                        elif level_type == 'heightAboveGround' and isinstance(params_map[config_name]['level_value'], int):
                            key = (cfgrib_name, level_type, params_map[config_name]['level_value'])
                        else:
                            key = (cfgrib_name, level_type, 0)
                        
                        cfgrib_to_config[key] = config_name
                        print(f"DEBUG load_parameters_config: Dodano mapowanie {key} -> {config_name} (db_column={params_map[config_name]['db_column']})", flush=True)
        
        print(f"DEBUG load_parameters_config: Utworzono {len(cfgrib_to_config)} mapowań cfgrib_to_config", flush=True)
        return params_map, cfgrib_to_config
    except Exception as e:
        module_logger.warning(f"Nie udało się wczytać konfiguracji parametrów z {config_file}: {e}")
        return {}, {}

def apply_transformation(data, transformation):
    """
    Stosuje transformację do danych.
    transformation: none, kelvin_to_celsius, pa_to_hpa, fraction_to_percent
    """
    if transformation == 'none':
        return data
    elif transformation == 'kelvin_to_celsius':
        return data - 273.15
    elif transformation == 'pa_to_hpa':
        return data / 100.0
    elif transformation == 'fraction_to_percent':
        # Sprawdź czy wartości są w zakresie 0-1
        try:
            max_val = float(data.max().values)
            if max_val <= 1.0:
                return data * 100.0
        except:
            pass
        return data
    else:
        return data

def build_grib_filter_url(date_str, hour_str, forecast_hour, resolution='0p25', params_config=None):
    """
    Buduje URL dla GRIB Filter API z wybranymi parametrami z konfiguracji.
    Format zgodny z dokumentacją NOMADS: https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs.pl
    """
    # Base URL - używa filter_gfs.pl (nie filter_gfs_0p25.pl)
    base_url = f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs.pl"
    
    # Wczytaj konfigurację parametrów jeśli nie podano
    if params_config is None:
        params_config, _ = load_parameters_config()
    
    # Parametry URL
    params = {
        'file': f'gfs.t{hour_str}z.pgrb2.{resolution}.f{forecast_hour:03d}',
        'dir': f'/gfs.{date_str}/{hour_str}/atmos',
    }
    
    # Jeśli mamy konfigurację parametrów, użyj jej
    if params_config:
        # Mapowanie nazw GRIB na nazwy w API NOMADS
        grib_to_nomads = {
            't2m': 'TMP',
            'd2m': 'DPT',
            'r2': 'RH',
            'u10': 'UGRD',
            'v10': 'VGRD',
            'u80': 'UGRD',
            'v80': 'VGRD',
            't80': 'TMP',
            'gust': 'GUST',
            'prmsl': 'PRMSL',
            'tp': 'APCP',
            'prate': 'PRATE',
            'tcc': 'TCDC',
            'lcc': 'LCDC',
            'mcc': 'MCDC',
            'hcc': 'HCDC',
            'vis': 'VIS',
            'dswrf': 'DSWRF',
            'cape': 'CAPE',
            'cin': 'CIN',
            'pwat': 'PWAT',
            't_850': 'TMP',
            'gh_850': 'HGT',
            'gh_500': 'HGT',
        }
        
        # Zbierz unikalne kombinacje var+level
        var_level_combos = set()
        
        for grib_name, config_data in params_config.items():
            level_type = config_data['level_type']
            level_value = config_data['level_value']
            nomads_var = grib_to_nomads.get(grib_name, grib_name.upper())
            
            # Buduj klucz dla poziomu (format NOMADS)
            if level_type == 'isobaricInhPa' and isinstance(level_value, int):
                level_key = f'lev_{level_value}_mb'
            elif level_type == 'heightAboveGround' and isinstance(level_value, int):
                level_key = f'lev_{level_value}_m'
            elif level_type == 'surface':
                level_key = 'lev_surface'
            elif level_type == 'meanSea':
                level_key = 'lev_mean_sea_level'
            elif level_type == 'entireAtmosphere':
                level_key = 'lev_entire_atmosphere'
            else:
                continue  # Pomiń nieznane typy poziomów
            
            var_level_combos.add((nomads_var, level_key))
        
        # Dodaj parametry do URL (NOMADS wymaga var_ i lev_ osobno)
        for nomads_var, level_key in var_level_combos:
            params[f'var_{nomads_var}'] = 'on'
            params[level_key] = 'on'
    else:
        # Fallback: użyj starej konfiguracji GRIB_FILTER_CONFIG
        # Dodaj poziomy izobaryczne (uproszczone nazwy)
        for level in GRIB_FILTER_CONFIG['levels']:
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
    
    # Buduj URL
    url = f"{base_url}?{urlencode(params)}"
    
    # Loguj URL dla debugowania (tylko pierwsze 500 znaków)
    if forecast_hour is not None and forecast_hour <= 1:
        print(f"{get_timestamp()} - [f{forecast_hour:03d}] DEBUG GRIB Filter URL ({len(url)} znaków): {url[:500]}...", flush=True)
    
    # Sprawdź długość URL
    if len(url) > 2000:
        print(f"{get_timestamp()} - ⚠️ UWAGA: URL jest bardzo długi ({len(url)} znaków) - może powodować problemy!", flush=True)
        print(f"{get_timestamp()} - URL (pierwsze 200 znaków): {url[:200]}...", flush=True)
    
    return url

def get_timestamp():
    """Zwraca timestamp w formacie YYYY-MM-DD HH:MM:SS"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def download_grib_filtered(url_or_date_str, output_path, max_retries=3, forecast_hour=None, hour_str=None, resolution='0p25', params_config=None):
    """
    Pobiera plik GRIB używając GRIB Filter API (z filtrowaniem na serwerze).
    Może przyjąć URL (string) lub date_str (wtedy buduje URL).
    Zwraca (success, file_size_bytes).
    """
    # Jeśli pierwszy parametr to URL (zawiera 'http'), użyj go bezpośrednio
    date_str = None
    if isinstance(url_or_date_str, str) and url_or_date_str.startswith('http'):
        url = url_or_date_str
        # Spróbuj wyciągnąć date_str i hour_str z URL dla fallback
        # URL format Filter API: ...?dir=%2Fgfs.20251120%2F12%2Fatmos&file=...
        # Lub bezpośredni URL: .../gfs.{date_str}/{hour_str}/atmos/...
        import re
        
        # Najpierw spróbuj z query string (Filter API)
        parsed = urlparse(url_or_date_str)
        query_params = parse_qs(parsed.query)
        if 'dir' in query_params:
            dir_param = unquote(query_params['dir'][0])
            match = re.search(r'/gfs\.(\d{8})/(\d{2})/atmos', dir_param)
            if match:
                date_str = match.group(1)
                if hour_str is None:
                    hour_str = match.group(2)
        
        # Jeśli nie znaleziono w query string, spróbuj z path
        if not date_str:
            match = re.search(r'/gfs\.(\d{8})/(\d{2})/atmos/', url_or_date_str)
            if match:
                date_str = match.group(1)
                if hour_str is None:
                    hour_str = match.group(2)
    else:
        # W przeciwnym razie, zbuduj URL z parametrów
        date_str = url_or_date_str
        if hour_str is None:
            raise ValueError("hour_str jest wymagany gdy podano date_str")
        url = build_grib_filter_url(date_str, hour_str, forecast_hour, resolution, params_config)
    
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
                print(f"{get_timestamp()} - [{fh_str}] ✗ HTTP {response.status_code} z GRIB Filter API", flush=True)
                
                # FALLBACK: Jeśli Filter API zwraca 404, spróbuj bezpośredniego pobierania
                if response.status_code == 404 and forecast_hour is not None:
                    # Jeśli nie mamy date_str i hour_str, spróbuj wyciągnąć z URL jeszcze raz
                    if not date_str or not hour_str:
                        import re
                        parsed = urlparse(url)
                        query_params = parse_qs(parsed.query)
                        if 'dir' in query_params:
                            dir_param = unquote(query_params['dir'][0])
                            match = re.search(r'/gfs\.(\d{8})/(\d{2})/atmos', dir_param)
                            if match:
                                date_str = match.group(1)
                                hour_str = match.group(2)
                    
                    if date_str and hour_str:
                        # Pobierz bezpośrednio plik GRIB (bez filtrowania)
                        direct_url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{resolution}.f{forecast_hour:03d}"
                        print(f"{get_timestamp()} - [{fh_str}] ⚠️ Filter API zwraca 404, próbuję bezpośredniego pobierania z {direct_url}...", flush=True)
                    wait_for_rate_limit()
                    response = requests.get(direct_url, timeout=300, stream=True)
                    if response.status_code == 200:
                        print(f"{get_timestamp()} - [{fh_str}] ✓ Bezpośrednie pobieranie działa, kontynuuję...", flush=True)
                        # Kontynuuj z bezpośrednim pobieraniem (plik będzie większy, ale działa)
                    else:
                        print(f"{get_timestamp()} - [{fh_str}] ✗ Bezpośrednie pobieranie też zwraca {response.status_code}", flush=True)
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                            continue
                        return False, 0
                else:
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
    Używa bezpośredniego URL do pliku .idx (index file) zamiast GRIB Filter API,
    bo Filter API może zwracać 404 nawet jeśli plik istnieje.
    """
    # Sprawdź dostępność pliku .idx (index file) - jest zawsze dostępny jeśli plik GRIB istnieje
    base_path = f"/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p25.f{forecast_hour:03d}"
    idx_url = f"https://nomads.ncep.noaa.gov{base_path}.idx"
    
    # Alternatywnie sprawdź bezpośredni URL do pliku GRIB
    grib_url = f"https://nomads.ncep.noaa.gov{base_path}"
    
    try:
        wait_for_rate_limit()
        # Najpierw sprawdź plik .idx (szybszy i bardziej niezawodny)
        response = requests.head(idx_url, timeout=10, allow_redirects=True)
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            if verbose:
                module_logger.debug(f"HTTP 429 - czekam {retry_after}s")
            time.sleep(retry_after)
            wait_for_rate_limit()
            response = requests.head(idx_url, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            if verbose:
                module_logger.debug(f"✓ Dane dostępne (f{forecast_hour:03d}) - plik .idx istnieje")
            return True
        
        # Jeśli .idx nie istnieje, sprawdź bezpośrednio plik GRIB
        if response.status_code == 404:
            wait_for_rate_limit()
            response = requests.head(grib_url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                if verbose:
                    module_logger.debug(f"✓ Dane dostępne (f{forecast_hour:03d}) - plik GRIB istnieje")
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

def process_grib_to_db_filtered(grib_path, run_time, forecast_hour, lat_min, lat_max, lon_min, lon_max, engine, params_config=None, cfgrib_to_config=None, csv_backup_dir=None):
    """
    Przetwarza plik GRIB (pofiltrowany) i zapisuje do bazy danych.
    Używa konfiguracji parametrów z config.ini - tylko parametry zdefiniowane w konfiguracji są przetwarzane!
    
    POPRAWKA: Otwiera plik dla KAŻDEGO typeOfLevel osobno,
    ponieważ xarray/cfgrib nie może otworzyć wszystkich poziomów naraz.
    """
    fh_str = f"f{forecast_hour:03d}"
    
    # Wczytaj konfigurację jeśli nie podano
    if params_config is None or cfgrib_to_config is None:
        params_config, cfgrib_to_config = load_parameters_config()
    
    # DEBUG: Pokaż mapowanie
    print(f"{get_timestamp()} - [{fh_str}] DEBUG: Załadowano {len(params_config)} parametrów z konfiguracji", flush=True)
    print(f"{get_timestamp()} - [{fh_str}] DEBUG: Mapowanie cfgrib_to_config ma {len(cfgrib_to_config)} kluczy", flush=True)
    if cfgrib_to_config:
        print(f"{get_timestamp()} - [{fh_str}] DEBUG: Wszystkie klucze w cfgrib_to_config:", flush=True)
        for key, config_name in cfgrib_to_config.items():
            db_col = params_config.get(config_name, {}).get('db_column', '?')
            print(f"{get_timestamp()} - [{fh_str}]   {key} -> {config_name} (db_column={db_col})", flush=True)
    
    if not params_config:
        print(f"{get_timestamp()} - [{fh_str}] ⚠ Brak konfiguracji parametrów - używam domyślnych", flush=True)
    
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
        
        all_data_vars = {}
        coords_dict = None
        
        # Lista poziomów do otwarcia - dla heightAboveGround otwieramy każdy poziom osobno
        # Najpierw sprawdź jakie poziomy heightAboveGround są w konfiguracji
        height_levels = []
        isobaric_levels = []
        if params_config:
            for config_name, param_info in params_config.items():
                level_type = param_info.get('level_type')
                level_value = param_info.get('level_value')
                if level_type == 'heightAboveGround' and isinstance(level_value, int):
                    if level_value not in height_levels:
                        height_levels.append(level_value)
                elif level_type == 'isobaricInhPa' and isinstance(level_value, int):
                    if level_value not in isobaric_levels:
                        isobaric_levels.append(level_value)
        
        # Lista typów poziomów, które mogą być w pliku
        type_of_levels = [
            ('isobaricInhPa', None),        # Poziomy izobaryczne (będą filtrowane po konkretnych poziomach)
            ('surface', None),              # Powierzchnia
            ('meanSea', None),              # Poziom morza
            ('tropopause', None),           # Tropopauza
            ('maxWind', None),              # Maksymalny poziom wiatru
            ('entireAtmosphere', None),     # Cała atmosfera
        ]
        
        # Dodaj heightAboveGround dla każdego poziomu osobno
        for height in height_levels:
            type_of_levels.append(('heightAboveGround', height))
        
        # Otwórz plik dla każdego typeOfLevel osobno
        for level_type, level_value in type_of_levels:
            try:
                if level_type == 'heightAboveGround' and level_value is not None:
                    print(f"{get_timestamp()} - [{fh_str}] Próbuję otworzyć level: {level_type} (height={level_value}m)...", flush=True)
                    filter_keys = {'typeOfLevel': level_type, 'level': level_value, 'stepType': 'instant'}
                elif level_type == 'isobaricInhPa' and isobaric_levels:
                    # Dla isobaricInhPa, otwieramy każdy poziom osobno
                    # Przetwarzamy je w pętli poniżej
                    continue
                else:
                    print(f"{get_timestamp()} - [{fh_str}] Próbuję otworzyć level: {level_type}...", flush=True)
                    filter_keys = {'typeOfLevel': level_type}
                    if level_type == 'surface':
                        filter_keys['stepType'] = 'instant'
                
                try:
                    ds = xr.open_dataset(
                        grib_path,
                        engine='cfgrib',
                        backend_kwargs={
                            'filter_by_keys': filter_keys,
                            'indexpath': '',
                            'errors': 'ignore'
                        }
                    )
                except Exception as e:
                    # Jeśli nie udało się z stepType='instant', spróbuj bez stepType
                    if level_type == 'surface':
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Nie udało się z stepType='instant', próbuję bez stepType...", flush=True)
                        filter_keys_no_step = {'typeOfLevel': level_type}
                        ds = xr.open_dataset(
                            grib_path,
                            engine='cfgrib',
                            backend_kwargs={
                                'filter_by_keys': filter_keys_no_step,
                                'indexpath': '',
                                'errors': 'ignore'
                            }
                        )
                    elif level_type == 'heightAboveGround' and level_value is not None:
                        # Spróbuj bez stepType
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Nie udało się z stepType='instant', próbuję bez stepType...", flush=True)
                        filter_keys_no_step = {'typeOfLevel': level_type, 'level': level_value}
                        ds = xr.open_dataset(
                            grib_path,
                            engine='cfgrib',
                            backend_kwargs={
                                'filter_by_keys': filter_keys_no_step,
                                'indexpath': '',
                                'errors': 'ignore'
                            }
                        )
                    else:
                        raise
                
                # Otwórz isobaricInhPa dla każdego poziomu osobno
                if level_type == 'isobaricInhPa' and isobaric_levels:
                    for isobaric_level in isobaric_levels:
                        try:
                            print(f"{get_timestamp()} - [{fh_str}] Próbuję otworzyć level: {level_type} ({isobaric_level} mb)...", flush=True)
                            filter_keys_iso = {'typeOfLevel': 'isobaricInhPa', 'level': isobaric_level}
                            ds_iso = xr.open_dataset(
                                grib_path,
                                engine='cfgrib',
                                backend_kwargs={
                                    'filter_by_keys': filter_keys_iso,
                                    'indexpath': '',
                                    'errors': 'ignore'
                                }
                            )
                            print(f"{get_timestamp()} - [{fh_str}] ✓ Otworzono {level_type} {isobaric_level} mb, zmienne: {list(ds_iso.data_vars.keys())}", flush=True)
                            
                            # Zapisz współrzędne (latitude, longitude) z pierwszego datasetu
                            if coords_dict is None:
                                coords_dict = {
                                    'latitude': ds_iso.latitude.values,
                                    'longitude': ds_iso.longitude.values
                                }
                            
                            # Przetwarzaj zmienne dla tego poziomu izobarycznego
                            print(f"{get_timestamp()} - [{fh_str}] DEBUG: Zmienne w {level_type} {isobaric_level} mb: {list(ds_iso.data_vars.keys())}", flush=True)
                            for var_name in ds_iso.data_vars:
                                var_data = ds_iso[var_name]
                                var_level_type = 'isobaricInhPa'
                                level_val = isobaric_level  # Użyj poziomu z filtra
                                
                                # Przetwarzaj zmienną (użyj tego samego kodu co poniżej)
                                # Sprawdź czy ta zmienna jest w konfiguracji
                                config_name = None
                                db_column = None
                                transformation = None
                                
                                key = (var_name, var_level_type, level_val)
                                print(f"{get_timestamp()} - [{fh_str}] DEBUG: Sprawdzam klucz dla isobaric: {key}", flush=True)
                                if key in cfgrib_to_config:
                                    config_name = cfgrib_to_config[key]
                                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: ✓ Znaleziono mapowanie: {key} -> {config_name}", flush=True)
                                    if config_name in params_config:
                                        db_column = params_config[config_name]['db_column']
                                        transformation = params_config[config_name]['transformation']
                                
                                if params_config and (not config_name or not db_column):
                                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: Pomijam {var_name} (key: {key}) - nie znaleziono w cfgrib_to_config", flush=True)
                                    continue
                                
                                # Zapisz zmienną
                                all_data_vars[db_column] = {
                                    'data': var_data,
                                    'transformation': transformation,
                                    'config_name': config_name
                                }
                            
                            ds_iso.close()
                        except Exception as e:
                            print(f"{get_timestamp()} - [{fh_str}] ⚠ {level_type} {isobaric_level} mb nie znaleziony: {e}", flush=True)
                            continue
                    continue  # Przejdź do następnego poziomu
                
                print(f"{get_timestamp()} - [{fh_str}] ✓ Otworzono {level_type}, zmienne: {list(ds.data_vars.keys())}", flush=True)
                
                # Zapisz współrzędne (latitude, longitude) z pierwszego datasetu
                if coords_dict is None:
                    coords_dict = {
                        'latitude': ds.latitude.values,
                        'longitude': ds.longitude.values
                    }
                
                # Zbierz wszystkie zmienne z tego poziomu - TYLKO TE Z KONFIGURACJI!
                print(f"{get_timestamp()} - [{fh_str}] DEBUG: Zmienne w {level_type}: {list(ds.data_vars.keys())}", flush=True)
                for var_name in ds.data_vars:
                    var_data = ds[var_name]
                    
                    # Określ poziom zmiennej
                    var_level_type = level_type
                    # Dla heightAboveGround z konkretnym poziomem, użyj tego poziomu (nie nadpisuj!)
                    if level_type == 'heightAboveGround' and level_value is not None:
                        level_val = level_value
                    else:
                        # Wyznacz level_val z danych
                        if 'isobaricInhPa' in var_data.dims:
                            level_vals = var_data.coords['isobaricInhPa'].values
                            if isinstance(level_vals, np.ndarray) and level_vals.size > 0:
                                if level_vals.size == 1:
                                    level_val = int(level_vals.item())
                                else:
                                    # Jeśli jest wiele poziomów, sprawdź każdy
                                    level_vals = [int(v) for v in level_vals]
                                    level_val = level_vals  # Lista poziomów
                                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: {var_name} ma wiele poziomów isobaricInhPa: {level_vals}", flush=True)
                        elif 'heightAboveGround' in var_data.dims:
                            height_vals = var_data.coords['heightAboveGround'].values
                            if isinstance(height_vals, np.ndarray) and height_vals.size > 0:
                                if height_vals.size == 1:
                                    level_val = int(height_vals.item())
                                else:
                                    height_vals = [int(v) for v in height_vals]
                                    level_val = height_vals  # Lista poziomów
                                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: {var_name} ma wiele poziomów heightAboveGround: {height_vals}", flush=True)
                        else:
                            level_val = 0  # surface, meanSea, etc.
                    
                    # DEBUG: Pokaż szczegóły zmiennej
                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: Przetwarzam {var_name}, level_type={var_level_type}, level_val={level_val}", flush=True)
                    
                    # Sprawdź czy ta zmienna jest w konfiguracji
                    # Szukaj w cfgrib_to_config: (cfgrib_name, level_type, level_value) -> config_name
                    config_name = None
                    db_column = None
                    transformation = None
                    
                    if isinstance(level_val, list):
                        # Wiele poziomów - sprawdź każdy
                        for lv in level_val:
                            key = (var_name, var_level_type, lv)
                            print(f"{get_timestamp()} - [{fh_str}] DEBUG: Sprawdzam klucz dla wielu poziomów: {key}", flush=True)
                            if key in cfgrib_to_config:
                                config_name = cfgrib_to_config[key]
                                print(f"{get_timestamp()} - [{fh_str}] DEBUG: ✓ Znaleziono mapowanie: {key} -> {config_name}", flush=True)
                                if config_name in params_config:
                                    db_column = params_config[config_name]['db_column']
                                    transformation = params_config[config_name]['transformation']
                                    level_val = lv  # Użyj tego poziomu
                                    break
                    else:
                        # Jeden poziom
                        key = (var_name, var_level_type, level_val if level_val is not None else 0)
                        print(f"{get_timestamp()} - [{fh_str}] DEBUG: Sprawdzam klucz dla jednego poziomu: {key}", flush=True)
                        if key in cfgrib_to_config:
                            config_name = cfgrib_to_config[key]
                            print(f"{get_timestamp()} - [{fh_str}] DEBUG: ✓ Znaleziono mapowanie: {key} -> {config_name}", flush=True)
                            if config_name in params_config:
                                db_column = params_config[config_name]['db_column']
                                transformation = params_config[config_name]['transformation']
                    
                    # Jeśli zmienna nie jest w konfiguracji, pomiń ją (chyba że brak konfiguracji - wtedy użyj domyślnych)
                    if params_config and (not config_name or not db_column):
                        # DEBUG: Sprawdź dlaczego nie znaleziono mapowania
                        if isinstance(level_val, list):
                            debug_key = (var_name, var_level_type, level_val[0] if level_val else 0)
                        else:
                            debug_key = (var_name, var_level_type, level_val if level_val is not None else 0)
                        # Sprawdź czy może być problem z typem level_val
                        if level_val is None:
                            debug_key_alt = (var_name, var_level_type, 0)
                            if debug_key_alt in cfgrib_to_config:
                                print(f"{get_timestamp()} - [{fh_str}] DEBUG: Znaleziono alternatywny klucz {debug_key_alt} dla {var_name}", flush=True)
                                config_name = cfgrib_to_config[debug_key_alt]
                                if config_name in params_config:
                                    db_column = params_config[config_name]['db_column']
                                    transformation = params_config[config_name]['transformation']
                                    level_val = 0
                        if not config_name or not db_column:
                            print(f"{get_timestamp()} - [{fh_str}] DEBUG: Pomijam {var_name} (key: {debug_key}) - nie znaleziono w cfgrib_to_config", flush=True)
                            # DEBUG: Pokaż podobne klucze w cfgrib_to_config
                            similar_keys = [k for k in cfgrib_to_config.keys() if k[0] == var_name or k[1] == var_level_type]
                            if similar_keys:
                                print(f"{get_timestamp()} - [{fh_str}] DEBUG: Podobne klucze w cfgrib_to_config: {similar_keys[:5]}", flush=True)
                            continue
                    
                    # Jeśli jest wiele poziomów, wybierz tylko ten z konfiguracji
                    if isinstance(level_val, list):
                        # Wybierz tylko poziom z konfiguracji
                        if var_level_type == 'isobaricInhPa':
                            var_data = var_data.sel(isobaricInhPa=level_val)
                        elif var_level_type == 'heightAboveGround':
                            var_data = var_data.sel(heightAboveGround=level_val)
                    
                    # Walidacja poziomu
                    if level_val is not None:
                        if var_level_type == 'isobaricInhPa':
                            if level_val in [999, 995, 996, 997, 998] or level_val == 0:
                                continue
                        elif var_level_type == 'heightAboveGround':
                            if level_val in [0, 999, 995, 996, 997, 998]:
                                continue
                    
                    # Jeśli brak konfiguracji, użyj domyślnej nazwy z sufiksem
                    if not params_config or not db_column:
                        # Fallback: dodaj sufiks z poziomem do nazwy zmiennej
                        if 'isobaricInhPa' in var_data.dims:
                            level_val_float = float(level_val) if level_val is not None else 0
                            full_var_name = f"{var_name}_{int(level_val_float)}_mb"
                        elif 'heightAboveGround' in var_data.dims:
                            level_val_float = float(level_val) if level_val is not None else 0
                            full_var_name = f"{var_name}_{int(level_val_float)}m"
                        else:
                            full_var_name = var_name
                        db_column = full_var_name
                        transformation = 'none'
                    
                    # Zapisz zmienną z nazwą kolumny bazy jako klucz
                    all_data_vars[db_column] = {
                        'data': var_data,
                        'transformation': transformation,
                        'config_name': config_name
                    }
                
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
            for db_column, var_info in all_data_vars.items():
                try:
                    var_data = var_info['data']
                    transformation = var_info['transformation']
                    config_name = var_info['config_name']
                    
                    if 'latitude' not in var_data.dims or 'longitude' not in var_data.dims:
                        continue
                    
                    # Wycinz region geograficzny
                    var_region = var_data.sel(
                        latitude=slice(lat_max, lat_min),  # Uwaga: slice(max, min) bo latitude maleje
                        longitude=slice(lon_min, lon_max)
                    )
                    
                    # TRANSFORMACJE DANYCH - używamy transformacji z konfiguracji!
                    var_region = apply_transformation(var_region, transformation)
                    if transformation != 'none':
                        print(f"{get_timestamp()} - [{fh_str}] Transformacja: {config_name} -> {db_column} ({transformation})", flush=True)
                    
                    # Zapisz z nazwą kolumny bazy jako klucz
                    vars_region[db_column] = var_region
                    
                except Exception as e:
                    print(f"{get_timestamp()} - [{fh_str}] ⚠ Błąd wycinania {db_column}: {e}", flush=True)
                    continue
            
            if not vars_region:
                print(f"{get_timestamp()} - [{fh_str}] ✗ Brak zmiennych po wycięciu regionu", flush=True)
                return 0
            
            # KONWERSJA: Konwertuj każdą zmienną osobno i łącz przez merge (jak w professional version)
            # To unika problemów z MultiIndex i sufiksami _m0, _m1, etc.
            print(f"{get_timestamp()} - [{fh_str}] Konwertowanie {len(vars_region)} zmiennych do DataFrame...", flush=True)
            
            df = None
            coords = ['latitude', 'longitude']  # Wspólne współrzędne
            
            for db_column, var_data in vars_region.items():
                try:
                    # Sprawdź wymiary zmiennej - jeśli ma więcej niż 2 wymiary (lat, lon), może być problem
                    dims = var_data.dims
                    dim_sizes = {dim: var_data.sizes[dim] for dim in dims}
                    
                    # Sprawdź czy zmienna nie ma zbyt wielu wymiarów (może mieć wszystkie poziomy)
                    total_size = 1
                    for size in dim_sizes.values():
                        total_size *= size
                    
                    # Jeśli zmienna jest zbyt duża (> 100M elementów), pomiń lub wybierz tylko jeden poziom
                    if total_size > 100_000_000:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Pomijam {db_column} - zbyt duża ({total_size:,} elementów, wymiary: {dim_sizes})", flush=True)
                        continue
                    
                    # Jeśli zmienna ma wymiar isobaricInhPa lub heightAboveGround z wieloma wartościami,
                    # wybierz tylko pierwszą wartość (powinna być już wyfiltrowana, ale sprawdźmy)
                    # UWAGA: Po wyfiltrowaniu przez filter_by_keys, wymiar może już nie istnieć, więc sprawdź czy istnieje
                    if 'isobaricInhPa' in dims and dim_sizes.get('isobaricInhPa', 0) > 1:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ {db_column} ma {dim_sizes['isobaricInhPa']} poziomów izobarycznych - wybieram pierwszy", flush=True)
                        try:
                            var_data = var_data.isel(isobaricInhPa=0)
                            # Po isel, zaktualizuj dims
                            dims = var_data.dims
                            dim_sizes = {dim: var_data.sizes[dim] for dim in dims}
                        except Exception as e:
                            print(f"{get_timestamp()} - [{fh_str}] ⚠ Błąd przy isel(isobaricInhPa=0): {e}", flush=True)
                    elif 'heightAboveGround' in dims and dim_sizes.get('heightAboveGround', 0) > 1:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ {db_column} ma {dim_sizes['heightAboveGround']} poziomów wysokości - wybieram pierwszy", flush=True)
                        try:
                            var_data = var_data.isel(heightAboveGround=0)
                            # Po isel, zaktualizuj dims
                            dims = var_data.dims
                            dim_sizes = {dim: var_data.sizes[dim] for dim in dims}
                        except Exception as e:
                            print(f"{get_timestamp()} - [{fh_str}] ⚠ Błąd przy isel(heightAboveGround=0): {e}", flush=True)
                    
                    # Konwertuj pojedynczą zmienną do DataFrame
                    # Użyj stack() tylko dla wymiarów które nie są lat/lon
                    non_coord_dims = [d for d in dims if d not in ['latitude', 'longitude']]
                    
                    if non_coord_dims:
                        # Jeśli są dodatkowe wymiary, usuń je przez wybranie pierwszej wartości
                        for dim in non_coord_dims:
                            if dim_sizes.get(dim, 0) > 1:
                                var_data = var_data.isel({dim: 0})
                    
                    tmp = var_data.to_dataframe().reset_index()
                    
                    # Sprawdź które współrzędne są dostępne
                    available_coords = [c for c in coords if c in tmp.columns]
                    
                    # Jeśli nie ma współrzędnych, pomiń
                    if not available_coords:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Pomijam {db_column} - brak współrzędnych", flush=True)
                        continue
                    
                    # Wybierz tylko potrzebne kolumny (współrzędne + wartość)
                    # Nazwa kolumny z wartością to nazwa zmiennej cfgrib (np. 't', 'gh', 'u10')
                    value_col = None
                    for col in tmp.columns:
                        if col not in available_coords and col not in ['time', 'valid_time', 'step', 'isobaricInhPa', 'heightAboveGround', 'stepType']:
                            value_col = col
                            break
                    
                    if value_col is None:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Pomijam {db_column} - brak kolumny wartości. Kolumny: {list(tmp.columns)}", flush=True)
                        continue
                    
                    # DEBUG: Sprawdź czy value_col ma wartości
                    if tmp[value_col].isna().all():
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Pomijam {db_column} - kolumna {value_col} ma same NaN", flush=True)
                        continue
                    
                    # Wybierz tylko potrzebne kolumny
                    cols_to_keep = available_coords + [value_col]
                    tmp = tmp[cols_to_keep]
                    
                    # Sprawdź rozmiar przed merge
                    if len(tmp) > 10_000_000:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Pomijam {db_column} - zbyt dużo wierszy ({len(tmp):,})", flush=True)
                        continue
                    
                    # Zmień nazwę kolumny wartości na nazwę kolumny bazy
                    if value_col != db_column:
                        tmp.rename(columns={value_col: db_column}, inplace=True)
                    
                    # DEBUG: Sprawdź czy są wartości w kolumnie
                    non_null_count = tmp[db_column].notna().sum()
                    if non_null_count == 0:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Pomijam {db_column} - brak wartości (wszystkie NaN)", flush=True)
                        continue
                    
                    print(f"{get_timestamp()} - [{fh_str}] ✓ {db_column}: {non_null_count}/{len(tmp)} wartości nie-NaN", flush=True)
                    
                    # Połącz z głównym DataFrame
                    if df is None:
                        df = tmp
                    else:
                        # Sprawdź rozmiar przed merge
                        if len(df) > 1_000_000 or len(tmp) > 1_000_000:
                            print(f"{get_timestamp()} - [{fh_str}] ⚠ Duże DataFrames przed merge: df={len(df):,}, tmp={len(tmp):,}", flush=True)
                        
                        # Merge na podstawie współrzędnych - sprawdź czy nie ma konfliktów nazw
                        common_cols = set(df.columns) & set(tmp.columns)
                        common_cols.discard('latitude')
                        common_cols.discard('longitude')
                        
                        if common_cols:
                            # Są wspólne kolumny (poza współrzędnymi) - użyj suffixes
                            df = df.merge(tmp, on=available_coords, how='outer', suffixes=('', '_dup'))
                            # Usuń kolumny z _dup
                            dup_cols = [c for c in df.columns if c.endswith('_dup')]
                            if dup_cols:
                                df = df.drop(columns=dup_cols)
                        else:
                            # Brak konfliktów - normalny merge
                            df = df.merge(tmp, on=available_coords, how='outer')
                    
                except MemoryError as e:
                    print(f"{get_timestamp()} - [{fh_str}] ⚠ BŁĄD PAMIĘCI przy konwersji {db_column}: {e}", flush=True)
                    continue
                except Exception as e:
                    error_msg = str(e)
                    if 'Unable to allocate' in error_msg or 'MemoryError' in error_msg:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ BŁĄD PAMIĘCI przy konwersji {db_column}: {error_msg[:200]}", flush=True)
                    else:
                        print(f"{get_timestamp()} - [{fh_str}] ⚠ Błąd konwersji {db_column}: {error_msg[:200]}", flush=True)
                    continue
            
            # Zwolnij pamięć
            del vars_region, all_data_vars
            import gc
            gc.collect()
            
            if df is None or len(df) == 0:
                print(f"{get_timestamp()} - [{fh_str}] ✗ Brak danych po konwersji", flush=True)
                return 0
            
            # Sprawdź czy są kolumny z nieprawidłowymi sufiksami
            suspicious_cols = [c for c in df.columns if any(c.lower().endswith(f'_m{i}') for i in range(1000))]
            if suspicious_cols:
                print(f"{get_timestamp()} - [{fh_str}] ⚠ UWAGA: Znaleziono podejrzane kolumny z sufiksami _m*: {suspicious_cols[:10]}...", flush=True)
                print(f"{get_timestamp()} - [{fh_str}] ⚠ To może być problem z MultiIndex lub duplikatami podczas merge!", flush=True)
            
            # Dodaj metadane
            df['run_time'] = run_time
            df['forecast_time'] = forecast_time
            df['created_at'] = datetime.utcnow()
            df.rename(columns={'latitude': 'lat', 'longitude': 'lon'}, inplace=True)
            
            # Oblicz wind_speed i wind_dir z u10 i v10
            if 'u10' in df.columns and 'v10' in df.columns:
                df['wind_speed'] = np.sqrt(df['u10']**2 + df['v10']**2)
                df['wind_dir'] = (270 - np.arctan2(df['v10'], df['u10']) * 180 / np.pi) % 360
                print(f"{get_timestamp()} - [{fh_str}] ✓ Obliczono wind_speed i wind_dir z u10 i v10", flush=True)
            
            # Zaokrąglij wszystkie kolumny numeryczne do 2 miejsc po przecinku (oprócz id jeśli istnieje)
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                if col not in ['id']:  # Nie zaokrąglaj ID jeśli istnieje
                    df[col] = df[col].round(2)
            
            # Usuń kolumny które nie powinny być w bazie (np. isobaricInhPa, heightAboveGround jako kolumny)
            cols_to_drop = [c for c in df.columns if c in ['isobaricInhPa', 'heightAboveGround', 'time', 'valid_time']]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)
            
            # Usuń kolumny z nieprawidłowymi poziomami (np. m999, m0, 999, etc.)
            # WAŻNE: Usuń wszystkie kolumny z sufiksami _m0, _m1, _m2, ..., _m999 (to są indeksy z MultiIndex)
            import re
            invalid_patterns = ['_m999', '_m0_', '_999_', '_999m', '_999mb', 'm999', 'm0', '_0m', '_0_mb']
            invalid_cols = [c for c in df.columns if any(pattern in c.lower() for pattern in invalid_patterns)]
            # Usuń wszystkie kolumny które kończą się na _m + liczba (np. _m0, _m1, _m999)
            invalid_cols.extend([c for c in df.columns if re.search(r'_m\d+$', str(c))])
            # Dodatkowo usuń kolumny z poziomem 999 (nieprawidłowy poziom)
            invalid_cols.extend([c for c in df.columns if '_999' in c.lower() and c not in invalid_cols])
            # Usuń duplikaty
            invalid_cols = list(set(invalid_cols))
            if invalid_cols:
                print(f"{get_timestamp()} - [{fh_str}] ⚠ Usuwam nieprawidłowe kolumny ({len(invalid_cols)}): {invalid_cols[:20]}...", flush=True)
                df = df.drop(columns=invalid_cols)
            
            # Zaokrąglij wartości numeryczne do 2 miejsc po przecinku
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                if col not in ['lat', 'lon']:  # Nie zaokrąglaj współrzędnych
                    df[col] = df[col].round(2)
            
            # DEBUG: Sprawdź kolumny i wartości przed usunięciem NaN
            print(f"{get_timestamp()} - [{fh_str}] DEBUG: Kolumny w DataFrame: {list(df.columns)}", flush=True)
            data_cols = [c for c in df.columns if c not in ['lat', 'lon', 'run_time', 'forecast_time']]
            if data_cols:
                for col in data_cols[:5]:  # Sprawdź pierwsze 5 kolumn
                    non_null = df[col].notna().sum()
                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: {col}: {non_null}/{len(df)} wartości nie-NaN", flush=True)
            
            # Usuń wiersze z samymi NaN (poza lat/lon/run_time/forecast_time)
            if data_cols:
                df = df.dropna(subset=data_cols, how='all')
            
            # DEBUG: Sprawdź po usunięciu NaN
            print(f"{get_timestamp()} - [{fh_str}] DEBUG: Po usunięciu NaN: {len(df)} wierszy", flush=True)
            if len(df) > 0 and data_cols:
                for col in data_cols[:5]:
                    non_null = df[col].notna().sum()
                    print(f"{get_timestamp()} - [{fh_str}] DEBUG: {col}: {non_null}/{len(df)} wartości nie-NaN", flush=True)
            
            records = df.to_dict('records')
            
            # Zwolnij pamięć
            del df
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
                
                # Ostateczna walidacja kolumn przed zapisem - usuń wszystkie nieprawidłowe
                import re
                invalid_patterns = ['_m999', '_m0_', '_999_', '_999m', '_999mb', 'm999', 'm0', '_0m', '_0_mb']
                invalid_cols = [c for c in df_final.columns if any(pattern in str(c).lower() for pattern in invalid_patterns)]
                # Usuń wszystkie kolumny które kończą się na _m + liczba (np. _m0, _m1, _m999)
                invalid_cols.extend([c for c in df_final.columns if re.search(r'_m\d+$', str(c))])
                invalid_cols.extend([c for c in df_final.columns if '_999' in str(c).lower() and c not in invalid_cols])
                # Usuń duplikaty
                invalid_cols = list(set(invalid_cols))
                if invalid_cols:
                    print(f"{get_timestamp()} - [{fh_str}] ⚠ Ostateczne usuwanie nieprawidłowych kolumn przed zapisem ({len(invalid_cols)}): {invalid_cols[:20]}...", flush=True)
                    df_final = df_final.drop(columns=invalid_cols)
                
                # Usuń również kolumny techniczne jeśli jeszcze są
                tech_cols = [c for c in df_final.columns if c in ['isobaricInhPa', 'heightAboveGround', 'time', 'valid_time']]
                if tech_cols:
                    df_final = df_final.drop(columns=tech_cols)
                
                df_final.to_sql('gfs_forecast', engine, if_exists='append', index=False, method='multi', chunksize=1000)
                print(f"{get_timestamp()} - [{fh_str}] ✓ Zapisano {len(records)} rekordów", flush=True)
                del df_final
                import gc
                gc.collect()
                return len(records)
            except KeyError as e:
                print(f"{get_timestamp()} - [{fh_str}] ✗ BŁĄD KOLUMNY: {e}", flush=True)
                import traceback
                print(f"{get_timestamp()} - [{fh_str}] Traceback:\n{traceback.format_exc()}", flush=True)
                # Spróbuj ponownie z filtrowaniem kolumn
                try:
                    df_final = pd.DataFrame(records)
                    # Usuń wszystkie kolumny które mogą powodować problemy
                    import re
                    all_invalid = [c for c in df_final.columns if any(x in str(c).lower() for x in ['_m999', '_999', 'm999', '_m0', 'm0'])]
                    # Usuń wszystkie kolumny które kończą się na _m + liczba
                    all_invalid.extend([c for c in df_final.columns if re.search(r'_m\d+$', str(c))])
                    all_invalid = list(set(all_invalid))
                    if all_invalid:
                        df_final = df_final.drop(columns=all_invalid)
                    df_final.to_sql('gfs_forecast', engine, if_exists='append', index=False, method='multi', chunksize=1000)
                    print(f"{get_timestamp()} - [{fh_str}] ✓ Zapisano po naprawie kolumn: {len(df_final)} rekordów", flush=True)
                    return len(df_final)
                except:
                    return 0
            except MemoryError as e:
                print(f"{get_timestamp()} - [{fh_str}] ✗ BŁĄD PAMIĘCI przy zapisie: {e}", flush=True)
                return 0
            except Exception as e:
                print(f"{get_timestamp()} - [{fh_str}] ✗ BŁĄD przy zapisie: {e}", flush=True)
                import traceback
                print(f"{get_timestamp()} - [{fh_str}] Traceback:\n{traceback.format_exc()}", flush=True)
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
