"""
GFS Weather Data Downloader - PROFESSIONAL VERSION
Pobiera pełny zakres prognoz: f000-f120 (co 1h) + f123-f384 (co 3h) = 209 prognoz
Z multi-threading, resume, progress bar i priorytetyzacją
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
import os
import logging
warnings.filterwarnings('ignore')

# Stłum błędy ECCODES (są tylko ostrzeżeniami)
os.environ['ECCODES_LOG_VERBOSITY'] = '0'
os.environ['ECCODES_DEBUG'] = '0'

# Wycisz logi DEBUG z cfgrib, ecmwf, eccodes, urllib3, requests (niepotrzebne dla użytkownika)
logging.getLogger('cfgrib').setLevel(logging.WARNING)
logging.getLogger('ecmwf').setLevel(logging.WARNING)
logging.getLogger('eccodes').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

# Logger dla modułu (będzie używał root logger jeśli nie jest skonfigurowany)
module_logger = logging.getLogger(__name__)

# === GŁÓWNY KOD - WYKONUJE SIĘ TYLKO GDY URUCHOMIONY BEZPOŚREDNIO ===
# Sprawdź czy moduł jest uruchamiany bezpośrednio (nie importowany)
try:
    import builtins
    _is_imported_by_daemon = hasattr(builtins, '__imported_by_daemon__')
except:
    _is_imported_by_daemon = False

_is_main_module = (__name__ == "__main__" and not _is_imported_by_daemon)
if _is_main_module:
    print("=" * 70)
    print("GFS Weather Data Downloader - PROFESSIONAL VERSION")
    print("=" * 70)

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
        
        # Konfiguracja wątków (można dostosować)
        NUM_THREADS = 6  # 4-8 wątków równolegle
        
        print(f"✓ Konfiguracja OK")
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

# === 3. FUNKCJE POMOCNICZE ===

def check_gfs_availability(date_str, hour_str, forecast_hour, verbose=False):
    """
    Sprawdza czy dana prognoza GFS jest dostępna.
    Sprawdza oba serwery: nomads.ncep.noaa.gov i ftp.ncep.noaa.gov
    Zwraca True jeśli którykolwiek serwer ma dane dostępne.
    """
    # Lista serwerów do sprawdzenia (w kolejności priorytetu)
    servers = [
        "nomads.ncep.noaa.gov",
        "ftp.ncep.noaa.gov"
    ]
    
    base_path = f"/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p25.f{forecast_hour:03d}"
    
    for server in servers:
        url = f"https://{server}{base_path}"
        
        try:
            # Używamy HEAD zamiast GET dla szybszego sprawdzenia
            response = requests.head(url, timeout=10, allow_redirects=True)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                # Sprawdź czy to nie jest strona HTML (błąd 404 jako HTML)
                if 'text/html' in content_type:
                    continue  # Spróbuj następny serwer
                
                if verbose:
                    module_logger.debug(f"  ✓ Dane dostępne na {server}")
                return True
                
        except requests.exceptions.Timeout:
            if verbose:
                module_logger.debug(f"  ⏱ Timeout na {server}")
            continue  # Spróbuj następny serwer
        except requests.exceptions.RequestException as e:
            if verbose:
                module_logger.debug(f"  ✗ Błąd na {server}: {e}")
            continue  # Spróbuj następny serwer
        except Exception as e:
            if verbose:
                module_logger.debug(f"  ✗ Nieoczekiwany błąd na {server}: {e}")
            continue  # Spróbuj następny serwer
    
    # Jeśli żaden serwer nie zwrócił 200, sprawdź jeszcze raz przez GET (dla pewności)
    # Niektóre serwery mogą nie obsługiwać HEAD poprawnie
    for server in servers:
        url = f"https://{server}{base_path}"
        
        try:
            response = requests.get(url, stream=True, timeout=10)
            response.close()
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                if 'text/html' in content_type:
                    continue
                
                if verbose:
                    module_logger.debug(f"  ✓ Dane dostępne na {server} (GET)")
                return True
                
        except:
            continue
    
    return False

def get_required_forecast_hours():
    """
    Zwraca set wymaganych forecast_hour do pobrania:
    - f000-f120 (co 1h) = 121 prognoz
    - f123-f384 (co 3h) = 88 prognoz
    RAZEM: 209 prognoz
    """
    required_hours = set()
    
    # f000-f120: co 1h (121 prognoz)
    for hour in range(0, 121):
        required_hours.add(hour)
    
    # f123-f384: co 3h (88 prognoz)
    for hour in range(123, 385, 3):
        required_hours.add(hour)
    
    return required_hours

def get_existing_forecast_hours(run_time, engine=None):
    """
    Zwraca set forecast_hour które są już w bazie dla danego run_time.
    Oblicza forecast_hour na podstawie różnicy między forecast_time a run_time.
    """
    # Użyj globalnego engine jeśli nie przekazano
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
                
                # Parsuj forecast_time jeśli to string
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
                    # Oblicz forecast_hour jako różnicę w godzinach
                    time_diff = forecast_time - run_time
                    forecast_hour = int(time_diff.total_seconds() / 3600)
                    existing_hours.add(forecast_hour)
            
            return existing_hours
            
    except Exception as e:
        print(f"⚠ Błąd sprawdzania forecast_hour w bazie: {e}")
        return set()

def find_latest_gfs_run(engine=None):
    """Znajduje najnowszy dostępny run GFS (szuka nowszego niż w bazie)"""
    # Użyj globalnego engine jeśli nie przekazano
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
    
    # Pobierz wymagane forecast_hour
    required_hours = get_required_forecast_hours()
    
    # Sprawdź najnowszy run w bazie
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
    
    # Szukaj nowszego run niż ten w bazie
    found_run = None
    
    for i in range(6):  # Sprawdź do 6 runów wstecz (36h)
        check_time = run_time - timedelta(hours=i * 6)
        date_str = check_time.strftime("%Y%m%d")
        hour_str = f"{check_time.hour:02d}"
        
        # Sprawdź dostępność online
        if check_gfs_availability(date_str, hour_str, 0):
            # Jeśli nie mamy run w bazie, zwróć pierwszy dostępny
            if last_run_in_db is None:
                return check_time, date_str, hour_str
            
            # Normalizuj daty do porównania (usuń mikrosekundy)
            check_time_normalized = check_time.replace(microsecond=0, second=0)
            if isinstance(last_run_in_db, datetime):
                last_run_normalized = last_run_in_db.replace(microsecond=0, second=0)
            else:
                last_run_normalized = last_run_in_db
            
            # Jeśli ten run jest starszy niż w bazie, pomiń
            if check_time_normalized < last_run_normalized:
                continue
            
            # Jeśli ten run jest taki sam jak w bazie, sprawdź czy ma wszystkie wymagane prognozy
            if check_time_normalized == last_run_normalized:
                try:
                    # Sprawdź które konkretne forecast_hour są już w bazie
                    existing_hours = get_existing_forecast_hours(check_time, engine)
                    missing_hours = required_hours - existing_hours
                    
                    # Jeśli wszystkie wymagane prognozy są już pobrane, szukaj nowszego run
                    if len(missing_hours) == 0:
                        # Szukaj nowszego run
                        continue
                    else:
                        # Ten sam run, ale brakuje niektórych prognoz - zwróć go
                        found_run = (check_time, date_str, hour_str)
                        break
                except Exception as e:
                    # W przypadku błędu, załóż że brakuje prognoz
                    found_run = (check_time, date_str, hour_str)
                    break
            
            # Ten run jest nowszy niż w bazie - zwróć go
            if check_time_normalized > last_run_normalized:
                return check_time, date_str, hour_str
            
            # Ten sam run, ale może nie mieć wszystkich prognoz
            if found_run is None:
                found_run = (check_time, date_str, hour_str)
    
    # Jeśli nie znaleziono nowszego, zwróć ten sam jeśli nie ma wszystkich prognoz
    if found_run:
        return found_run
    
    return None, None, None

def check_existing_forecasts(run_time, engine=None):
    """Sprawdza które prognozy już są w bazie dla danego run_time"""
    # Użyj globalnego engine jeśli nie przekazano
    if engine is None:
        try:
            engine = globals().get('engine')
            if engine is None:
                return set()
        except:
            return set()
    
    try:
        with engine.connect() as conn:
            # Formatuj run_time jako string dla porównania w SQL
            run_time_str = run_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Użyj formatu datetime dla porównania
            result = conn.execute(text("""
                SELECT DISTINCT forecast_time
                FROM gfs_forecast
                WHERE DATE_FORMAT(run_time, '%Y-%m-%d %H:%i:%s') = :run_time
                ORDER BY forecast_time
            """), {"run_time": run_time_str})
            
            existing_times = set()
            rows = result.fetchall()
            
            for row in rows:
                # Upewnij się że to datetime object
                forecast_time = row[0]
                
                # Normalizuj datę - usuń mikrosekundy dla porównania
                if isinstance(forecast_time, datetime):
                    # Zaokrąglij do sekundy (usuń mikrosekundy)
                    normalized = forecast_time.replace(microsecond=0, second=0)
                    existing_times.add(normalized)
                elif isinstance(forecast_time, str):
                    # Jeśli string, parsuj do datetime
                    try:
                        # Spróbuj różne formaty
                        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M']:
                            try:
                                dt = datetime.strptime(forecast_time, fmt)
                                normalized = dt.replace(microsecond=0, second=0)
                                existing_times.add(normalized)
                                break
                            except:
                                continue
                    except:
                        pass
            
            return existing_times
            
    except Exception as e:
        print(f"⚠ Błąd sprawdzania bazy: {e}")
        import traceback
        traceback.print_exc()
        return set()

def generate_forecast_list(run_time):
    """
    Generuje listę prognoz do pobrania:
    - f000-f120 (co 1h) = 121 prognoz
    - f123-f384 (co 3h) = 88 prognoz
    RAZEM: 209 prognoz
    Priorytet: najświeższe pierwsze
    """
    forecasts = []
    
    # f000-f120: co 1h (121 prognoz)
    for hour in range(0, 121):
        forecast_time = run_time + timedelta(hours=hour)
        forecasts.append({
            'forecast_hour': hour,
            'forecast_time': forecast_time,
            'priority': hour  # Niższy = wyższy priorytet (f000, f001, f002...)
        })
    
    # f123-f384: co 3h (88 prognoz)
    for hour in range(123, 385, 3):
        forecast_time = run_time + timedelta(hours=hour)
        forecasts.append({
            'forecast_hour': hour,
            'forecast_time': forecast_time,
            'priority': hour  # Niższy = wyższy priorytet
        })
    
    # Sortuj według priorytetu (najświeższe pierwsze)
    forecasts.sort(key=lambda x: x['priority'])
    
    return forecasts

    # === 4. ZNAJDŹ NAJNOWSZY RUN ===
    print(f"\n⏳ Szukam najnowszego run GFS...")

    try:
        run_time, RUN_DATE, RUN_HOUR = find_latest_gfs_run(engine)
        
        if run_time is None:
            # Sprawdź co mamy w bazie
            try:
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT MAX(run_time) as last_run, COUNT(DISTINCT forecast_time) as count
                        FROM gfs_forecast
                        WHERE run_time = (SELECT MAX(run_time) FROM gfs_forecast)
                    """))
                row = result.fetchone()
                if row and row[0]:
                    last_run = row[0]
                    count = row[1] if row[1] else 0
                    
                    # Sprawdź które konkretne prognozy są już pobrane
                    if isinstance(last_run, str):
                        try:
                            last_run = datetime.strptime(last_run, '%Y-%m-%d %H:%M:%S')
                        except:
                            try:
                                last_run = datetime.strptime(last_run, '%Y-%m-%d %H:%M')
                            except:
                                pass
                    
                    required_hours = get_required_forecast_hours()
                    existing_hours = get_existing_forecast_hours(last_run, engine) if isinstance(last_run, datetime) else set()
                    missing_hours = sorted(list(required_hours - existing_hours))
                    
                    print("\n" + "=" * 70)
                    print("ℹ️  BRAK NOWSZEGO RUN GFS")
                    print("=" * 70)
                    print(f"Ostatni run w bazie: {last_run}")
                    print(f"Prognoz w bazie: {count} / 209")
                    
                    if len(missing_hours) == 0:
                        print(f"\n💡 Wszystkie dane są aktualne!")
                    else:
                        print(f"\n⚠️  Brakuje {len(missing_hours)} prognoz:")
                        # Pokaż pierwsze 20 brakujących prognoz
                        missing_str = ', '.join([f"f{h:03d}" for h in missing_hours[:20]])
                        if len(missing_hours) > 20:
                            missing_str += f" ... i {len(missing_hours) - 20} więcej"
                        print(f"   Brakujące: {missing_str}")
                        print(f"\n💡 Uruchom ponownie skrypt, aby pobrać brakujące prognozy.")
                    
                    # Oblicz kiedy będzie następny run
                    if isinstance(last_run, datetime):
                        next_run = last_run + timedelta(hours=6)
                        print(f"\nNastępny run GFS: {next_run.strftime('%Y-%m-%d %H:00')} UTC")
                        
                        # Kiedy będzie dostępny (ok. 3.5h po run)
                        next_available = next_run + timedelta(hours=3, minutes=30)
                        print(f"Będzie dostępny około: {next_available.strftime('%Y-%m-%d %H:%M')} UTC")
                    print("=" * 70)
            except:
                print("✗ Nie znaleziono dostępnego run GFS")
            
            input("\nNaciśnij Enter...")
            exit(0)
        
        print(f"✓ Run znaleziony: {run_time.strftime('%Y-%m-%d %H:00')} UTC")
        
    except Exception as e:
        print(f"✗ BŁĄD: {e}")
        input("\nEnter...")
        exit(1)

    # === 5. SPRAWDŹ CO JUŻ JEST W BAZIE (RESUME) ===
    print(f"\n⏳ Sprawdzam co już jest w bazie...")

    # Debug: sprawdź wszystkie run_time w bazie
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT run_time, COUNT(DISTINCT forecast_time) as count, COUNT(*) as total_records
                FROM gfs_forecast
                GROUP BY run_time
                ORDER BY run_time DESC
                LIMIT 5
            """))
            all_runs = list(result)
            if all_runs:
                print(f"  Znalezione run_time w bazie:")
                for row in all_runs:
                    rt, count, total = row[0], row[1], row[2]
                    print(f"    - {rt}: {count} unikalnych prognoz, {total} rekordów")
    except Exception as e:
        print(f"  ⚠ Błąd sprawdzania run_time: {e}")

    existing_forecast_times = check_existing_forecasts(run_time, engine)
    existing_count = len(existing_forecast_times)

    # Sprawdź które konkretne forecast_hour są już pobrane
    existing_hours = get_existing_forecast_hours(run_time, engine)
    required_hours = get_required_forecast_hours()
    missing_hours = sorted(list(required_hours - existing_hours))

    # Debug: pokaż przykładowe forecast_time z bazy
    if existing_count > 0:
        print(f"✓ Znaleziono {existing_count} istniejących prognoz w bazie dla run {run_time.strftime('%Y-%m-%d %H:00')}")
        if len(missing_hours) > 0:
            print(f"  ⚠ Brakuje {len(missing_hours)} prognoz (będę je pobierać)")
            # Pokaż pierwsze 10 brakujących prognoz
            missing_str = ', '.join([f"f{h:03d}" for h in missing_hours[:10]])
            if len(missing_hours) > 10:
                missing_str += f" ... i {len(missing_hours) - 10} więcej"
            print(f"  Brakujące: {missing_str}")
        else:
            print(f"  ✓ Wszystkie wymagane prognozy są już w bazie")
        print(f"  Będę kontynuować od miejsca przerwania (RESUME)")
        # Debug: pokaż pierwsze 3 i ostatnie 3 przykłady
        sorted_times = sorted(list(existing_forecast_times))
        if sorted_times:
            first_3 = sorted_times[:3]
            last_3 = sorted_times[-3:] if len(sorted_times) > 3 else []
            examples = ', '.join([t.strftime('%Y-%m-%d %H:%M') for t in first_3])
            if last_3:
                examples += f" ... {', '.join([t.strftime('%Y-%m-%d %H:%M') for t in last_3])}"
            print(f"  Przykłady: {examples}")
    else:
        print(f"✓ Brak prognoz dla tego run - zaczynam od początku")

    # === 6. GENERUJ LISTĘ PROGNOZ ===
    print(f"\n⏳ Generowanie listy prognoz...")

    all_forecasts = generate_forecast_list(run_time)
    print(f"✓ Wygenerowano {len(all_forecasts)} prognoz do pobrania")

    # Filtruj te które już są w bazie
    # Normalizuj daty prognoz (usuń mikrosekundy) dla porównania
    forecasts_to_download = []
    skipped_forecasts = []

    for f in all_forecasts:
        # Normalizuj forecast_time (usuń mikrosekundy i sekundy)
        normalized_forecast_time = f['forecast_time'].replace(microsecond=0, second=0)
        
        # Sprawdź czy już jest w bazie
        if normalized_forecast_time not in existing_forecast_times:
            forecasts_to_download.append(f)
        else:
            skipped_forecasts.append(f)

    print(f"✓ Do pobrania: {len(forecasts_to_download)} prognoz")
    print(f"✓ Już w bazie: {existing_count} prognoz")

    # Debug: pokaż pierwsze i ostatnie pominięte prognozy
    if skipped_forecasts and len(skipped_forecasts) <= 10:
        skipped_str = ', '.join([f"f{f['forecast_hour']:03d}({f['forecast_time'].strftime('%Y-%m-%d %H:%M')})" for f in skipped_forecasts])
        print(f"  Pominięte prognozy: {skipped_str}")
    elif skipped_forecasts:
        first_3 = skipped_forecasts[:3]
        last_3 = skipped_forecasts[-3:]
        first_str = ', '.join([f"f{f['forecast_hour']:03d}({f['forecast_time'].strftime('%H:%M')})" for f in first_3])
        last_str = ', '.join([f"f{f['forecast_hour']:03d}({f['forecast_time'].strftime('%H:%M')})" for f in last_3])
        print(f"  Pominięte (pierwsze): {first_str}")
        print(f"  Pominięte (ostatnie): {last_str}")

    if len(forecasts_to_download) == 0:
        print("\n" + "=" * 70)
        print("ℹ️  WSZYSTKIE PROGNOZY JUŻ SĄ W BAZIE!")
        print("=" * 70)
        print(f"Run: {run_time.strftime('%Y-%m-%d %H:00')} UTC")
        print(f"Prognoz w bazie: {existing_count} / {len(all_forecasts)}")
        input("\nNaciśnij Enter...")
        exit(0)

    # === 7. KLASY I FUNKCJE DO MULTI-THREADING ===

class ForecastDownloader:
    def __init__(self, run_date, run_hour, lat_min, lat_max, lon_min, lon_max, engine):
        self.run_date = run_date
        self.run_hour = run_hour
        self.lat_min = lat_min
        self.lat_max = lat_max
        self.lon_min = lon_min
        self.lon_max = lon_max
        self.engine = engine
        self.filters_config = [
            # Ciśnienie
            {'name': 'mslp', 'filter': {'typeOfLevel': 'meanSea', 'stepType': 'instant'}, 'vars': ['prmsl']},
            
            # Opady - używamy stepType 'accum' dla skumulowanych opadów od początku prognozy
            # Dla f000 tp=0 (brak opadów), dla f003 tp=opady w ciągu 3h od początku, itd.
            {'name': 'precip', 'filter': {'typeOfLevel': 'surface', 'stepType': 'accum', 'shortName': 'tp'}, 'vars': ['tp']},
            {'name': 'precip_rate', 'filter': {'typeOfLevel': 'surface', 'stepType': 'instant'}, 'vars': ['prate']},
            
            # Zachmurzenie - wszystkie poziomy
            {'name': 'clouds', 'filter': {'typeOfLevel': 'surface', 'stepType': 'instant'}, 'vars': ['tcc', 'lcc', 'mcc', 'hcc']},
            
            # Parametry 2m
            {'name': 't2m', 'filter': {'typeOfLevel': 'heightAboveGround', 'level': 2, 'stepType': 'instant'}, 'vars': ['t2m', 'd2m', 'r2']},
            
            # Wiatr 10m
            {'name': 'wind10', 'filter': {'typeOfLevel': 'heightAboveGround', 'level': 10, 'stepType': 'instant'}, 'vars': ['u10', 'v10', 'gust']},
            
            # Wiatr 80m
            {'name': 'wind80', 'filter': {'typeOfLevel': 'heightAboveGround', 'level': 80, 'stepType': 'instant'}, 'vars': ['u', 'v', 't']},
            
            # Parametry atmosferyczne
            {'name': 'cape', 'filter': {'typeOfLevel': 'atmosphere', 'stepType': 'instant'}, 'vars': ['cape', 'cin', 'pwat']},
            
            # Parametry wysokościowe 850 hPa
            {'name': 't850', 'filter': {'typeOfLevel': 'isobaricInhPa', 'level': 850}, 'vars': ['t', 'gh']},
            
            # Parametry wysokościowe 500 hPa
            {'name': 'gh500', 'filter': {'typeOfLevel': 'isobaricInhPa', 'level': 500}, 'vars': ['gh']},
            
            # Widzialność i promieniowanie
            {'name': 'surface_other', 'filter': {'typeOfLevel': 'surface', 'stepType': 'instant'}, 'vars': ['vis', 'dswrf']},
        ]
    
    def download_and_process(self, forecast_info, progress_queue, thread_id=None, attempt_count=0):
        """
        Pobiera i przetwarza jedną prognozę
        Zwraca (success, forecast_info, df) lub (False, forecast_info, None)
        """
        forecast_hour = forecast_info['forecast_hour']
        forecast_time = forecast_info['forecast_time']
        run_time = datetime.strptime(f"{self.run_date} {self.run_hour}", "%Y%m%d %H")
        
        # Lista serwerów do sprawdzenia (w kolejności priorytetu)
        servers = [
            "nomads.ncep.noaa.gov",
            "ftp.ncep.noaa.gov"
        ]
        
        base_path = f"/pub/data/nccf/com/gfs/prod/gfs.{self.run_date}/{self.run_hour}/atmos/gfs.t{self.run_hour}z.pgrb2.0p25.f{forecast_hour:03d}"
        idx_path = f"{base_path}.idx"
        
        temp_file = None
        response = None
        used_server = None
        
        # NAJPIERW sprawdź czy plik .idx istnieje (weryfikacja dostępności)
        idx_available = False
        for server in servers:
            idx_url = f"https://{server}{idx_path}"
            try:
                idx_response = requests.head(idx_url, timeout=10, allow_redirects=True)
                if idx_response.status_code == 200:
                    idx_available = True
                    module_logger.debug(f"thr: {thread_id} - Plik .idx dostępny na {server} dla f{forecast_hour:03d}")
                    break
            except:
                continue
        
        if not idx_available:
            module_logger.warning(f"thr: {thread_id} - Plik .idx niedostępny dla f{forecast_hour:03d} (licznikProbPobrania = {attempt_count})")
        
        # Spróbuj pobrać z każdego serwera po kolei
        for server in servers:
            url = f"https://{server}{base_path}"
            
            try:
                module_logger.info(f"thr: {thread_id} - Pobieranie (licznikProbPobrania = {attempt_count}): f{forecast_hour:03d}")
                # Pobierz plik
                response = requests.get(url, stream=True, timeout=300)
                status_code = response.status_code
                module_logger.info(f"thr: {thread_id} - Status pobrania pliku: {status_code}")
                
                if status_code == 200:
                    used_server = server
                    # Jeśli udało się, przerwij pętlę
                    break
                elif status_code == 404:
                    module_logger.warning(f"thr: {thread_id} - Plik f{forecast_hour:03d} niedostępny na {server} (404)")
                    response.close()
                    response = None
                    continue
                else:
                    module_logger.warning(f"thr: {thread_id} - Nieoczekiwany status {status_code} z {server}")
                    response.close()
                    response = None
                    continue
            except requests.exceptions.Timeout:
                module_logger.warning(f"thr: {thread_id} - Timeout pobierania z {server} dla f{forecast_hour:03d}")
                if response:
                    response.close()
                response = None
                continue
            except requests.exceptions.RequestException as e:
                # Jeśli błąd, spróbuj następny serwer
                module_logger.warning(f"thr: {thread_id} - Błąd pobierania z {server} dla f{forecast_hour:03d}: {e}")
                if response:
                    response.close()
                response = None
                continue
        
        # Jeśli żaden serwer nie zadziałał, zwróć błąd
        if response is None or response.status_code != 200:
            if attempt_count > 0:
                module_logger.warning(f"thr: {thread_id} - Pobieranie ponowne (licznikProbPobrania = {attempt_count}): f{forecast_hour:03d}")
            raise Exception(f"Nie udało się pobrać f{forecast_hour:03d} z żadnego serwera")
        
        # Zapisz tymczasowo
        if not os.path.exists('temp'):
            os.makedirs('temp')
        
        temp_file = os.path.join('temp', f'gfs_{self.run_date}_{self.run_hour}_f{forecast_hour:03d}.grib2')
        file_size_bytes = 0
        
        try:
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        file_size_bytes += len(chunk)
            
            # Parsuj GRIB2
            all_datasets = []
            
            # Wycisz logi cfgrib i eccodes podczas parsowania
            cfgrib_logger = logging.getLogger('cfgrib')
            eccodes_logger = logging.getLogger('eccodes')
            ecmwf_logger = logging.getLogger('ecmwf')
            original_cfgrib_level = cfgrib_logger.level
            original_eccodes_level = eccodes_logger.level
            original_ecmwf_level = ecmwf_logger.level
            
            cfgrib_logger.setLevel(logging.ERROR)  # Tylko błędy
            eccodes_logger.setLevel(logging.ERROR)  # Tylko błędy
            ecmwf_logger.setLevel(logging.ERROR)  # Tylko błędy
            
            # Wycisz również root logger dla tych modułów
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if hasattr(handler, 'setLevel'):
                    # Nie zmieniamy poziomu handlera, tylko loggerów
                    pass
            
            try:
                module_logger.info(f"thr: {thread_id} - Rozpoczynam parsowanie GRIB2 dla f{forecast_hour:03d}")
                for idx, flt_cfg in enumerate(self.filters_config, 1):
                    try:
                        # Stłum błędy ECCODES podczas parsowania
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            module_logger.debug(f"thr: {thread_id} - Parsowanie {flt_cfg['name']} ({idx}/{len(self.filters_config)}) dla f{forecast_hour:03d}")
                            ds = xr.open_dataset(
                                temp_file, 
                                engine='cfgrib',
                                backend_kwargs={
                                    'filter_by_keys': flt_cfg['filter'], 
                                    'indexpath': '',
                                    'errors': 'ignore'  # Ignoruj błędy parsowania
                                }
                            )
                            
                            module_logger.debug(f"thr: {thread_id} - Wycinanie regionu dla {flt_cfg['name']} f{forecast_hour:03d}")
                            ds_region = ds.sel(
                                latitude=slice(self.lat_max, self.lat_min),
                                longitude=slice(self.lon_min, self.lon_max)
                            )
                            
                            all_datasets.append({
                                'name': flt_cfg['name'],
                                'dataset': ds_region,
                                'vars': flt_cfg['vars']
                            })
                            module_logger.debug(f"thr: {thread_id} - ✓ {flt_cfg['name']} sparsowany dla f{forecast_hour:03d}")
                            
                    except Exception as e:
                        # Ignoruj błędy parsowania - niektóre pliki mogą mieć problemy
                        module_logger.debug(f"thr: {thread_id} - Błąd parsowania {flt_cfg['name']} dla f{forecast_hour:03d}: {e}")
                        continue
            finally:
                # Przywróć oryginalny poziom logowania
                cfgrib_logger.setLevel(original_cfgrib_level)
                eccodes_logger.setLevel(original_eccodes_level)
                ecmwf_logger.setLevel(original_ecmwf_level)
                module_logger.info(f"thr: {thread_id} - Zakończono parsowanie GRIB2 dla f{forecast_hour:03d} - znaleziono {len(all_datasets)} datasetów")
            
            # Konwertuj do DataFrame
            if len(all_datasets) == 0:
                module_logger.warning(f"thr: {thread_id} - Brak datasetów po parsowaniu f{forecast_hour:03d}")
                return (False, forecast_info, None, 0)
            
            module_logger.info(f"thr: {thread_id} - Konwertuję {len(all_datasets)} datasetów do DataFrame dla f{forecast_hour:03d}")
            df = None
            
            for ds_info in all_datasets:
                ds = ds_info['dataset']
                level_name = ds_info['name']
                
                for var in ds_info['vars']:
                    if var not in ds.data_vars:
                        continue
                    
                    try:
                        data = ds[var]
                        
                        # Transformacje dla różnych parametrów
                        if var in ['t2m', 'd2m', 't']:
                            data = data - 273.15  # Konwersja z Kelvin na °C
                        elif var == 'prmsl':
                            data = data / 100  # Konwersja z Pa na hPa
                        elif var in ['tcc', 'lcc', 'mcc', 'hcc']:
                            data = data * 100  # Zachmurzenie z 0-1 na procenty 0-100
                        elif var == 'r2':
                            # r2 to wilgotność względna - zazwyczaj jest już w procentach w GRIB2
                            # Sprawdź czy trzeba przeliczyć (jeśli wartości są w zakresie 0-1)
                            try:
                                max_val = float(data.max().values)
                                if max_val <= 1.0:
                                    data = data * 100  # Konwersja z 0-1 na procenty
                            except:
                                # Jeśli nie można sprawdzić, zakładamy że już w procentach
                                pass
                        elif var == 'prate':
                            # Intensywność opadów - może potrzebować transformacji
                            # Prate jest w kg/m²/s, można pozostawić lub przeliczyć
                            pass
                        elif var in ['vis', 'dswrf']:
                            # Widzialność i promieniowanie - pozostawiamy jak są
                            pass
                        
                        tmp = data.to_dataframe().reset_index()
                        coords = [c for c in ['latitude', 'longitude', 'time'] if c in tmp.columns]
                        
                        new_name = var
                        # Dodaj prefix dla kolizji nazw
                        if var in ['t', 'gh', 'u', 'v'] and level_name not in ['t2m', 'wind10']:
                            new_name = f"{var}_{level_name}"
                        
                        # Mapowanie nazw dla zgodności z bazą
                        if var == 'prmsl':
                            new_name = 'mslp'  # prmsl -> mslp
                        elif var == 'r2':
                            new_name = 'rh'  # r2 -> rh (wilgotność względna)
                        
                        if var in tmp.columns:
                            tmp.rename(columns={var: new_name}, inplace=True)
                        
                        cols = coords + [new_name]
                        tmp = tmp[cols]
                        
                        if df is None:
                            df = tmp
                        else:
                            df = df.merge(tmp, on=coords, how='outer')
                    
                    except:
                        continue
            
            # Zamknij datasets
            for ds_info in all_datasets:
                ds_info['dataset'].close()
            
            # Przygotuj DataFrame
            if df is None or len(df) == 0:
                return (False, forecast_info, None, 0)
            
            df['run_time'] = run_time
            df['created_at'] = datetime.utcnow()
            
            # WAŻNE: Nadpisz 'time' prawidłowym forecast_time (run_time + forecast_hour)
            # Kolumna 'time' z GRIB2 może mieć nieprawidłowe wartości
            if 'time' in df.columns:
                # Zastąp wszystkie wartości 'time' prawidłowym forecast_time
                df['time'] = forecast_time
            
            df.rename(columns={
                'latitude': 'lat',
                'longitude': 'lon',
                'time': 'forecast_time'
            }, inplace=True)
            
            # Oblicz wiatr
            if 'u10' in df.columns and 'v10' in df.columns:
                df['wind_speed'] = np.sqrt(df['u10']**2 + df['v10']**2)
                df['wind_dir'] = (270 - np.arctan2(df['v10'], df['u10']) * 180 / np.pi) % 360
            
            # Zaokrąglij wszystkie kolumny numeryczne do 2 miejsc po przecinku
            # (oprócz id - jeśli istnieje)
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                if col not in ['id']:  # Nie zaokrąglaj ID jeśli istnieje
                    # Zaokrąglij do 2 miejsc po przecinku (zmniejsza rozmiar bazy)
                    df[col] = df[col].round(2)
            
            # ZAPIS DO CSV (backup przed zapisem do MySQL)
            csv_dir = os.path.join('temp', 'csv_backup')
            if not os.path.exists(csv_dir):
                os.makedirs(csv_dir)
            
            csv_file = os.path.join(csv_dir, f'gfs_{self.run_date}_{self.run_hour}_f{forecast_hour:03d}.csv')
            try:
                df.to_csv(csv_file, index=False, encoding='utf-8')
                module_logger.info(f"thr: {thread_id} - Zapisano do CSV: {len(df)} rekordów dla f{forecast_hour:03d}")
            except Exception as e:
                module_logger.warning(f"thr: {thread_id} - Błąd zapisu do CSV dla f{forecast_hour:03d}: {e}")
                # Kontynuuj mimo błędu CSV
            
            # Zapis do bazy (na bieżąco)
            try:
                module_logger.info(f"thr: {thread_id} - Przeniesienie danych z CSV do bazy danych dla f{forecast_hour:03d}")
                df.to_sql(
                    "gfs_forecast",
                    self.engine,
                    if_exists="append",
                    index=False,
                    chunksize=1000,
                    method='multi'
                )
                file_size_mb = file_size_bytes / (1024 * 1024)
                module_logger.info(f"thr: {thread_id} - Zakończono zapis do bazy dla f{forecast_hour:03d} ({len(df)} rekordów, {file_size_mb:.2f} MB)")
            except Exception as e:
                # Możliwe duplikaty - sprawdź przed zapisem
                module_logger.warning(f"thr: {thread_id} - Błąd zapisu do bazy dla f{forecast_hour:03d}: {e}")
                return (False, forecast_info, None, 0)
            
            return (True, forecast_info, df, file_size_bytes)
            
        except Exception as e:
            module_logger.error(f"Błąd pobierania/przetwarzania f{forecast_hour:03d}: {e}", exc_info=True)
            return (False, forecast_info, None, 0)
        
        finally:
            # Usuń plik tymczasowy
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

def worker_thread(queue, downloader, progress_queue, stats, thread_id=None):
    """Wątek roboczy - pobiera prognozy z kolejki"""
    if thread_id is None:
        thread_id = threading.current_thread().ident
    
    while True:
        try:
            forecast_info = queue.get(timeout=1)
            
            if forecast_info is None:
                queue.task_done()
                break
            
            forecast_hour = forecast_info['forecast_hour']
            attempt_count = 0
            
            # Powiadom o rozpoczęciu przetwarzania
            module_logger.info(f"thr: {thread_id} - Rozpoczęto pobieranie f{forecast_hour:03d}")
            progress_queue.put({
                'type': 'start',
                'forecast_hour': forecast_hour,
                'thread_id': thread_id
            })
            
            # Próba pobrania z ponawianiem
            success = False
            info = forecast_info
            df = None
            file_size_bytes = 0
            
            while attempt_count < 3:  # Maksymalnie 3 próby
                try:
                    success, info, df, file_size_bytes = downloader.download_and_process(forecast_info, progress_queue, thread_id, attempt_count)
                    if success:
                        break
                except Exception as e:
                    module_logger.warning(f"thr: {thread_id} - Błąd pobierania f{forecast_hour:03d} (próba {attempt_count + 1}): {e}")
                    if attempt_count < 2:
                        module_logger.info(f"thr: {thread_id} - Czekam 2 min. na pobranie pliku...")
                        time.sleep(120)  # Czekaj 2 minuty przed ponowną próbą
                
                attempt_count += 1
            
            if success:
                stats['success'] += 1
                stats['total_records'] += len(df) if df is not None else 0
                if 'total_bytes' not in stats:
                    stats['total_bytes'] = 0
                stats['total_bytes'] += file_size_bytes
            else:
                stats['failed'] += 1
                module_logger.error(f"thr: {thread_id} - Nie udało się pobrać f{forecast_hour:03d} po {attempt_count} próbach")
            
            # Powiadom o zakończeniu przetwarzania
            progress_queue.put({
                'type': 'done',
                'forecast_hour': info['forecast_hour'],
                'success': success,
                'total_records': len(df) if df is not None else 0,
                'file_size_bytes': file_size_bytes,
                'thread_id': thread_id
            })
            
            queue.task_done()
            
        except Empty:
            continue
        except Exception as e:
            module_logger.error(f"thr: {thread_id} - Błąd w worker_thread: {e}", exc_info=True)
            stats['failed'] += 1
            # Spróbuj oznaczyć zadanie jako zakończone, jeśli to możliwe
            try:
                queue.task_done()
            except:
                pass

    # === 8. URUCHOMIENIE POBRANIA Z AUTOMATYCZNYM PONAWIANIEM ===
    if _is_main_module:
        print(f"\n⏳ Rozpoczynam pobieranie prognoz...")
        print(f"  Używam {NUM_THREADS} wątków równolegle")
        print(f"  Priorytet: najświeższe pierwsze (f000, f001, f002...)")
        print(f"  Automatyczne ponawianie: 30s między próbami")
        print(f"  System będzie kontynuował aż wszystkie 209 prognoz będą pobrane")
        print(f"  (Naciśnij Ctrl+C aby przerwać)\n")

        # Rozpocznij pomiar czasu
        start_time = time.time()

        # Stwórz downloader
        downloader = ForecastDownloader(RUN_DATE, RUN_HOUR, lat_min, lat_max, lon_min, lon_max, engine)

        # Pętla automatycznego ponawiania
        attempt = 1
        total_success = 0
        total_failed = 0
        total_records = 0
        WAIT_BETWEEN_ATTEMPTS = 30  # sekund

        while True:
            try:
                # Sprawdź które prognozy jeszcze brakują
                existing_hours = get_existing_forecast_hours(run_time, engine)
                required_hours = get_required_forecast_hours()
                missing_hours = sorted(list(required_hours - existing_hours))
                
                if len(missing_hours) == 0:
                    print(f"\n✓✓✓ Wszystkie 209 prognoz są już pobrane!")
                    break
                
                # Jeśli to nie pierwsza próba, pokaż status
                if attempt > 1:
                    print(f"\n{'='*70}")
                    print(f"🔄 Próba #{attempt} - brakuje jeszcze {len(missing_hours)} prognoz")
                    print(f"{'='*70}")
                
                # Filtruj prognozy do pobrania (tylko te które brakują)
                forecasts_to_download_this_round = [
                    f for f in all_forecasts 
                    if f['forecast_hour'] in missing_hours
                ]
                
                if len(forecasts_to_download_this_round) == 0:
                    break
                
                print(f"\n⏳ Próba #{attempt}: Pobieranie {len(forecasts_to_download_this_round)} brakujących prognoz...")
                
                # Przygotuj kolejki i statystyki dla tej rundy
                download_queue = queue.Queue()
                progress_queue = queue.Queue()
                stats = {'success': 0, 'failed': 0, 'total_records': 0}
                currently_processing = set()
                last_completed = None
                
                # Dodaj prognozy do kolejki
                for forecast in forecasts_to_download_this_round:
                    download_queue.put(forecast)
                
                # Uruchom wątki
                threads = []
                for i in range(NUM_THREADS):
                    t = threading.Thread(target=worker_thread, args=(download_queue, downloader, progress_queue, stats, i+1))
                    t.daemon = True
                    t.start()
                    threads.append(t)
                
                # Progress bar dla tej rundy
                with tqdm(total=len(forecasts_to_download_this_round), desc=f"Runda #{attempt}", unit="prognoz", 
                          bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}') as pbar:
                    processed = 0
                    
                    while processed < len(forecasts_to_download_this_round):
                        try:
                            progress = progress_queue.get(timeout=30)
                            
                            if progress.get('type') == 'start':
                                forecast_hour = progress['forecast_hour']
                                currently_processing.add(forecast_hour)
                                
                                processing_list = sorted(list(currently_processing))[:5]
                                processing_str = ', '.join([f"f{h:03d}" for h in processing_list])
                                if len(currently_processing) > 5:
                                    processing_str += f" +{len(currently_processing) - 5}"
                                
                                pbar.set_postfix({
                                    'Teraz': processing_str if processing_str else '-',
                                    'OK': stats['success'],
                                    'FAIL': stats['failed']
                                })
                                
                            elif progress.get('type') == 'done':
                                forecast_hour = progress['forecast_hour']
                                currently_processing.discard(forecast_hour)
                                last_completed = forecast_hour
                                processed += 1
                                
                                processing_list = sorted(list(currently_processing))[:5]
                                processing_str = ', '.join([f"f{h:03d}" for h in processing_list])
                                if len(currently_processing) > 5:
                                    processing_str += f" +{len(currently_processing) - 5}"
                                
                                last_str = f"f{forecast_hour:03d}" if last_completed is not None else '-'
                                
                                if progress['success']:
                                    pbar.set_postfix({
                                        'Teraz': processing_str if processing_str else '-',
                                        'Ostatnia': last_str,
                                        'OK': stats['success'],
                                        'FAIL': stats['failed']
                                    })
                                else:
                                    pbar.set_postfix({
                                        'Teraz': processing_str if processing_str else '-',
                                        'Ostatnia': f"{last_str} (ERROR)",
                                        'OK': stats['success'],
                                        'FAIL': stats['failed']
                                    })
                                
                                pbar.update(1)
                            
                        except Empty:
                            alive = sum(1 for t in threads if t.is_alive())
                            if alive == 0:
                                break
                
                # Poczekaj na zakończenie wszystkich wątków
                for t in threads:
                    t.join(timeout=5)
                
                # Dodaj None do kolejki aby zakończyć wątki
                for _ in range(NUM_THREADS):
                    download_queue.put(None)
                
                # Zaktualizuj statystyki całkowite
                total_success += stats['success']
                total_failed += stats['failed']
                total_records += stats['total_records']
                
                # Sprawdź czy wszystkie są już pobrane
                existing_hours_after = get_existing_forecast_hours(run_time, engine)
                missing_hours_after = sorted(list(required_hours - existing_hours_after))
                
                if len(missing_hours_after) == 0:
                    print(f"\n✓✓✓ Wszystkie 209 prognoz są już pobrane!")
                    break
                
                # Jeśli nie ma nowych sukcesów, sprawdź czy warto kontynuować
                if stats['success'] == 0:
                    # Sprawdź dostępność od najniższej brakującej (dane są tworzone sukcesywnie)
                    # Jeśli nie ma f080, to na pewno nie ma też f081, f082 itd.
                    min_missing = min(missing_hours_after) if missing_hours_after else None
                    is_available = False
                    
                    if min_missing is not None:
                        # Sprawdź kilka najniższych brakujących prognoz
                        check_hours = sorted(missing_hours_after)[:5]  # Sprawdź pierwsze 5
                        for hour in check_hours:
                            if check_gfs_availability(RUN_DATE, RUN_HOUR, hour):
                                is_available = True
                                print(f"\n✓ Prognoza f{hour:03d} jest dostępna online")
                                break
                    
                    if not is_available:
                        # Brak dostępnych prognoz - poczekaj i spróbuj ponownie
                        if min_missing is not None:
                            print(f"\n⏳ Najniższa brakująca prognoza: f{min_missing:03d} - jeszcze niedostępna")
                        print(f"⏳ Czekam {WAIT_BETWEEN_ATTEMPTS}s przed następną próbą...")
                        print(f"   (Naciśnij Ctrl+C aby przerwać)")
                        time.sleep(WAIT_BETWEEN_ATTEMPTS)
                    else:
                        # Są dostępne prognozy, ale nie udało się ich pobrać - kontynuuj
                        print(f"\n⏳ Czekam {WAIT_BETWEEN_ATTEMPTS}s przed następną próbą...")
                        print(f"   (Naciśnij Ctrl+C aby przerwać)")
                        time.sleep(WAIT_BETWEEN_ATTEMPTS)
                else:
                    # Były sukcesy - kontynuuj od razu (dane są tworzone sukcesywnie)
                    print(f"\n✓ Pobrano {stats['success']} prognoz. Kontynuuję...")
                    time.sleep(2)  # Krótka przerwa przed następną próbą
                
                attempt += 1
                
            except KeyboardInterrupt:
                print(f"\n\n⚠️  Przerwano przez użytkownika (Ctrl+C)")
                print(f"   Pobrano łącznie: {total_success} prognoz w {attempt-1} próbach")
                break
            except Exception as e:
                print(f"\n⚠️  Błąd podczas pobierania: {e}")
                print(f"   Czekam {WAIT_BETWEEN_ATTEMPTS}s przed następną próbą...")
                time.sleep(WAIT_BETWEEN_ATTEMPTS)
                attempt += 1

        # Zakończ pomiar czasu
        end_time = time.time()
        elapsed_time = end_time - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)

        # Formatuj czas
        if hours > 0:
            time_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"

        # === 9. PODSUMOWANIE ===
        print("\n" + "=" * 70)
        print("✓✓✓ POBRANIE ZAKOŃCZONE!")
        print("=" * 70)
        print(f"Run GFS:          {run_time.strftime('%Y-%m-%d %H:00')} UTC")
        print(f"Prób wykonano:     {attempt-1}")
        print(f"Prognoz pobrano:   {total_success}")
        print(f"Prognoz błędów:    {total_failed}")
        print(f"Rekordów w bazie:  {total_records}")
        print(f"⏱️  Czas pobrania:   {time_str} ({elapsed_time:.1f} sekund)")
        print("=" * 70)

        # Sprawdź końcowy stan
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(DISTINCT forecast_time) as count
                    FROM gfs_forecast
                    WHERE run_time = :run_time
                """), {"run_time": run_time})
            row = result.fetchone()
            if row:
                final_count = row[0]
                print(f"\n✓ Końcowa liczba prognoz w bazie: {final_count}")
            
        except Exception as e:
            print(f"\n⚠ Nie udało się sprawdzić końcowej liczby prognoz: {e}")
            pass

        # === 10. KASOWANIE STARYCH RUNÓW (zostaw tylko 2 ostatnie) ===
        if total_success > 0:  # Tylko jeśli udało się pobrać coś
            print(f"\n⏳ Czyszczenie starych runów (zostaw tylko 2 ostatnie)...")
            
            try:
                with engine.connect() as conn:
                    # Znajdź wszystkie run_time w bazie
                    result = conn.execute(text("""
                        SELECT DISTINCT run_time
                        FROM gfs_forecast
                        ORDER BY run_time DESC
                    """))
                
                all_runs = [row[0] for row in result.fetchall()]
                
                if len(all_runs) > 2:
                    # Zachowaj tylko 2 najnowsze runy
                    runs_to_keep = sorted(all_runs, reverse=True)[:2]
                    runs_to_delete = [rt for rt in all_runs if rt not in runs_to_keep]
                    
                    if runs_to_delete:
                        # Usuń stare runy (sprzed 2 ostatnich)
                        for old_run in runs_to_delete:
                            delete_result = conn.execute(text("""
                                DELETE FROM gfs_forecast
                                WHERE run_time = :old_run
                            """), {"old_run": old_run})
                            deleted_count = delete_result.rowcount
                            print(f"  ✓ Usunięto run {old_run.strftime('%Y-%m-%d %H:00')}: {deleted_count} rekordów")
                        
                        conn.commit()
                        
                        if len(runs_to_delete) > 0:
                            print(f"✓ Usunięto {len(runs_to_delete)} starych run(ów)")
                            print(f"  Zostały tylko 2 najnowsze runy w bazie")
                else:
                    print(f"✓ W bazie jest {len(all_runs)} run(ów) - wszystko OK")
                    
            except Exception as e:
                print(f"⚠ Błąd podczas czyszczenia starych runów: {e}")
                import traceback
                traceback.print_exc()

        print("\n💡 Wszystkie dane są już zapisane w bazie!")
        print(f"   Tabela: gfs_forecast")
        print(f"   Baza: {MYSQL_DATABASE}")

        input("\nNaciśnij Enter...")

