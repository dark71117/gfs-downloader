"""
GFS Weather Data Downloader - FILTERED VERSION - DAEMON MODE
Działa ciągle, automatycznie pobiera nowe prognozy i ponawia błędne pobrania
"""

import sys
import os
import time
import configparser
import threading
import queue
import glob
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging
try:
    import pytz
except ImportError:
    pytz = None

# Import funkcji z filtered version
from gfs_downloader_filtered_fixed import (
    get_timestamp, build_grib_filter_url, download_grib_filtered,
    process_grib_to_db_filtered, get_required_forecast_hours,
    get_existing_forecast_hours, check_gfs_availability,
    wait_for_rate_limit
)

# === KONFIGURACJA LOGOWANIA ===
LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f'gfs_filtered_daemon_{datetime.now().strftime("%Y%m%d")}.log')
DETAILED_LOG_FILE = os.path.join(LOG_DIR, f'gfs_filtered_daemon_detailed_{datetime.now().strftime("%Y%m%d")}.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, f'gfs_filtered_daemon_errors_{datetime.now().strftime("%Y%m%d")}.log')

# Format logowania
log_format = '%(asctime)s - %(levelname)s - %(message)s'
date_format = '%Y-%m-%d %H:%M:%S'

logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt=date_format,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
detailed_logger = logging.getLogger('detailed')
detailed_logger.setLevel(logging.DEBUG)
detailed_handler = logging.FileHandler(DETAILED_LOG_FILE, encoding='utf-8')
detailed_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
detailed_logger.addHandler(detailed_handler)
detailed_logger.propagate = False

error_logger = logging.getLogger('errors')
error_logger.setLevel(logging.ERROR)
error_handler = logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8')
error_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
error_logger.addHandler(error_handler)
error_logger.propagate = False

# === KONFIGURACJA ===
RETRY_FAILED_INTERVAL = 120  # 2 minuty między ponawianiem błędnych pobrań

def load_config():
    """Wczytuje konfigurację z config.ini"""
    try:
        config = configparser.ConfigParser()
        config.read("config.ini", encoding='utf-8')
        
        result = {
            'mysql_user': config["database"]["user"],
            'mysql_password': config["database"]["password"],
            'mysql_host': config["database"]["host"],
            'mysql_database': config["database"]["database"],
            'lat_min': float(config["region"]["lat_min"]),
            'lat_max': float(config["region"]["lat_max"]),
            'lon_min': float(config["region"]["lon_min"]),
            'lon_max': float(config["region"]["lon_max"]),
            'num_threads': int(config.get("threading", "num_threads", fallback=6)),
        }
        
        # Wczytaj harmonogram
        schedule = {}
        if 'schedule' in config:
            for run_hour in ['00', '06', '12', '18']:
                if run_hour in config['schedule']:
                    check_time_str = config['schedule'][run_hour]
                    # Parsuj czas (format: "HH:MM")
                    try:
                        hour, minute = map(int, check_time_str.split(':'))
                        schedule[int(run_hour)] = (hour, minute)
                    except:
                        logger.warning(f"Nieprawidłowy format czasu w harmonogramie dla run {run_hour}: {check_time_str}")
        
        # Domyślny harmonogram jeśli nie ma w config.ini
        if not schedule:
            schedule = {
                0: (3, 0),   # Run 00:00 -> sprawdzaj od 03:00
                6: (9, 0),   # Run 06:00 -> sprawdzaj od 09:00
                12: (15, 0), # Run 12:00 -> sprawdzaj od 15:00
                18: (21, 0), # Run 18:00 -> sprawdzaj od 21:00
            }
        
        result['schedule'] = schedule
        result['check_interval_before'] = int(config.get("schedule", "check_interval_before", fallback=600))  # 10 min
        result['check_interval_after'] = int(config.get("schedule", "check_interval_after", fallback=60))    # 1 min
        
        # Wczytaj konfigurację CSV backup
        result['csv_backup_dir'] = config.get("csv_backup", "csv_backup_dir", fallback="temp/csv_backup")
        result['csv_keep_runs'] = int(config.get("csv_backup", "csv_keep_runs", fallback=8))  # 2 dni = 8 runów
        
        return result
    except Exception as e:
        logger.error(f"Błąd wczytywania konfiguracji: {e}")
        sys.exit(1)

def get_local_time_str(utc_time):
    """
    Konwertuje czas UTC na czas lokalny (Polska - automatycznie obsługuje czas letni/zimowy).
    Zwraca string z czasem lokalnym.
    """
    try:
        if pytz:
            # Strefa czasowa Polski (automatycznie obsługuje czas letni/zimowy)
            poland_tz = pytz.timezone('Europe/Warsaw')
            local_time = utc_time.replace(tzinfo=pytz.UTC).astimezone(poland_tz)
            return local_time.strftime('%Y-%m-%d %H:%M:%S')
    except:
        pass
    # Fallback jeśli pytz nie jest dostępne
    return utc_time.strftime('%Y-%m-%d %H:%M:%S')

def clean_old_csv_files(csv_backup_dir, keep_runs=8):
    """
    Czyści stare pliki CSV, zostawiając tylko ostatnie N runów (domyślnie 8 = 2 dni).
    """
    try:
        if not os.path.exists(csv_backup_dir):
            return
        
        # Znajdź wszystkie pliki CSV
        csv_files = glob.glob(os.path.join(csv_backup_dir, 'gfs_*.csv'))
        
        if len(csv_files) <= keep_runs * 209:  # 209 prognoz na run
            return  # Nie ma co czyścić
        
        # Wyciągnij unikalne runy z nazw plików (format: gfs_YYYYMMDD_HH_fXXX.csv)
        runs = {}
        for csv_file in csv_files:
            basename = os.path.basename(csv_file)
            # Format: gfs_YYYYMMDD_HH_fXXX.csv
            parts = basename.replace('gfs_', '').replace('.csv', '').split('_')
            if len(parts) >= 3:
                date_str = parts[0]  # YYYYMMDD
                hour_str = parts[1]   # HH
                run_key = f"{date_str}_{hour_str}"
                if run_key not in runs:
                    runs[run_key] = []
                runs[run_key].append(csv_file)
        
        # Posortuj runy po dacie (najnowsze pierwsze)
        sorted_runs = sorted(runs.items(), key=lambda x: x[0], reverse=True)
        
        # Zostaw tylko ostatnie N runów
        runs_to_keep = sorted_runs[:keep_runs]
        files_to_keep = set()
        for run_key, files in runs_to_keep:
            files_to_keep.update(files)
        
        # Usuń pliki które nie są w liście do zachowania
        deleted_count = 0
        for csv_file in csv_files:
            if csv_file not in files_to_keep:
                try:
                    os.remove(csv_file)
                    deleted_count += 1
                except:
                    pass
        
        if deleted_count > 0:
            logger.info(f"Usunięto {deleted_count} starych plików CSV (zachowano {len(files_to_keep)} plików z {keep_runs} ostatnich runów)")
    except Exception as e:
        logger.warning(f"Błąd czyszczenia starych plików CSV: {e}")

def should_check_now(now_utc, schedule):
    """
    Sprawdza czy teraz jest czas na sprawdzanie (czy minął czas z harmonogramu).
    Sprawdza TYLKO najnowszy run który powinien być dostępny (nie wszystkie runy wstecz).
    Zwraca (should_check, next_run_hour, next_run_date) lub (False, None, None).
    """
    # Znajdź najnowszy run który powinien być już dostępny (sprawdź od najnowszego)
    # Sprawdź runy dla dzisiaj i wczoraj (max 24h wstecz)
    for day_offset in [0, -1]:  # Dzisiaj i wczoraj
        check_date = (now_utc + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Sprawdź runy od najnowszego do najstarszego (18, 12, 6, 0)
        for run_hour in [18, 12, 6, 0]:
            if run_hour not in schedule:
                continue
            
            run_time = check_date.replace(hour=run_hour)
            check_hour, check_minute = schedule[run_hour]
            check_time = check_date.replace(hour=check_hour, minute=check_minute)
            
            # Jeśli minął czas sprawdzania dla tego runu
            if now_utc >= check_time:
                # Sprawdź czy to nie jest zbyt stary run (max 24h wstecz od czasu sprawdzania)
                if (now_utc - check_time).total_seconds() <= 24 * 3600:
                    # To jest najnowszy run który powinien być dostępny - zwróć go
                    return True, run_hour, run_time
    
    return False, None, None

def find_next_gfs_run_intelligent(engine):
    """
    Inteligentne znajdowanie następnego run GFS.
    GFS pojawia się co 6h (00/06/12/18 UTC) z opóźnieniem ~3h.
    Sprawdza od +3h od czasu run co 10 min aż coś się pojawi.
    """
    now_utc = datetime.utcnow()
    
    # Oblicz następny oczekiwany run
    current_hour = now_utc.hour
    next_run_hour = ((current_hour // 6) + 1) * 6
    if next_run_hour >= 24:
        next_run_hour = 0
        next_run_date = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        next_run_date = now_utc.replace(hour=next_run_hour, minute=0, second=0, microsecond=0)
    
    # Sprawdź czy już minął czas rozpoczęcia sprawdzania (+3h od run)
    check_start_time = next_run_date + timedelta(hours=3)
    
    if now_utc < check_start_time:
        # Jeszcze za wcześnie - zwróć None
        return None, None, None
    
    # Sprawdź czy run jest dostępny
    date_str = next_run_date.strftime("%Y%m%d")
    hour_str = f"{next_run_hour:02d}"
    
    if check_gfs_availability(date_str, hour_str, 0, verbose=False):
        return next_run_date, date_str, hour_str
    
    # Nie jest jeszcze dostępny
    return None, None, None

def find_latest_gfs_run_with_retry(engine):
    """
    Znajduje najnowszy dostępny run GFS, sprawdzając również czy nie ma nowszych.
    WAŻNE: Sprawdza dostępność pierwszej BRAKUJĄCEJ prognozy, nie tylko f000!
    """
    now_utc = datetime.utcnow()
    
    # Sprawdź ostatni run w bazie
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
    
    # Sprawdź ostatnie 4 runy (ostatnie 24h)
    for i in range(4):
        check_time = now_utc.replace(hour=((now_utc.hour // 6) * 6), minute=0, second=0, microsecond=0) - timedelta(hours=i * 6)
        if check_time.hour not in [0, 6, 12, 18]:
            continue
        
        # Pomiń runy starsze niż 48h - prawdopodobnie już nie są dostępne na serwerze
        age_hours = (now_utc - check_time).total_seconds() / 3600
        if age_hours > 48:
            logger.debug(f"Run {check_time.strftime('%Y-%m-%d %H:00')} UTC jest za stary ({age_hours:.1f}h) - pomijam")
            continue
        
        date_str = check_time.strftime("%Y%m%d")
        hour_str = f"{check_time.hour:02d}"
        
        # ZAWSZE sprawdź które prognozy są już w bazie dla tego runu
        try:
            existing_hours = get_existing_forecast_hours(check_time, engine)
            required_hours = get_required_forecast_hours()
            missing_hours = sorted(list(required_hours - existing_hours))
            
            if len(missing_hours) == 0:
                # Wszystkie prognozy są już pobrane - pomiń ten run
                logger.debug(f"Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - wszystkie prognozy już pobrane, pomijam")
                continue
            
            # Ten run ma brakujące prognozy - sprawdź czy są jeszcze dostępne na serwerze
            # Sprawdź dostępność pierwszej BRAKUJĄCEJ prognozy (nie f000!)
            first_missing_hour = missing_hours[0]
            logger.info(f"Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - brakuje {len(missing_hours)} prognoz (pierwsza brakująca: f{first_missing_hour:03d})")
            
            if check_gfs_availability(date_str, hour_str, first_missing_hour, verbose=False):
                # Brakujące prognozy są dostępne - możemy kontynuować pobieranie
                logger.info(f"✓ Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - brakujące prognozy są dostępne na serwerze")
                return check_time, date_str, hour_str
            else:
                # Brakujące prognozy nie są już dostępne na serwerze - pomiń ten run
                logger.info(f"✗ Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - brakujące prognozy (f{first_missing_hour:03d}) nie są już dostępne na serwerze - pomijam")
                continue
                
        except Exception as e:
            logger.warning(f"Błąd sprawdzania prognoz dla run {check_time.strftime('%Y-%m-%d %H:00')} UTC: {e}")
            # W przypadku błędu, sprawdź dostępność f000 jako fallback
            if check_gfs_availability(date_str, hour_str, 0, verbose=False):
                return check_time, date_str, hour_str
            continue
    
    return None, None, None

def download_forecast_with_retry(forecast_hour, RUN_DATE, RUN_HOUR, run_time, lat_min, lat_max, lon_min, lon_max, engine, temp_dir, params_config=None, cfgrib_to_config=None, csv_backup_dir=None, max_retries=10):
    """
    Pobiera jedną prognozę z automatycznym ponawianiem do skutku.
    Zwraca (success, records, file_size_bytes).
    """
    url = build_grib_filter_url(RUN_DATE, RUN_HOUR, forecast_hour, params_config=params_config)
    temp_file = os.path.join(temp_dir, f"gfs_f{forecast_hour:03d}_filtered.grb2")
    
    for attempt in range(max_retries):
        try:
            # Pobierz plik (przekaż date_str i hour_str dla fallback)
            success, file_size = download_grib_filtered(url, temp_file, forecast_hour=forecast_hour, hour_str=RUN_HOUR, resolution='0p25', params_config=params_config)
            
            if not success:
                if attempt < max_retries - 1:
                    logger.info(f"[f{forecast_hour:03d}] Próba {attempt+1}/{max_retries} nieudana, ponawiam za {RETRY_FAILED_INTERVAL}s...")
                    time.sleep(RETRY_FAILED_INTERVAL)
                    continue
                return False, 0, 0
            
            # Przetwórz i zapisz
            num_records = process_grib_to_db_filtered(
                temp_file, run_time, forecast_hour,
                lat_min, lat_max, lon_min, lon_max, engine,
                params_config, cfgrib_to_config, csv_backup_dir
            )
            
            # Usuń plik tymczasowy
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass
            
            if num_records > 0:
                return True, num_records, file_size
            else:
                # Brak rekordów - może plik był pusty, spróbuj ponownie
                if attempt < max_retries - 1:
                    logger.warning(f"[f{forecast_hour:03d}] Brak rekordów, ponawiam za {RETRY_FAILED_INTERVAL}s...")
                    time.sleep(RETRY_FAILED_INTERVAL)
                    continue
                return False, 0, file_size
                
        except Exception as e:
            logger.error(f"[f{forecast_hour:03d}] Błąd w próbie {attempt+1}: {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_FAILED_INTERVAL)
                continue
            return False, 0, 0
    
    return False, 0, 0

def download_all_forecasts(run_time, RUN_DATE, RUN_HOUR, config, engine):
    """
    Pobiera wszystkie prognozy dla danego run z automatycznym ponawianiem błędnych.
    """
    logger.info(f"Rozpoczynam pobieranie prognoz dla run {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    
    # Wczytaj konfigurację parametrów
    from gfs_downloader_filtered_fixed import load_parameters_config
    params_config, cfgrib_to_config = load_parameters_config()
    
    temp_dir = "temp_grib_filtered"
    os.makedirs(temp_dir, exist_ok=True)
    
    required_hours = get_required_forecast_hours()
    total_success = 0
    total_failed = 0
    total_records = 0
    total_bytes = 0
    
    while True:
        # Sprawdź które prognozy jeszcze brakują
        existing_hours = get_existing_forecast_hours(run_time, engine)
        missing_hours = sorted(list(required_hours - existing_hours))
        
        if len(missing_hours) == 0:
            logger.info("✓✓✓ Wszystkie 209 prognoz są już pobrane!")
            break
        
        logger.info(f"Brakuje {len(missing_hours)} prognoz, pobieram używając {config['num_threads']} wątków...")
        
        # MULTI-THREADING: Pobierz brakujące prognozy równolegle
        import queue as queue_module
        download_queue = queue_module.Queue()
        progress_queue = queue_module.Queue()
        stats = {'success': 0, 'failed': 0, 'records': 0, 'bytes': 0}
        
        # Dodaj prognozy do kolejki
        for forecast_hour in missing_hours:
            download_queue.put(forecast_hour)
        
        # Funkcja worker thread
        def worker_thread():
            while True:
                try:
                    forecast_hour = download_queue.get(timeout=1)
                    if forecast_hour is None:
                        break
                    
                    success, records, file_size = download_forecast_with_retry(
                        forecast_hour, RUN_DATE, RUN_HOUR, run_time,
                        config['lat_min'], config['lat_max'],
                        config['lon_min'], config['lon_max'],
                        engine, temp_dir, params_config, cfgrib_to_config,
                        config.get('csv_backup_dir', 'temp/csv_backup')
                    )
                    
                    progress_queue.put({
                        'forecast_hour': forecast_hour,
                        'success': success,
                        'records': records,
                        'file_size': file_size
                    })
                    
                    download_queue.task_done()
                except queue_module.Empty:
                    break
                except Exception as e:
                    logger.error(f"Błąd w worker thread: {e}", exc_info=True)
                    progress_queue.put({
                        'forecast_hour': forecast_hour if 'forecast_hour' in locals() else -1,
                        'success': False,
                        'records': 0,
                        'file_size': 0
                    })
                    download_queue.task_done()
        
        # Uruchom wątki
        threads = []
        for i in range(config['num_threads']):
            t = threading.Thread(target=worker_thread, daemon=True)
            t.start()
            threads.append(t)
            logger.info(f"Wątek #{i+1} uruchomiony (ID: {t.ident})")
        
        # Przetwarzaj wyniki
        completed = 0
        while completed < len(missing_hours):
            try:
                progress = progress_queue.get(timeout=5)
                completed += 1
                
                if progress['success']:
                    stats['success'] += 1
                    stats['records'] += progress['records']
                    stats['bytes'] += progress['file_size']
                    logger.info(f"✓ [f{progress['forecast_hour']:03d}] Pobrano ({progress['records']} rekordów, {progress['file_size']/(1024*1024):.1f} MB)")
                else:
                    stats['failed'] += 1
                    logger.warning(f"✗ [f{progress['forecast_hour']:03d}] Nie udało się pobrać po wszystkich próbach")
            except queue_module.Empty:
                # Sprawdź czy wątki jeszcze działają
                alive = sum(1 for t in threads if t.is_alive())
                if alive == 0:
                    break
        
        # Zakończ wątki
        for _ in range(config['num_threads']):
            download_queue.put(None)
        for t in threads:
            t.join(timeout=5)
        
        total_success = stats['success']
        total_failed = stats['failed']
        total_records = stats['records']
        total_bytes = stats['bytes']
        
        # Jeśli były błędy, poczekaj przed ponowną próbą
        if total_failed > 0:
            logger.info(f"Ponawiam {total_failed} błędnych pobrań za {RETRY_FAILED_INTERVAL}s...")
            time.sleep(RETRY_FAILED_INTERVAL)
            total_failed = 0  # Reset licznika
    
    total_mb = total_bytes / (1024 * 1024)
    logger.info(f"📊 STATYSTYKI: Pobrano {total_success} plików, łącznie {total_mb:.2f} MB danych, {total_records} rekordów w bazie")
    
    return total_success, total_failed, total_records, total_bytes

def main_daemon_loop():
    """Główna pętla daemona"""
    logger.info("=" * 70)
    logger.info("GFS Weather Data Downloader - FILTERED VERSION - DAEMON MODE")
    logger.info("=" * 70)
    
    # Wczytaj konfigurację
    config = load_config()
    
    try:
        MYSQL_URL = f"mysql+pymysql://{config['mysql_user']}:{config['mysql_password']}@{config['mysql_host']}/{config['mysql_database']}?charset=utf8mb4"
        engine = create_engine(MYSQL_URL, echo=False, pool_pre_ping=True)
        
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        logger.info(f"✓ Połączono z bazą: {config['mysql_database']}")
        logger.info(f"✓ Harmonogram sprawdzania:")
        for run_hour, (check_hour, check_min) in sorted(config['schedule'].items()):
            logger.info(f"   Run {run_hour:02d}:00 UTC -> sprawdzaj od {check_hour:02d}:{check_min:02d} UTC")
        
    except Exception as e:
        logger.error(f"Błąd konfiguracji: {e}")
        sys.exit(1)
    
    logger.info("\n🚀 Daemon uruchomiony. Działa w tle...")
    logger.info("   (Naciśnij Ctrl+C aby zatrzymać)\n")
    
    schedule = config['schedule']
    check_interval_before = config['check_interval_before']  # 10 minut
    check_interval_after = config['check_interval_after']    # 1 minuta
    
    try:
        while True:
            current_time = datetime.utcnow()
            
            # Sprawdź czy teraz jest czas na sprawdzanie (na podstawie harmonogramu)
            should_check, next_run_hour, next_run_date = should_check_now(current_time, schedule)
            
            if should_check:
                local_time_str = get_local_time_str(current_time)
                logger.info(f"\n{'='*70}")
                logger.info(f"Sprawdzam dostępność nowych prognoz GFS... ({current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC / {local_time_str} lokalny)")
                logger.info(f"{'='*70}\n")
                
                # Znajdź run do pobrania (sprawdź czy są brakujące prognozy w istniejących runach)
                run_time, RUN_DATE, RUN_HOUR = find_latest_gfs_run_with_retry(engine)
                
                if run_time:
                    logger.info(f"✓ Znaleziono run do pobrania: {run_time.strftime('%Y-%m-%d %H:00')} UTC")
                    
                    # Pobierz wszystkie prognozy (z automatycznym ponawianiem do skutku)
                    success, failed, records, bytes_downloaded = download_all_forecasts(
                        run_time, RUN_DATE, RUN_HOUR, config, engine
                    )
                    
                    mb_downloaded = bytes_downloaded / (1024 * 1024)
                    logger.info(f"✓✓✓ Pobieranie zakończone: {success} sukcesów, {failed} błędów")
                    logger.info(f"📊 STATYSTYKI: Pobrano {success} plików, łącznie {mb_downloaded:.2f} MB danych, {records} rekordów w bazie")
                    
                    # Wyczyść stare pliki CSV
                    clean_old_csv_files(config['csv_backup_dir'], config['csv_keep_runs'])
                    
                    # Po zakończeniu run, sprawdź za check_interval_after (1 min)
                    next_check = current_time + timedelta(seconds=check_interval_after)
                    logger.info(f"\nNastępne sprawdzenie za {check_interval_after/60:.0f} minut ({next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC)...\n")
                    time.sleep(check_interval_after)
                    continue
                else:
                    # Brak nowych runów - sprawdź za check_interval_before (10 min)
                    next_check = current_time + timedelta(seconds=check_interval_before)
                    logger.info(f"Brak nowych runów. Następne sprawdzenie: {next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC (za {check_interval_before/60:.0f} min)")
                    time.sleep(check_interval_before)
                    continue
            
            # Czekaj 1 minutę przed następnym sprawdzeniem
            time.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("\n⚠️  Zatrzymywanie daemona...")
    except Exception as e:
        logger.error(f"Błąd w głównej pętli: {e}", exc_info=True)
        error_logger.error(f"Błąd w głównej pętli daemona: {e}", exc_info=True)
    finally:
        logger.info("Daemon zakończony")

if __name__ == "__main__":
    main_daemon_loop()

