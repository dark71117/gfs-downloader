"""
GFS Weather Data Downloader - FILTERED VERSION - DAEMON MODE
Działa ciągle, automatycznie pobiera nowe prognozy i ponawia błędne pobrania
"""

import sys
import os
import time
import configparser
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging

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
CHECK_INTERVAL = 1800  # 30 minut między sprawdzaniami nowych runów
RETRY_FAILED_INTERVAL = 120  # 2 minuty między ponawianiem błędnych pobrań
INTELLIGENT_CHECK_START_OFFSET = 3  # Sprawdzaj od +3h od czasu run (00->03, 06->09, 12->15, 18->21)
INTELLIGENT_CHECK_INTERVAL = 600  # 10 minut między sprawdzaniami podczas oczekiwania na nowy run

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
    check_start_time = next_run_date + timedelta(hours=INTELLIGENT_CHECK_START_OFFSET)
    
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
        
        date_str = check_time.strftime("%Y%m%d")
        hour_str = f"{check_time.hour:02d}"
        
        if last_run_in_db and check_time <= last_run_in_db:
            # Sprawdź czy ten run ma wszystkie prognozy
            try:
                existing_hours = get_existing_forecast_hours(check_time, engine)
                required_hours = get_required_forecast_hours()
                missing_hours = required_hours - existing_hours
                
                if len(missing_hours) > 0:
                    # Ten run ma brakujące prognozy
                    return check_time, date_str, hour_str
            except:
                pass
            continue
        
        # Sprawdź czy run jest dostępny
        if check_gfs_availability(date_str, hour_str, 0, verbose=False):
            return check_time, date_str, hour_str
    
    return None, None, None

def download_forecast_with_retry(forecast_hour, RUN_DATE, RUN_HOUR, run_time, lat_min, lat_max, lon_min, lon_max, engine, temp_dir, max_retries=10):
    """
    Pobiera jedną prognozę z automatycznym ponawianiem do skutku.
    Zwraca (success, records, file_size_bytes).
    """
    url = build_grib_filter_url(RUN_DATE, RUN_HOUR, forecast_hour)
    temp_file = os.path.join(temp_dir, f"gfs_f{forecast_hour:03d}_filtered.grb2")
    
    for attempt in range(max_retries):
        try:
            # Pobierz plik
            success, file_size = download_grib_filtered(url, temp_file, forecast_hour=forecast_hour)
            
            if not success:
                if attempt < max_retries - 1:
                    logger.info(f"[f{forecast_hour:03d}] Próba {attempt+1}/{max_retries} nieudana, ponawiam za {RETRY_FAILED_INTERVAL}s...")
                    time.sleep(RETRY_FAILED_INTERVAL)
                    continue
                return False, 0, 0
            
            # Przetwórz i zapisz
            num_records = process_grib_to_db_filtered(
                temp_file, run_time, forecast_hour,
                lat_min, lat_max, lon_min, lon_max, engine
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
        
        logger.info(f"Brakuje {len(missing_hours)} prognoz, pobieram...")
        
        # Pobierz brakujące prognozy (pojedynczo, z automatycznym ponawianiem)
        for forecast_hour in missing_hours:
            success, records, file_size = download_forecast_with_retry(
                forecast_hour, RUN_DATE, RUN_HOUR, run_time,
                config['lat_min'], config['lat_max'],
                config['lon_min'], config['lon_max'],
                engine, temp_dir
            )
            
            if success:
                total_success += 1
                total_records += records
                total_bytes += file_size
                logger.info(f"✓ [f{forecast_hour:03d}] Pobrano ({records} rekordów, {file_size/(1024*1024):.1f} MB)")
            else:
                total_failed += 1
                logger.warning(f"✗ [f{forecast_hour:03d}] Nie udało się pobrać po wszystkich próbach")
        
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
    try:
        config_parser = configparser.ConfigParser()
        config_parser.read("config.ini", encoding='utf-8')
        
        config = {
            'user': config_parser["database"]["user"],
            'password': config_parser["database"]["password"],
            'host': config_parser["database"]["host"],
            'database': config_parser["database"]["database"],
            'lat_min': float(config_parser["region"]["lat_min"]),
            'lat_max': float(config_parser["region"]["lat_max"]),
            'lon_min': float(config_parser["region"]["lon_min"]),
            'lon_max': float(config_parser["region"]["lon_max"]),
        }
        
        MYSQL_URL = f"mysql+pymysql://{config['user']}:{config['password']}@{config['host']}/{config['database']}?charset=utf8mb4"
        engine = create_engine(MYSQL_URL, echo=False, pool_pre_ping=True)
        
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        logger.info(f"✓ Połączono z bazą: {config['database']}")
        
    except Exception as e:
        logger.error(f"Błąd konfiguracji: {e}")
        sys.exit(1)
    
    logger.info("\n🚀 Daemon uruchomiony. Działa w tle...")
    logger.info("   (Naciśnij Ctrl+C aby zatrzymać)\n")
    
    last_check_time = None
    last_run_completed = None
    
    try:
        while True:
            current_time = datetime.utcnow()
            
            # Sprawdź czy minął interwał sprawdzania (30 min po zakończeniu poprzedniego run)
            should_check = False
            if last_check_time is None:
                should_check = True
            elif last_run_completed:
                # Po zakończeniu run, sprawdź po 30 minutach
                if (current_time - last_run_completed).total_seconds() >= CHECK_INTERVAL:
                    should_check = True
            else:
                # Normalne sprawdzanie co 30 minut
                if (current_time - last_check_time).total_seconds() >= CHECK_INTERVAL:
                    should_check = True
            
            if should_check:
                logger.info(f"\n{'='*70}")
                logger.info(f"Sprawdzam dostępność nowych prognoz GFS... ({current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
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
                    last_run_completed = current_time
                    last_check_time = current_time
                    
                    # Po zakończeniu run, następne sprawdzenie za 30 minut
                    next_check = current_time + timedelta(seconds=CHECK_INTERVAL)
                    logger.info(f"\nNastępne sprawdzenie za {CHECK_INTERVAL/60:.0f} minut ({next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC)...\n")
                else:
                    # Sprawdź inteligentnie czy nie ma nowego run (sprawdza od +3h od czasu run co 10 min)
                    next_run, next_date, next_hour = find_next_gfs_run_intelligent(engine)
                    
                    if next_run:
                        logger.info(f"✓ Znaleziono nowy run: {next_run.strftime('%Y-%m-%d %H:00')} UTC")
                        success, failed, records, bytes_downloaded = download_all_forecasts(
                            next_run, next_date, next_hour, config, engine
                        )
                        mb_downloaded = bytes_downloaded / (1024 * 1024)
                        logger.info(f"✓✓✓ Pobieranie zakończone: {success} sukcesów, {failed} błędów")
                        logger.info(f"📊 STATYSTYKI: Pobrano {success} plików, łącznie {mb_downloaded:.2f} MB danych, {records} rekordów w bazie")
                        last_run_completed = current_time
                        last_check_time = current_time
                        
                        # Po zakończeniu run, następne sprawdzenie za 30 minut
                        next_check = current_time + timedelta(seconds=CHECK_INTERVAL)
                        logger.info(f"\nNastępne sprawdzenie za {CHECK_INTERVAL/60:.0f} minut ({next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC)...\n")
                    else:
                        # Brak nowych runów - sprawdź za 10 minut (inteligentne oczekiwanie)
                        next_check = current_time + timedelta(seconds=INTELLIGENT_CHECK_INTERVAL)
                        logger.info(f"Brak nowych runów. Następne sprawdzenie: {next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC (za {INTELLIGENT_CHECK_INTERVAL/60:.0f} min)")
                        last_check_time = current_time
                        time.sleep(INTELLIGENT_CHECK_INTERVAL)
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

