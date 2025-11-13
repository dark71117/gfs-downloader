# 🐧 Migracja GFS Downloader na serwer Linux (kylos.pl)

## 📋 Spis treści
1. [Przygotowanie](#przygotowanie)
2. [Instalacja na serwerze](#instalacja-na-serwerze)
3. [Konfiguracja bazy danych](#konfiguracja-bazy-danych)
4. [Uruchomienie jako daemon](#uruchomienie-jako-daemon)
5. [GitHub (opcjonalnie)](#github-opcjonalnie)

---

## 🔧 PRZYGOTOWANIE

### Krok 1: Sprawdź dostęp do serwera

Upewnij się, że masz:
- ✅ Dostęp SSH do serwera
- ✅ Uprawnienia do instalacji pakietów (sudo lub root)
- ✅ Dostęp do MySQL/MariaDB
- ✅ Python 3.9+ na serwerze

### Krok 2: Sprawdź Python na serwerze

```bash
ssh uzytkownik@kylos.pl
python3 --version
# Powinno pokazać: Python 3.9.x lub nowszy
```

Jeśli nie ma Pythona 3.9+, skontaktuj się z supportem kylos.pl.

---

## 📦 INSTALACJA NA SERWERZE

### Krok 1: Przenieś pliki na serwer

#### Opcja A: Przez SCP (z Windows)

```powershell
# W PowerShell na Windows
scp -r C:\xampp\htdocs\meteomax_new\ uzytkownik@kylos.pl:~/gfs_downloader/
```

#### Opcja B: Przez SFTP (FileZilla, WinSCP)

1. Połącz się z serwerem przez SFTP
2. Przenieś cały folder `meteomax_new` do `~/gfs_downloader/`

#### Opcja C: Przez Git (jeśli masz repozytorium)

```bash
# Na serwerze
cd ~
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader
```

### Krok 2: Zainstaluj zależności systemowe

```bash
# Połącz się z serwerem
ssh uzytkownik@kylos.pl

# Przejdź do katalogu projektu
cd ~/gfs_downloader

# Zainstaluj systemowe zależności (eccodes)
# Dla Ubuntu/Debian:
sudo apt-get update
sudo apt-get install -y libeccodes-dev libeccodes-tools

# Dla CentOS/RHEL:
# sudo yum install -y eccodes-devel
```

### Krok 3: Utwórz środowisko wirtualne Python

```bash
# Utwórz środowisko wirtualne
python3 -m venv venv

# Aktywuj środowisko
source venv/bin/activate

# Zaktualizuj pip
pip install --upgrade pip
```

### Krok 4: Zainstaluj biblioteki Python

```bash
# Zainstaluj podstawowe biblioteki
pip install -r requirements.txt

# Jeśli cfgrib/eccodes nie działa, spróbuj przez conda:
# (jeśli masz conda na serwerze)
conda install -c conda-forge eccodes cfgrib
pip install -r requirements.txt
```

---

## 🗄️ KONFIGURACJA BAZY DANYCH

### Krok 1: Utwórz bazę danych

```bash
# Połącz się z MySQL
mysql -u root -p
# LUB jeśli masz użytkownika:
mysql -u twoj_uzytkownik -p
```

W MySQL wykonaj:

```sql
CREATE DATABASE IF NOT EXISTS dane_gfs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Utwórz użytkownika (jeśli potrzebny)
CREATE USER IF NOT EXISTS 'gfs_user'@'localhost' IDENTIFIED BY 'twoje_haslo';
GRANT ALL PRIVILEGES ON dane_gfs.* TO 'gfs_user'@'localhost';
FLUSH PRIVILEGES;

-- Użyj bazy
USE dane_gfs;

-- Wykonaj skrypt SQL
SOURCE ~/gfs_downloader/create_database_complete.sql;
-- LUB skopiuj zawartość i wklej do MySQL
```

### Krok 2: Skonfiguruj config.ini

```bash
cd ~/gfs_downloader
nano config.ini
```

Zmień ustawienia:

```ini
[database]
user = gfs_user          # LUB twoj_uzytkownik_mysql
password = twoje_haslo   # Hasło do MySQL
host = localhost         # LUB adres IP bazy (jeśli zdalna)
database = dane_gfs

[region]
lat_min = 49.0
lat_max = 55.0
lon_min = 14.0
lon_max = 24.0
```

Zapisz: `Ctrl+O`, `Enter`, `Ctrl+X`

### Krok 3: Utwórz katalogi

```bash
cd ~/gfs_downloader
mkdir -p logs temp/csv_backup
chmod 755 logs temp temp/csv_backup
```

---

## 🚀 URUCHOMIENIE JAKO DAEMON

### Opcja 1: Systemd Service (ZALECANE)

#### Krok 1: Utwórz plik service

```bash
sudo nano /etc/systemd/system/gfs-downloader.service
```

Wklej następującą zawartość (dostosuj ścieżki):

```ini
[Unit]
Description=GFS Weather Data Downloader Daemon
After=network.target mysql.service

[Service]
Type=simple
User=twoj_uzytkownik
WorkingDirectory=/home/twoj_uzytkownik/gfs_downloader
Environment="PATH=/home/twoj_uzytkownik/gfs_downloader/venv/bin"
ExecStart=/home/twoj_uzytkownik/gfs_downloader/venv/bin/python /home/twoj_uzytkownik/gfs_downloader/gfs_downloader_daemon.py
Restart=always
RestartSec=10
StandardOutput=append:/home/twoj_uzytkownik/gfs_downloader/logs/daemon_service.log
StandardError=append:/home/twoj_uzytkownik/gfs_downloader/logs/daemon_service_errors.log

[Install]
WantedBy=multi-user.target
```

**WAŻNE:** Zamień:
- `twoj_uzytkownik` → Twój użytkownik na serwerze
- Sprawdź ścieżkę do Pythona: `which python3` (w venv)

#### Krok 2: Włącz i uruchom service

```bash
# Przeładuj systemd
sudo systemctl daemon-reload

# Włącz automatyczne uruchamianie przy starcie systemu
sudo systemctl enable gfs-downloader.service

# Uruchom service
sudo systemctl start gfs-downloader.service

# Sprawdź status
sudo systemctl status gfs-downloader.service

# Zobacz logi
sudo journalctl -u gfs-downloader.service -f
```

#### Krok 3: Zarządzanie service

```bash
# Zatrzymaj
sudo systemctl stop gfs-downloader.service

# Uruchom ponownie
sudo systemctl restart gfs-downloader.service

# Sprawdź status
sudo systemctl status gfs-downloader.service

# Wyłącz automatyczne uruchamianie
sudo systemctl disable gfs-downloader.service
```

### Opcja 2: Screen/Tmux (prostsze, ale mniej niezawodne)

```bash
# Zainstaluj screen (jeśli nie ma)
sudo apt-get install screen

# Uruchom w screen
screen -S gfs_daemon
cd ~/gfs_downloader
source venv/bin/activate
python gfs_downloader_daemon.py

# Odłącz: Ctrl+A, potem D
# Podłącz ponownie: screen -r gfs_daemon
```

### Opcja 3: nohup (najprostsze)

```bash
cd ~/gfs_downloader
source venv/bin/activate
nohup python gfs_downloader_daemon.py > logs/nohup.log 2>&1 &

# Sprawdź czy działa
ps aux | grep gfs_downloader_daemon
```

---

## 📊 MONITOROWANIE

### Sprawdzanie logów

```bash
# Główny log
tail -f ~/gfs_downloader/logs/gfs_daemon_$(date +%Y%m%d).log

# Szczegółowy log
tail -f ~/gfs_downloader/logs/gfs_daemon_detailed_$(date +%Y%m%d).log

# Log błędów
tail -f ~/gfs_downloader/logs/gfs_daemon_errors_$(date +%Y%m%d).log
```

### Sprawdzanie bazy danych

```bash
mysql -u gfs_user -p dane_gfs

# Sprawdź ostatnie runy
SELECT DISTINCT run_time, COUNT(*) as rekordow 
FROM gfs_forecast 
GROUP BY run_time 
ORDER BY run_time DESC 
LIMIT 5;

# Sprawdź ile prognoz dla ostatniego runu
SELECT run_time, COUNT(DISTINCT forecast_time) as prognoz
FROM gfs_forecast
WHERE run_time = (SELECT MAX(run_time) FROM gfs_forecast)
GROUP BY run_time;
```

---

## 🔄 GITHUB (OPCJONALNIE)

### Krok 1: Utwórz repozytorium na GitHub

1. Zaloguj się na GitHub
2. Kliknij "New repository"
3. Nazwa: `gfs-downloader` (lub inna)
4. Opis: "GFS Weather Data Downloader - Daemon"
5. **NIE zaznaczaj** "Initialize with README" (masz już pliki)
6. Kliknij "Create repository"

### Krok 2: Utwórz .gitignore

```bash
cd C:\xampp\htdocs\meteomax_new
```

Utwórz plik `.gitignore`:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# Logi
logs/*.log
logs/*.txt

# Pliki tymczasowe
temp/
*.grib2
*.csv

# Konfiguracja (z hasłami)
config.ini

# IDE
.vscode/
.idea/
*.swp
*.swo

# System
.DS_Store
Thumbs.db
```

### Krok 3: Inicjalizuj Git i wyślij

```bash
# W PowerShell na Windows
cd C:\xampp\htdocs\meteomax_new

# Inicjalizuj repozytorium
git init

# Dodaj pliki
git add .

# Commit
git commit -m "Initial commit - GFS Downloader Daemon"

# Dodaj remote (zamień na swoje URL)
git remote add origin https://github.com/twoj-username/gfs-downloader.git

# Wyślij
git branch -M main
git push -u origin main
```

### Krok 4: Pobierz na serwerze

```bash
# Na serwerze
cd ~
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader

# Skonfiguruj config.ini (patrz wyżej)
nano config.ini

# Zainstaluj zależności (patrz wyżej)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ⚠️ WAŻNE UWAGI

### 1. Bezpieczeństwo

- **NIE commituj** `config.ini` z hasłami do Git!
- Użyj `.gitignore` (patrz wyżej)
- Na serwerze utwórz `config.ini` ręcznie

### 2. Uprawnienia

```bash
# Upewnij się, że katalogi mają odpowiednie uprawnienia
chmod 755 ~/gfs_downloader
chmod 755 ~/gfs_downloader/logs
chmod 755 ~/gfs_downloader/temp
```

### 3. Firewall

Jeśli używasz zdalnej bazy danych, upewnij się że port MySQL (3306) jest otwarty.

### 4. Limity hostingu

Sprawdź limity hostingu kylos.pl:
- Limit pamięci RAM
- Limit CPU
- Limit przestrzeni dyskowej
- Limit transferu

GFS Downloader potrzebuje:
- ~500 MB RAM podczas pobierania
- ~1-2 GB miejsca na dane (2 runy × ~500 MB)
- Transfer: ~500 MB co 6 godzin

---

## 🆘 ROZWIĄZYWANIE PROBLEMÓW

### Problem: "Permission denied"

```bash
# Sprawdź uprawnienia
ls -la ~/gfs_downloader

# Napraw
chmod +x ~/gfs_downloader/gfs_downloader_daemon.py
```

### Problem: "Module not found"

```bash
# Upewnij się, że venv jest aktywne
source venv/bin/activate

# Zainstaluj ponownie
pip install -r requirements.txt
```

### Problem: "Cannot connect to MySQL"

```bash
# Sprawdź czy MySQL działa
sudo systemctl status mysql

# Sprawdź połączenie
mysql -u gfs_user -p dane_gfs
```

### Problem: Service nie startuje

```bash
# Sprawdź logi systemd
sudo journalctl -u gfs-downloader.service -n 50

# Sprawdź czy Python jest w PATH
which python3

# Sprawdź uprawnienia użytkownika
sudo -u twoj_uzytkownik /home/twoj_uzytkownik/gfs_downloader/venv/bin/python --version
```

---

## 📝 PRZYDATNE KOMENDY

```bash
# Sprawdź czy daemon działa
ps aux | grep gfs_downloader_daemon

# Zatrzymaj proces
pkill -f gfs_downloader_daemon

# Sprawdź użycie dysku
du -sh ~/gfs_downloader

# Sprawdź użycie pamięci
free -h

# Sprawdź ostatnie logi
tail -n 100 ~/gfs_downloader/logs/gfs_daemon_$(date +%Y%m%d).log
```

---

## ✅ CHECKLIST PRZED URUCHOMIENIEM

- [ ] Pliki przeniesione na serwer
- [ ] Python 3.9+ zainstalowany
- [ ] Środowisko wirtualne utworzone
- [ ] Biblioteki zainstalowane (`pip install -r requirements.txt`)
- [ ] eccodes zainstalowany systemowo
- [ ] Baza danych utworzona
- [ ] Tabela `gfs_forecast` utworzona
- [ ] `config.ini` skonfigurowany
- [ ] Katalogi `logs/` i `temp/` utworzone
- [ ] Service systemd utworzony (lub screen/nohup)
- [ ] Service uruchomiony i działa
- [ ] Logi są zapisywane

---

**Powodzenia! 🚀**

Jeśli masz problemy, sprawdź logi w `~/gfs_downloader/logs/`

