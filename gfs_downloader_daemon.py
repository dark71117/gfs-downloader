"""
GFS Weather Data Downloader - DAEMON VERSION
Działa w tle, automatycznie sprawdza co 20 minut czy pojawiły się nowe dane GFS
i pobiera je gdy są dostępne.
"""

import sys
import os
import time
import logging
from datetime import datetime, timedelta
import configparser
from sqlalchemy import create_engine, text
import requests

import threading
import queue
from queue import Empty
import warnings
warnings.filterwarnings('ignore')

# Importujemy funkcje z professional version bezpośrednio
# Dodaj katalog do ścieżki Python, żeby móc zaimportować moduł
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Ustaw flagę przed importem, żeby główny kod się nie wykonał
import builtins
builtins.__imported_by_daemon__ = True

# Importuj moduł - kod w if __name__ == "__main__": się nie wykona
# bo mamy ustawioną flagę __imported_by_daemon__
try:
    import gfs_downloader_professional as gfs_professional
    logger_temp = logging.getLogger(__name__)
    logger_temp.info("Moduł gfs_downloader_professional zaimportowany pomyślnie")
except Exception as e:
    # Jeśli logger jeszcze nie istnieje, użyj print
    print(f"BŁĄD importu modułu gfs_downloader_professional: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# === KONFIGURACJA LOGOWANIA ===
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Główny plik logów (codzienny)
LOG_FILE = os.path.join(LOG_DIR, f"gfs_daemon_{datetime.now().strftime('%Y%m%d')}.log")

# Szczegółowy plik logów z wszystkimi operacjami
DETAILED_LOG_FILE = os.path.join(LOG_DIR, f"gfs_daemon_detailed_{datetime.now().strftime('%Y%m%d')}.log")

# Plik logów z błędami
ERROR_LOG_FILE = os.path.join(LOG_DIR, f"gfs_daemon_errors_{datetime.now().strftime('%Y%m%d')}.log")

# Wycisz logi DEBUG z bibliotek zewnętrznych (przed konfiguracją głównego loggera)
logging.getLogger('cfgrib').setLevel(logging.WARNING)
logging.getLogger('ecmwf').setLevel(logging.WARNING)
logging.getLogger('eccodes').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

# Konfiguracja głównego loggera (konsola + główny plik)
logging.basicConfig(
    level=logging.INFO,  # Zmieniono na INFO - DEBUG tylko dla naszego kodu
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # INFO dla głównego loggera

# Szczegółowy logger (wszystkie operacje)
detailed_logger = logging.getLogger('detailed')
detailed_logger.setLevel(logging.DEBUG)
detailed_handler = logging.FileHandler(DETAILED_LOG_FILE, encoding='utf-8')
detailed_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
detailed_logger.addHandler(detailed_handler)
detailed_logger.propagate = False

# Logger błędów
error_logger = logging.getLogger('errors')
error_logger.setLevel(logging.ERROR)
error_handler = logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8')
error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
error_logger.addHandler(error_handler)
error_logger.propagate = False

# === KONFIGURACJA ===
CHECK_INTERVAL = 1200  # 20 minut w sekundach
WAIT_BETWEEN_ATTEMPTS = 60  # sekund między próbami pobierania

def load_config():
    """Wczytuje konfigurację z config.ini"""
    try:
        config = configparser.ConfigParser()
        config.read("config.ini", encoding='utf-8')
        
        return {
            'mysql_user': config["database"]["user"],
            'mysql_password': config["database"]["password"],
            'mysql_host': config["database"]["host"],
            'mysql_database': config["database"]["database"],
            'lat_min': float(config["region"]["lat_min"]),
            'lat_max': float(config["region"]["lat_max"]),
            'lon_min': float(config["region"]["lon_min"]),
            'lon_max': float(config["region"]["lon_max"]),
            'num_threads': 6
        }
    except Exception as e:
        logger.error(f"Błąd wczytywania konfiguracji: {e}")
        sys.exit(1)

def check_for_new_run(engine, last_run_in_db=None):
    """
    Sprawdza czy pojawił się nowy run GFS (sprawdza f000).
    Zoptymalizowane: najpierw sprawdza bazę i pomija już kompletne runy.
    Zwraca (run_time, RUN_DATE, RUN_HOUR) jeśli znaleziono nowy run, None w przeciwnym razie.
    """
    now_utc = datetime.utcnow()
    current_run_hour = (now_utc.hour // 6) * 6
    run_time = now_utc.replace(hour=current_run_hour, minute=0, second=0, microsecond=0)
    
    detailed_logger.info(f"=== SPRAWDZANIE NOWYCH RUN GFS ===")
    detailed_logger.info(f"Czas sprawdzenia: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    detailed_logger.info(f"Aktualny run (teoretyczny): {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    
    # Sprawdź najnowszy run w bazie i które runy są już kompletne
    # ZAWSZE sprawdzamy bazę, żeby mieć aktualne informacje o kompletnych runach
    complete_runs = set()  # Runy które mają wszystkie 209 prognoz
    try:
        with engine.connect() as conn:
            # Pobierz wszystkie runy z bazy i sprawdź które są kompletne
            result = conn.execute(text("""
                SELECT DISTINCT run_time
                FROM gfs_forecast
                ORDER BY run_time DESC
            """))
            all_runs_in_db = []
            for row in result:
                run_time_db = row[0]
                if isinstance(run_time_db, str):
                    try:
                        run_time_db = datetime.strptime(run_time_db, '%Y-%m-%d %H:%M:%S')
                    except:
                        try:
                            run_time_db = datetime.strptime(run_time_db, '%Y-%m-%d %H:%M')
                        except:
                            continue
                all_runs_in_db.append(run_time_db)
            
            if all_runs_in_db:
                # Zaktualizuj last_run_in_db jeśli jest None lub jeśli w bazie jest nowszy
                max_run_in_db = max(all_runs_in_db)
                if last_run_in_db is None:
                    last_run_in_db = max_run_in_db
                else:
                    # Sprawdź czy w bazie jest nowszy run
                    if isinstance(last_run_in_db, datetime):
                        last_run_normalized = last_run_in_db.replace(microsecond=0, second=0)
                    else:
                        last_run_normalized = last_run_in_db
                    max_run_normalized = max_run_in_db.replace(microsecond=0, second=0) if isinstance(max_run_in_db, datetime) else max_run_in_db
                    if max_run_normalized > last_run_normalized:
                        last_run_in_db = max_run_in_db
                
                detailed_logger.info(f"Ostatni run w bazie: {last_run_in_db}")
                
                # Sprawdź które runy są kompletne (mają wszystkie 209 prognoz)
                required_hours = gfs_professional.get_required_forecast_hours()
                for run_time_db in all_runs_in_db:
                    try:
                        existing_hours = gfs_professional.get_existing_forecast_hours(run_time_db, engine)
                        missing_hours = required_hours - existing_hours
                        if len(missing_hours) == 0:
                            run_time_normalized = run_time_db.replace(microsecond=0, second=0) if isinstance(run_time_db, datetime) else run_time_db
                            complete_runs.add(run_time_normalized)
                            detailed_logger.info(f"  ✓ Run {run_time_db.strftime('%Y-%m-%d %H:00')} UTC - kompletny (209/209 prognoz)")
                    except Exception as e:
                        detailed_logger.debug(f"  Błąd sprawdzania kompletności run {run_time_db}: {e}")
            else:
                detailed_logger.info("Brak runów w bazie")
                last_run_in_db = None
    except Exception as e:
        detailed_logger.warning(f"Błąd sprawdzania bazy: {e}")
        error_logger.error(f"Błąd sprawdzania ostatniego run w bazie: {e}", exc_info=True)
    
    # Sprawdź do 6 runów wstecz (36h)
    checked_runs = []
    skipped_complete = 0
    
    for i in range(6):
        check_time = run_time - timedelta(hours=i * 6)
        date_str = check_time.strftime("%Y%m%d")
        hour_str = f"{check_time.hour:02d}"
        check_time_normalized = check_time.replace(microsecond=0, second=0)
        
        # NAJPIERW sprawdź bazę - jeśli run jest kompletny, pomiń sprawdzanie online
        if check_time_normalized in complete_runs:
            skipped_complete += 1
            detailed_logger.info(f"  ⊘ Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - POMINIĘTY (już kompletny w bazie)")
            continue
        
        # Jeśli run jest starszy niż ostatni w bazie i jest kompletny, pomiń
        if last_run_in_db is not None:
            if isinstance(last_run_in_db, datetime):
                last_run_normalized = last_run_in_db.replace(microsecond=0, second=0)
            else:
                last_run_normalized = last_run_in_db
            
            if check_time_normalized < last_run_normalized:
                # Sprawdź czy ten starszy run jest kompletny
                try:
                    existing_hours = gfs_professional.get_existing_forecast_hours(check_time, engine)
                    required_hours = gfs_professional.get_required_forecast_hours()
                    missing_hours = required_hours - existing_hours
                    if len(missing_hours) == 0:
                        skipped_complete += 1
                        detailed_logger.info(f"  ⊘ Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - POMINIĘTY (starszy i kompletny)")
                        continue
                except:
                    pass  # W przypadku błędu, sprawdź online
        
        # Tylko teraz sprawdź dostępność online (tylko dla runów które mogą być potrzebne)
        detailed_logger.info(f"Sprawdzam run: {check_time.strftime('%Y-%m-%d %H:00')} UTC (f000)")
        
        # Sprawdź dostępność f000 (pierwsza prognoza) - sprawdza oba serwery
        is_available = gfs_professional.check_gfs_availability(date_str, hour_str, 0)
        checked_runs.append({
            'run_time': check_time,
            'available': is_available
        })
        
        if is_available:
            detailed_logger.info(f"  ✓ Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - f000 DOSTĘPNA")
            
            # Jeśli nie mamy run w bazie, zwróć pierwszy dostępny
            if last_run_in_db is None:
                logger.info(f"Znaleziono pierwszy dostępny run: {check_time.strftime('%Y-%m-%d %H:00')} UTC")
                detailed_logger.info(f"  → Wybrano: {check_time.strftime('%Y-%m-%d %H:00')} UTC (pierwszy dostępny)")
                return check_time, date_str, hour_str, last_run_in_db
            
            # Normalizuj daty do porównania
            if isinstance(last_run_in_db, datetime):
                last_run_normalized = last_run_in_db.replace(microsecond=0, second=0)
            else:
                last_run_normalized = last_run_in_db
            
            # Jeśli ten run jest nowszy niż w bazie, zwróć go
            if check_time_normalized > last_run_normalized:
                logger.info(f"Znaleziono nowszy run: {check_time.strftime('%Y-%m-%d %H:00')} UTC (poprzedni: {last_run_in_db})")
                detailed_logger.info(f"  → Wybrano: {check_time.strftime('%Y-%m-%d %H:00')} UTC (nowszy niż w bazie: {last_run_in_db})")
                return check_time, date_str, hour_str, last_run_in_db
            
            # Jeśli ten sam run, sprawdź czy ma wszystkie prognozy
            if check_time_normalized == last_run_normalized:
                try:
                    existing_hours = gfs_professional.get_existing_forecast_hours(check_time, engine)
                    required_hours = gfs_professional.get_required_forecast_hours()
                    missing_hours = required_hours - existing_hours
                    
                    if len(missing_hours) == 0:
                        # Wszystkie prognozy są już pobrane
                        detailed_logger.info(f"  → Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - wszystkie 209 prognoz już pobrane")
                        return None, None, None, last_run_in_db
                    else:
                        # Ten sam run, ale brakuje niektórych prognoz
                        missing_list = sorted(list(missing_hours))[:10]
                        missing_str = ', '.join([f"f{h:03d}" for h in missing_list])
                        if len(missing_hours) > 10:
                            missing_str += f" ... i {len(missing_hours) - 10} więcej"
                        logger.info(f"Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - brakuje {len(missing_hours)} prognoz")
                        detailed_logger.info(f"  → Wybrano: {check_time.strftime('%Y-%m-%d %H:00')} UTC - brakuje {len(missing_hours)} prognoz: {missing_str}")
                        return check_time, date_str, hour_str, last_run_in_db
                except Exception as e:
                    detailed_logger.warning(f"  → Błąd sprawdzania prognoz dla {check_time.strftime('%Y-%m-%d %H:00')} UTC: {e}")
                    error_logger.error(f"Błąd sprawdzania prognoz dla run {check_time}: {e}", exc_info=True)
                    return check_time, date_str, hour_str, last_run_in_db
        else:
            detailed_logger.info(f"  ✗ Run {check_time.strftime('%Y-%m-%d %H:00')} UTC - f000 NIEDOSTĘPNA")
    
    # Podsumowanie sprawdzeń
    available_runs = [r for r in checked_runs if r['available']]
    detailed_logger.info(f"Podsumowanie: Sprawdzono {len(checked_runs)} runów online, {skipped_complete} pominiętych (już kompletne), {len(available_runs)} dostępnych")
    if skipped_complete > 0:
        logger.info(f"Pominięto {skipped_complete} już kompletnych run(ów) - nie sprawdzano online")
    detailed_logger.info(f"Brak nowych runów do pobrania")
    
    return None, None, None, last_run_in_db

def download_forecasts(run_time, RUN_DATE, RUN_HOUR, config, engine):
    """
    Pobiera wszystkie prognozy dla danego run.
    Używa tej samej logiki co professional version z automatycznym ponawianiem.
    """
    logger.info(f"Rozpoczynam pobieranie prognoz dla run {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    detailed_logger.info(f"Rozpoczynam pobieranie prognoz dla run {run_time.strftime('%Y-%m-%d %H:00')} UTC")
    
    # Przygotowanie katalogów
    csv_backup_dir = os.path.join('temp', 'csv_backup')
    if not os.path.exists(csv_backup_dir):
        os.makedirs(csv_backup_dir)
        logger.info(f"Przygotowanie katalogu dla CSV backup...")
        detailed_logger.info(f"Przygotowanie katalogu dla CSV backup: {csv_backup_dir}")
    
    temp_dir = 'temp'
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        logger.info(f"Przygotowanie katalogu dla plików tymczasowych...")
        detailed_logger.info(f"Przygotowanie katalogu dla plików tymczasowych: {temp_dir}")
    
    try:
        logger.debug("Tworzenie ForecastDownloader...")
        downloader = gfs_professional.ForecastDownloader(RUN_DATE, RUN_HOUR, config['lat_min'], config['lat_max'], 
                                        config['lon_min'], config['lon_max'], engine)
        logger.debug("ForecastDownloader utworzony")
    except Exception as e:
        logger.error(f"Błąd tworzenia ForecastDownloader: {e}", exc_info=True)
        error_logger.error(f"Błąd tworzenia ForecastDownloader: {e}", exc_info=True)
        raise
    
    try:
        logger.debug("Pobieranie wymaganych godzin prognoz...")
        required_hours = gfs_professional.get_required_forecast_hours()
        logger.debug(f"Wymagane godziny: {len(required_hours)} prognoz")
    except Exception as e:
        logger.error(f"Błąd pobierania wymaganych godzin: {e}", exc_info=True)
        error_logger.error(f"Błąd pobierania wymaganych godzin: {e}", exc_info=True)
        raise
    
    try:
        logger.debug("Generowanie listy prognoz...")
        all_forecasts = gfs_professional.generate_forecast_list(run_time)
        logger.debug(f"Wygenerowano {len(all_forecasts)} prognoz")
    except Exception as e:
        logger.error(f"Błąd generowania listy prognoz: {e}", exc_info=True)
        error_logger.error(f"Błąd generowania listy prognoz: {e}", exc_info=True)
        raise
    
    attempt = 1
    total_success = 0
    total_failed = 0
    total_records = 0
    
    while True:
        try:
            # Sprawdź które prognozy jeszcze brakują
            existing_hours = gfs_professional.get_existing_forecast_hours(run_time, engine)
            missing_hours = sorted(list(required_hours - existing_hours))
            
            if len(missing_hours) == 0:
                logger.info("✓✓✓ Wszystkie 209 prognoz są już pobrane!")
                detailed_logger.info("Sprawdzam kompletnosc prognozy...")
                detailed_logger.info("Wszystkie 209 prognoz są już pobrane!")
                break
            
            if attempt > 1:
                logger.info(f"Próba #{attempt} - brakuje jeszcze {len(missing_hours)} prognoz")
                detailed_logger.info(f"Sprawdzam kompletnosc prognozy...")
                detailed_logger.info(f"Nastepny plik: {min(missing_hours) if missing_hours else 'brak'}")
            
            # Sprawdź kompletność przed rozpoczęciem
            if attempt == 1:
                logger.info("Sprawdzam kompletnosc prognozy...")
                detailed_logger.info("Sprawdzam kompletnosc prognozy...")
                if missing_hours:
                    detailed_logger.info(f"Nastepny plik: {min(missing_hours)}")
            
            # Filtruj prognozy do pobrania
            forecasts_to_download = [
                f for f in all_forecasts 
                if f['forecast_hour'] in missing_hours
            ]
            
            if len(forecasts_to_download) == 0:
                break
            
            logger.info(f"Próba #{attempt}: Pobieranie {len(forecasts_to_download)} brakujących prognoz...")
            
            # Przygotuj kolejki i statystyki
            download_queue = queue.Queue()
            progress_queue = queue.Queue()
            stats = {'success': 0, 'failed': 0, 'total_records': 0}
            currently_processing = set()
            
            # Dodaj prognozy do kolejki
            logger.debug(f"Dodawanie {len(forecasts_to_download)} prognoz do kolejki...")
            for forecast in forecasts_to_download:
                download_queue.put(forecast)
            logger.debug(f"Dodano {len(forecasts_to_download)} prognoz do kolejki")
            
            # Uruchom wątki
            logger.info(f"Uruchamianie {config['num_threads']} wątków...")
            detailed_logger.info(f"Uruchamianie {config['num_threads']} wątków do pobierania prognoz")
            threads = []
            try:
                for i in range(config['num_threads']):
                    t = threading.Thread(target=gfs_professional.worker_thread, args=(download_queue, downloader, progress_queue, stats, i+1))
                    t.daemon = True
                    t.start()
                    threads.append(t)
                    logger.info(f"Wątek #{i+1} uruchomiony (ID: {t.ident})")
                    detailed_logger.info(f"Wątek #{i+1} uruchomiony (ID: {t.ident})")
                logger.info(f"Wszystkie {len(threads)} wątki uruchomione")
                detailed_logger.info(f"Wszystkie {len(threads)} wątki uruchomione")
            except Exception as e:
                logger.error(f"Błąd uruchamiania wątków: {e}", exc_info=True)
                error_logger.error(f"Błąd uruchamiania wątków: {e}", exc_info=True)
                raise
            
            # Progress bar (bez wyświetlania w daemon mode, tylko logowanie)
            processed = 0
            successful_forecasts = []
            failed_forecasts = []
            
            # Logger dla modułu professional powinien być już skonfigurowany wcześniej
            # Ale upewnijmy się, że jest skonfigurowany
            if not gfs_professional.module_logger.handlers:
                logger.warning("Logger dla modułu professional nie jest skonfigurowany - konfiguruję teraz")
                gfs_professional.module_logger.handlers = []
                gfs_professional.module_logger.addHandler(logging.FileHandler(LOG_FILE, encoding='utf-8'))
                gfs_professional.module_logger.addHandler(detailed_handler)
                gfs_professional.module_logger.addHandler(logging.StreamHandler(sys.stdout))
                gfs_professional.module_logger.addHandler(error_handler)
                gfs_professional.module_logger.setLevel(logging.INFO)  # Zmieniono na INFO
                gfs_professional.module_logger.propagate = False
            
            logger.debug(f"Rozpoczynam przetwarzanie {len(forecasts_to_download)} prognoz w {config['num_threads']} wątkach")
            
            while processed < len(forecasts_to_download):
                try:
                    progress = progress_queue.get(timeout=30)
                    
                    if progress.get('type') == 'start':
                        forecast_hour = progress['forecast_hour']
                        thread_id = progress.get('thread_id', '?')
                        currently_processing.add(forecast_hour)
                        detailed_logger.info(f"thr: {thread_id} - Rozpoczęto pobieranie f{forecast_hour:03d}")
                    
                    elif progress.get('type') == 'done':
                        forecast_hour = progress['forecast_hour']
                        thread_id = progress.get('thread_id', '?')
                        currently_processing.discard(forecast_hour)
                        processed += 1
                        
                        if progress['success']:
                            successful_forecasts.append(forecast_hour)
                            records = progress.get('total_records', 0)
                            logger.info(f"✓ Pobrano f{forecast_hour:03d} - {records} rekordów")
                            detailed_logger.info(f"thr: {thread_id} - ✓ Pobrano f{forecast_hour:03d} - {records} rekordów")
                        else:
                            failed_forecasts.append(forecast_hour)
                            logger.warning(f"✗ Błąd pobierania f{forecast_hour:03d}")
                            detailed_logger.warning(f"thr: {thread_id} - ✗ BŁĄD pobierania f{forecast_hour:03d}")
                            error_logger.error(f"Błąd pobierania f{forecast_hour:03d} dla run {run_time.strftime('%Y-%m-%d %H:00')} UTC (wątek: {thread_id})")
                    
                except Empty:
                    alive = sum(1 for t in threads if t.is_alive())
                    if alive == 0:
                        logger.warning(f"Wszystkie wątki zakończone, ale przetworzono tylko {processed}/{len(forecasts_to_download)} prognoz")
                        break
                except Exception as e:
                    logger.error(f"Błąd w pętli przetwarzania progress_queue: {e}", exc_info=True)
                    error_logger.error(f"Błąd w pętli przetwarzania progress_queue: {e}", exc_info=True)
                    # Kontynuuj, żeby nie przerwać całego procesu
                    continue
            
            # Poczekaj na zakończenie wątków
            for t in threads:
                t.join(timeout=10)
            
            # Sprawdź czy wszystkie wątki zakończyły się prawidłowo
            alive_threads = [t for t in threads if t.is_alive()]
            if alive_threads:
                logger.warning(f"Niektóre wątki nadal działają: {len(alive_threads)}/{len(threads)}")
            
            # Zakończ wątki (wyślij sygnał None)
            for _ in range(config['num_threads']):
                try:
                    download_queue.put(None, timeout=1)
                except:
                    pass
            
            # Zaktualizuj statystyki
            total_success += stats['success']
            total_failed += stats['failed']
            total_records += stats['total_records']
            
            logger.info(f"Próba #{attempt}: Pobrano {stats['success']}, błędów: {stats['failed']}")
            
            # Szczegółowe logowanie wyników próby
            detailed_logger.info(f"=== PRÓBA #{attempt} ZAKOŃCZONA ===")
            detailed_logger.info(f"Pobrano: {stats['success']} prognoz")
            detailed_logger.info(f"Błędów: {stats['failed']} prognoz")
            detailed_logger.info(f"Rekordów w bazie: {stats['total_records']}")
            
            if successful_forecasts:
                success_list = sorted(successful_forecasts)
                success_str = ', '.join([f"f{h:03d}" for h in success_list[:20]])
                if len(success_list) > 20:
                    success_str += f" ... i {len(success_list) - 20} więcej"
                detailed_logger.info(f"Pomyślnie pobrane: {success_str}")
            
            if failed_forecasts:
                failed_list = sorted(failed_forecasts)
                failed_str = ', '.join([f"f{h:03d}" for h in failed_list[:20]])
                if len(failed_list) > 20:
                    failed_str += f" ... i {len(failed_list) - 20} więcej"
                detailed_logger.warning(f"Błędy pobierania: {failed_str}")
                error_logger.error(f"Próba #{attempt}: Nie udało się pobrać {len(failed_forecasts)} prognoz: {failed_str}")
            
            # Sprawdź czy wszystkie są już pobrane
            existing_hours_after = gfs_professional.get_existing_forecast_hours(run_time, engine)
            missing_hours_after = sorted(list(required_hours - existing_hours_after))
            
            if len(missing_hours_after) == 0:
                logger.info("✓✓✓ Wszystkie 209 prognoz są już pobrane!")
                break
            
            # Jeśli nie ma nowych sukcesów, poczekaj
            if stats['success'] == 0:
                min_missing = min(missing_hours_after) if missing_hours_after else None
                is_available = False
                
                if min_missing is not None:
                    check_hours = sorted(missing_hours_after)[:5]
                    for hour in check_hours:
                        if gfs_professional.check_gfs_availability(RUN_DATE, RUN_HOUR, hour):
                            is_available = True
                            logger.info(f"✓ Prognoza f{hour:03d} jest dostępna online")
                            break
                
                if not is_available:
                    if min_missing is not None:
                        logger.info(f"⏳ Najniższa brakująca prognoza: f{min_missing:03d} - jeszcze niedostępna")
                    logger.info(f"⏳ Czekam {WAIT_BETWEEN_ATTEMPTS}s przed następną próbą...")
                    time.sleep(WAIT_BETWEEN_ATTEMPTS)
                else:
                    logger.info(f"⏳ Czekam {WAIT_BETWEEN_ATTEMPTS}s przed następną próbą...")
                    time.sleep(WAIT_BETWEEN_ATTEMPTS)
            else:
                # Były sukcesy - kontynuuj szybciej
                logger.info(f"✓ Pobrano {stats['success']} prognoz. Kontynuuję...")
                time.sleep(2)
            
            attempt += 1
            
        except KeyboardInterrupt:
            logger.warning("Przerwano przez użytkownika (Ctrl+C)")
            logger.info(f"Pobrano łącznie: {total_success} prognoz w {attempt-1} próbach")
            break
        except Exception as e:
            logger.error(f"Błąd podczas pobierania: {e}", exc_info=True)
            logger.info(f"Czekam {WAIT_BETWEEN_ATTEMPTS}s przed następną próbą...")
            time.sleep(WAIT_BETWEEN_ATTEMPTS)
            attempt += 1
    
    logger.info(f"Pobieranie zakończone: {total_success} sukcesów, {total_failed} błędów, {total_records} rekordów")
    
    # Podsumowanie całego pobierania
    detailed_logger.info("=" * 70)
    detailed_logger.info(f"=== POBRANIE ZAKOŃCZONE DLA RUN {run_time.strftime('%Y-%m-%d %H:00')} UTC ===")
    detailed_logger.info(f"Łącznie prób: {attempt-1}")
    detailed_logger.info(f"Pobrano: {total_success} prognoz")
    detailed_logger.info(f"Błędów: {total_failed} prognoz")
    detailed_logger.info(f"Rekordów w bazie: {total_records}")
    
    # Sprawdź końcowy stan
    try:
        existing_hours_final = gfs_professional.get_existing_forecast_hours(run_time, engine)
        required_hours = gfs_professional.get_required_forecast_hours()
        missing_hours_final = sorted(list(required_hours - existing_hours_final))
        
        if len(missing_hours_final) == 0:
            detailed_logger.info("✓ Wszystkie 209 prognoz są w bazie!")
        else:
            missing_str = ', '.join([f"f{h:03d}" for h in missing_hours_final[:20]])
            if len(missing_hours_final) > 20:
                missing_str += f" ... i {len(missing_hours_final) - 20} więcej"
            detailed_logger.warning(f"⚠ Brakuje jeszcze {len(missing_hours_final)} prognoz: {missing_str}")
    except Exception as e:
        detailed_logger.error(f"Błąd sprawdzania końcowego stanu: {e}")
        error_logger.error(f"Błąd sprawdzania końcowego stanu dla run {run_time}: {e}", exc_info=True)
    
    detailed_logger.info("=" * 70)
    
    # === CZYSZCZENIE STARYCH RUNÓW (zostaw tylko 2 najnowsze kompletne) ===
    if total_success > 0:  # Tylko jeśli udało się pobrać coś
        logger.info("Czyszczenie starych runów (zostaw tylko 2 najnowsze kompletne)...")
        detailed_logger.info("Czyszczenie starych runów (zostaw tylko 2 najnowsze kompletne)...")
        
        try:
            with engine.connect() as conn:
                # Znajdź wszystkie kompletne runy w bazie (mające wszystkie 209 prognoz)
                required_hours = gfs_professional.get_required_forecast_hours()
                
                # Pobierz wszystkie runy z bazy
                result = conn.execute(text("""
                    SELECT DISTINCT run_time
                    FROM gfs_forecast
                    ORDER BY run_time DESC
                """))
                
                all_runs = []
                complete_runs = []
                
                for row in result:
                    run_time_db = row[0]
                    if isinstance(run_time_db, str):
                        try:
                            run_time_db = datetime.strptime(run_time_db, '%Y-%m-%d %H:%M:%S')
                        except:
                            try:
                                run_time_db = datetime.strptime(run_time_db, '%Y-%m-%d %H:%M')
                            except:
                                continue
                    all_runs.append(run_time_db)
                    
                    # Sprawdź czy run jest kompletny
                    try:
                        existing_hours = gfs_professional.get_existing_forecast_hours(run_time_db, engine)
                        missing_hours = required_hours - existing_hours
                        if len(missing_hours) == 0:
                            complete_runs.append(run_time_db)
                    except:
                        pass
                
                # Sortuj kompletne runy od najnowszego
                complete_runs.sort(reverse=True)
                
                if len(complete_runs) > 2:
                    # Zachowaj tylko 2 najnowsze kompletne runy
                    runs_to_keep = complete_runs[:2]
                    oldest_kept = min(runs_to_keep)  # Najstarszy z 2 najnowszych kompletnych
                    
                    # Usuń tylko runy starsze niż najstarszy z 2 najnowszych kompletnych
                    # (nie usuwamy niekompletnych runów które są nowsze)
                    runs_to_delete = [rt for rt in all_runs if rt < oldest_kept]
                    
                    if runs_to_delete:
                        deleted_total = 0
                        for old_run in runs_to_delete:
                            try:
                                delete_result = conn.execute(text("""
                                    DELETE FROM gfs_forecast
                                    WHERE run_time = :old_run
                                """), {"old_run": old_run})
                                deleted_count = delete_result.rowcount
                                deleted_total += deleted_count
                                
                                logger.info(f"  ✓ Usunięto run {old_run.strftime('%Y-%m-%d %H:00')} UTC: {deleted_count} rekordów")
                                detailed_logger.info(f"  ✓ Usunięto run {old_run.strftime('%Y-%m-%d %H:00')} UTC: {deleted_count} rekordów")
                            except Exception as e:
                                logger.warning(f"  ✗ Błąd usuwania run {old_run.strftime('%Y-%m-%d %H:00')} UTC: {e}")
                                detailed_logger.warning(f"  ✗ Błąd usuwania run {old_run.strftime('%Y-%m-%d %H:00')} UTC: {e}")
                        
                        conn.commit()
                        
                        logger.info(f"✓ Usunięto {len(runs_to_delete)} starych run(ów) - {deleted_total} rekordów")
                        logger.info(f"  Zostały tylko 2 najnowsze kompletne runy:")
                        for rt in runs_to_keep:
                            logger.info(f"    - {rt.strftime('%Y-%m-%d %H:00')} UTC")
                        detailed_logger.info(f"✓ Usunięto {len(runs_to_delete)} starych run(ów) - {deleted_total} rekordów")
                        detailed_logger.info(f"  Zostały tylko 2 najnowsze kompletne runy: {[rt.strftime('%Y-%m-%d %H:00') for rt in runs_to_keep]}")
                else:
                    if len(complete_runs) > 0:
                        logger.info(f"✓ W bazie jest {len(complete_runs)} kompletny(ych) run(ów) - wszystko OK")
                        detailed_logger.info(f"✓ W bazie jest {len(complete_runs)} kompletny(ych) run(ów) - wszystko OK")
                    else:
                        logger.info("✓ Brak kompletnych runów do czyszczenia")
                        detailed_logger.info("✓ Brak kompletnych runów do czyszczenia")
                        
        except Exception as e:
            logger.error(f"Błąd podczas czyszczenia starych runów: {e}", exc_info=True)
            detailed_logger.error(f"Błąd podczas czyszczenia starych runów: {e}", exc_info=True)
            error_logger.error(f"Błąd podczas czyszczenia starych runów: {e}", exc_info=True)
    
    return total_success, total_failed, total_records

def main_daemon_loop():
    """Główna pętla daemona"""
    logger.info("=" * 70)
    logger.info("GFS Weather Data Downloader - DAEMON VERSION")
    logger.info("=" * 70)
    logger.info(f"Interwał sprawdzania: {CHECK_INTERVAL/60:.0f} minut")
    logger.info(f"Logi zapisywane do:")
    logger.info(f"  - Główny log: {LOG_FILE}")
    logger.info(f"  - Szczegółowy log: {DETAILED_LOG_FILE}")
    logger.info(f"  - Log błędów: {ERROR_LOG_FILE}")
    logger.info("=" * 70)
    
    detailed_logger.info("=" * 70)
    detailed_logger.info("GFS Weather Data Downloader - DAEMON VERSION - SZCZEGÓŁOWY LOG")
    detailed_logger.info("=" * 70)
    detailed_logger.info(f"Uruchomiono: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    detailed_logger.info(f"Interwał sprawdzania: {CHECK_INTERVAL/60:.0f} minut")
    detailed_logger.info("=" * 70)
    
    # Wczytaj konfigurację
    config = load_config()
    logger.info(f"Konfiguracja OK - Region: {config['lat_min']}°-{config['lat_max']}°N, {config['lon_min']}°-{config['lon_max']}°E")
    
    # Połącz z bazą
    try:
        mysql_url = f"mysql+pymysql://{config['mysql_user']}:{config['mysql_password']}@{config['mysql_host']}/{config['mysql_database']}?charset=utf8mb4"
        engine = create_engine(mysql_url, echo=False, pool_pre_ping=True)
        
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        logger.info(f"MySQL OK: {config['mysql_database']}")
    except Exception as e:
        logger.error(f"Błąd połączenia z MySQL: {e}")
        sys.exit(1)
    
    last_run_in_db = None
    last_check_time = None
    
    logger.info("\n🚀 Daemon uruchomiony. Działa w tle...")
    logger.info("   (Naciśnij Ctrl+C aby zatrzymać)\n")
    
    try:
        while True:
            try:
                current_time = datetime.utcnow()
                
                # Sprawdź czy minął interwał
                if last_check_time is None or (current_time - last_check_time).total_seconds() >= CHECK_INTERVAL:
                    logger.info(f"Sprawdzam dostępność nowych danych GFS... ({current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
                    detailed_logger.info(f"\n{'='*70}")
                    detailed_logger.info(f"SPRAWDZANIE NOWYCH DANYCH - {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                    detailed_logger.info(f"{'='*70}")
                    
                    run_time, RUN_DATE, RUN_HOUR, last_run_in_db = check_for_new_run(engine, last_run_in_db)
                    
                    if run_time is not None:
                        logger.info(f"✓ Znaleziono run do pobrania: {run_time.strftime('%Y-%m-%d %H:00')} UTC")
                        detailed_logger.info(f"\n{'='*70}")
                        detailed_logger.info(f"ROZPOCZYNAM POBRANIE RUN {run_time.strftime('%Y-%m-%d %H:00')} UTC")
                        detailed_logger.info(f"{'='*70}")
                        
                        # Skonfiguruj logger dla modułu professional PRZED użyciem
                        try:
                            gfs_professional.module_logger.handlers = []
                            # Dodaj handler do głównego pliku logów
                            gfs_professional.module_logger.addHandler(logging.FileHandler(LOG_FILE, encoding='utf-8'))
                            # Dodaj handler do szczegółowego pliku logów
                            gfs_professional.module_logger.addHandler(detailed_handler)
                            # Dodaj handler do konsoli (stdout)
                            gfs_professional.module_logger.addHandler(logging.StreamHandler(sys.stdout))
                            # Dodaj handler do błędów
                            gfs_professional.module_logger.addHandler(error_handler)
                            gfs_professional.module_logger.setLevel(logging.INFO)  # Zmieniono na INFO żeby widzieć logi
                            gfs_professional.module_logger.propagate = False
                            logger.debug("Logger dla modułu professional skonfigurowany")
                        except Exception as e:
                            logger.warning(f"Błąd konfiguracji loggera dla modułu professional: {e}")
                        
                        # Pobierz wszystkie prognozy
                        try:
                            success, failed, records = download_forecasts(run_time, RUN_DATE, RUN_HOUR, config, engine)
                            
                            # Zaktualizuj last_run_in_db
                            last_run_in_db = run_time
                            
                            logger.info(f"✓✓✓ Pobieranie zakończone: {success} sukcesów, {failed} błędów")
                        except Exception as e:
                            logger.error(f"KRYTYCZNY BŁĄD podczas pobierania prognoz: {e}", exc_info=True)
                            error_logger.error(f"KRYTYCZNY BŁĄD podczas pobierania prognoz dla run {run_time}: {e}", exc_info=True)
                            detailed_logger.error(f"KRYTYCZNY BŁĄD podczas pobierania prognoz: {e}", exc_info=True)
                            # Kontynuuj działanie daemona zamiast się wyłączać
                            logger.info("Kontynuuję działanie daemona...")
                    else:
                        logger.info("Brak nowych danych do pobrania")
                        detailed_logger.info("Brak nowych danych do pobrania")
                    
                    last_check_time = current_time
                    next_check = current_time + timedelta(seconds=CHECK_INTERVAL)
                    logger.info(f"Następne sprawdzenie za {CHECK_INTERVAL/60:.0f} minut ({next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC)...\n")
                    detailed_logger.info(f"Następne sprawdzenie: {next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                
                # Czekaj 1 minutę przed następnym sprawdzeniem
                time.sleep(60)
                
            except KeyboardInterrupt:
                logger.info("\n⚠️  Zatrzymywanie daemona...")
                break
            except Exception as e:
                logger.error(f"Błąd w głównej pętli: {e}", exc_info=True)
                time.sleep(60)  # Czekaj przed ponowną próbą
                
    except KeyboardInterrupt:
        logger.info("\n⚠️  Daemon zatrzymany przez użytkownika")
    except SystemExit as e:
        logger.error(f"SystemExit wywołany: {e}", exc_info=True)
        error_logger.error(f"SystemExit wywołany: {e}", exc_info=True)
        raise  # Pozwól na normalne wyjście
    except Exception as e:
        logger.error(f"Krytyczny błąd w głównej pętli daemona: {e}", exc_info=True)
        error_logger.error(f"Krytyczny błąd w głównej pętli daemona: {e}", exc_info=True)
        detailed_logger.error(f"Krytyczny błąd w głównej pętli daemona: {e}", exc_info=True)
        # Nie kończ programu - spróbuj kontynuować
        logger.info("Próbuję kontynuować działanie daemona...")
        time.sleep(60)  # Poczekaj przed ponowną próbą
    finally:
        logger.info("Daemon zakończony")
        detailed_logger.info("Daemon zakończony")

if __name__ == "__main__":
    main_daemon_loop()

