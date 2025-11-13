# 🚀 Szybki start - Linux (kylos.pl)

## Krok 1: Przenieś pliki na serwer

### Opcja A: Przez Git (ZALECANE)

```bash
# Na Windows - w PowerShell
cd C:\xampp\htdocs\meteomax_new

# Inicjalizuj Git (jeśli jeszcze nie)
git init
git add .
git commit -m "Initial commit"

# Dodaj remote (zamień na swoje)
git remote add origin https://github.com/twoj-username/gfs-downloader.git
git push -u origin main

# Na serwerze Linux
ssh uzytkownik@kylos.pl
cd ~
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader
```

### Opcja B: Przez SCP

```powershell
# W PowerShell na Windows
scp -r C:\xampp\htdocs\meteomax_new\ uzytkownik@kylos.pl:~/gfs_downloader/
```

## Krok 2: Zainstaluj

```bash
# Na serwerze
cd ~/gfs_downloader  # LUB ~/gfs-downloader (jeśli przez Git)

# Uruchom skrypt instalacji
bash INSTALACJA_LINUX.sh

# LUB ręcznie:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Krok 3: Skonfiguruj bazę danych

```bash
# Połącz się z MySQL
mysql -u root -p
# LUB
mysql -u twoj_uzytkownik -p

# W MySQL:
CREATE DATABASE dane_gfs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE dane_gfs;
SOURCE ~/gfs_downloader/create_database_complete.sql;
# LUB skopiuj zawartość pliku i wklej
```

## Krok 4: Skonfiguruj config.ini

```bash
nano config.ini
```

Ustaw:
```ini
[database]
user = twoj_uzytkownik_mysql
password = twoje_haslo
host = localhost
database = dane_gfs
```

## Krok 5: Uruchom jako service

```bash
# Skopiuj plik service
sudo cp gfs-downloader.service /etc/systemd/system/

# Edytuj ścieżki w pliku
sudo nano /etc/systemd/system/gfs-downloader.service

# Zamień:
# - twoj_uzytkownik → Twój użytkownik na serwerze
# - Sprawdź ścieżkę: which python3 (w venv: ~/gfs_downloader/venv/bin/python3)

# Włącz i uruchom
sudo systemctl daemon-reload
sudo systemctl enable gfs-downloader.service
sudo systemctl start gfs-downloader.service

# Sprawdź status
sudo systemctl status gfs-downloader.service
```

## Krok 6: Sprawdź logi

```bash
# Główny log
tail -f ~/gfs_downloader/logs/gfs_daemon_$(date +%Y%m%d).log

# Status service
sudo systemctl status gfs-downloader.service
```

## ✅ Gotowe!

Daemon działa w tle i automatycznie:
- Sprawdza nowe dane co 10 minut
- Pobiera gdy są dostępne
- Zapisuje do bazy danych
- Czyści stare runy (zostaje tylko 2 najnowsze)

---

**Więcej szczegółów:** Zobacz [MIGRACJA_LINUX.md](MIGRACJA_LINUX.md)

