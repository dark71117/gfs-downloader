# 🌦️ GFS Weather Data Downloader - Daemon Version

Automatyczny system pobierania danych pogodowych GFS (Global Forecast System) z NOAA.

## ✨ Funkcje

- ✅ Automatyczne pobieranie danych GFS co 6 godzin
- ✅ Pełny zakres prognoz: 209 prognoz (f000-f120 co 1h + f123-f384 co 3h)
- ✅ Multi-threading - równoległe pobieranie
- ✅ Automatyczne sprawdzanie dostępności danych
- ✅ Sprawdzanie obu serwerów NOAA (nomads i ftp)
- ✅ Weryfikacja plików .idx przed pobieraniem
- ✅ Backup do CSV przed zapisem do MySQL
- ✅ Automatyczne czyszczenie starych runów (zostaje tylko 2 najnowsze)
- ✅ Szczegółowe logowanie
- ✅ Działa jako daemon w tle

## 📋 Wymagania

- Python 3.9+
- MySQL/MariaDB
- eccodes (dla obsługi GRIB2)
- ~2 GB wolnego miejsca na dysku

## 🚀 Szybki start

### 1. Instalacja

```bash
# Sklonuj repozytorium
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader

# Uruchom skrypt instalacji
bash INSTALACJA_LINUX.sh

# LUB ręcznie:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Konfiguracja

```bash
# Skonfiguruj bazę danych
nano config.ini
```

```ini
[database]
user = twoj_uzytkownik
password = twoje_haslo
host = localhost
database = dane_gfs

[region]
lat_min = 49.0
lat_max = 55.0
lon_min = 14.0
lon_max = 24.0
```

### 3. Utwórz bazę danych

```sql
CREATE DATABASE dane_gfs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE dane_gfs;
-- Wykonaj create_database_complete.sql
```

### 4. Uruchom jako daemon

```bash
# Jako systemd service (ZALECANE)
sudo cp gfs-downloader.service /etc/systemd/system/
sudo nano /etc/systemd/system/gfs-downloader.service  # Edytuj ścieżki
sudo systemctl daemon-reload
sudo systemctl enable gfs-downloader.service
sudo systemctl start gfs-downloader.service

# LUB przez screen
screen -S gfs_daemon
source venv/bin/activate
python gfs_downloader_daemon.py
```

## 📖 Dokumentacja

- [Instrukcja instalacji (Windows)](INSTRUKCJA.md)
- [Migracja na Linux](MIGRACJA_LINUX.md)
- [Professional Version](PROFESSIONAL_VERSION.md)

## 📊 Struktura bazy danych

Tabela `gfs_forecast` zawiera:
- `run_time` - czas uruchomienia modelu GFS (00, 06, 12, 18 UTC)
- `forecast_time` - czas prognozy
- `lat`, `lon` - współrzędne geograficzne
- Parametry pogodowe: `t2m`, `d2m`, `rh`, `wind_speed`, `wind_dir`, `mslp`, `tp`, itd.

## 🔧 Konfiguracja

### Interwał sprawdzania

W `gfs_downloader_daemon.py`:
```python
CHECK_INTERVAL = 600  # 10 minut (domyślnie)
```

### Region

W `config.ini`:
```ini
[region]
lat_min = 49.0  # Szerokość geograficzna (min)
lat_max = 55.0  # Szerokość geograficzna (max)
lon_min = 14.0  # Długość geograficzna (min)
lon_max = 24.0  # Długość geograficzna (max)
```

## 📝 Logi

Logi są zapisywane w katalogu `logs/`:
- `gfs_daemon_YYYYMMDD.log` - główny log
- `gfs_daemon_detailed_YYYYMMDD.log` - szczegółowy log
- `gfs_daemon_errors_YYYYMMDD.log` - błędy

## 🆘 Rozwiązywanie problemów

Zobacz [MIGRACJA_LINUX.md](MIGRACJA_LINUX.md) - sekcja "Rozwiązywanie problemów"

## 📄 Licencja

MIT License

## 🙏 Podziękowania

- NOAA za dane GFS
- ECMWF za bibliotekę eccodes
- Wszystkim twórcom bibliotek Python

