# 📦 Kompletna instrukcja instalacji GFS Downloader

## ⚠️ WAŻNE - Przeczytaj przed rozpoczęciem!

Ta instrukcja zawiera **wszystkie kroki** potrzebne do poprawnej instalacji programu na nowym komputerze. Postępuj krok po kroku.

---

## 📋 Wymagania

- Windows 10/11
- Miniconda lub Anaconda (conda)
- XAMPP z MySQL (lub osobny MySQL)
- Połączenie z internetem
- ~2 GB wolnego miejsca na dysku

---

## 🔧 KROK 1: Instalacja Miniconda (jeśli nie masz)

1. Pobierz Miniconda: https://docs.conda.io/en/latest/miniconda.html
2. Zainstaluj Miniconda (zaznacz "Add Miniconda3 to PATH")
3. Otwórz **Anaconda PowerShell Prompt** (lub zwykły PowerShell)

---

## 🐍 KROK 2: Sklonuj repozytorium

```powershell
# Przejdź do katalogu gdzie chcesz mieć projekt (np. C:\xampp\htdocs)
cd C:\xampp\htdocs

# Sklonuj repozytorium
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader
```

**LUB** jeśli masz już pliki:
```powershell
cd C:\xampp\htdocs\gfs-downloader
```

---

## 🎯 KROK 3: Utwórz środowisko conda z Python 3.14.0

```powershell
# Utwórz środowisko z Python 3.14.0
conda create -n gfs314 python=3.14.0 -y
```

**Czekaj na zakończenie** - to może zająć 1-2 minuty.

---

## 📦 KROK 4: Zainstaluj biblioteki systemowe (WAŻNE!)

**⚠️ TO JEST KLUCZOWE!** Bez tego parsowanie GRIB2 nie będzie działać.

```powershell
# Zainstaluj eccodes przez conda-forge (zawiera biblioteki systemowe)
conda install -n gfs314 -c conda-forge eccodes -y

# Zainstaluj cfgrib przez conda-forge (lepsza kompatybilność)
conda install -n gfs314 -c conda-forge cfgrib -y
```

**Czekaj na zakończenie** - to może zająć 2-3 minuty.

---

## 📚 KROK 5: Zainstaluj pozostałe biblioteki Python

```powershell
# Zainstaluj wszystkie biblioteki z requirements.txt
conda run -n gfs314 pip install -r requirements.txt
```

**Czekaj na zakończenie** - to może zająć 2-3 minuty.

---

## ✅ KROK 6: Sprawdź instalację

```powershell
# Sprawdź czy Python 3.14.0 jest zainstalowany
conda run -n gfs314 python --version
# Powinno pokazać: Python 3.14.0

# Sprawdź czy biblioteki działają
conda run -n gfs314 python -c "import eccodes; import cfgrib; import pandas; import xarray; print('OK - Wszystkie biblioteki działają!')"
# Powinno pokazać: OK - Wszystkie biblioteki działają!
```

Jeśli widzisz błąd, wróć do kroku 4 i 5.

---

## ⚙️ KROK 7: Skonfiguruj bazę danych MySQL

1. Uruchom XAMPP i włącz MySQL
2. Otwórz phpMyAdmin: http://localhost/phpmyadmin
3. Kliknij zakładkę **SQL**
4. Otwórz plik `create_database_complete.sql` (lub `setup_database.sql`)
5. Skopiuj całą zawartość i wklej do pola SQL
6. Kliknij **Wykonaj** (Execute)
7. Sprawdź czy baza `dane_gfs` została utworzona

---

## 📝 KROK 8: Skonfiguruj config.ini

```powershell
# Sprawdź czy config.ini istnieje
Test-Path config.ini

# Jeśli nie istnieje, skopiuj z przykładu
if (!(Test-Path "config.ini")) {
    Copy-Item "config.ini.example" "config.ini"
    Write-Host "Plik config.ini utworzony!"
}
```

**Edytuj `config.ini`** i ustaw:
```ini
[database]
user = root
password =          # Wpisz hasło MySQL jeśli masz
host = localhost
database = dane_gfs

[region]
lat_min = 49.0
lat_max = 55.0
lon_min = 14.0
lon_max = 24.0
```

---

## 🚀 KROK 9: Uruchom program

### Metoda 1: Przez skrypt PowerShell (ZALECANE)
```powershell
.\uruchom_daemon.ps1
```

### Metoda 2: Przez skrypt BAT
```powershell
.\uruchom.bat
```

### Metoda 3: Bezpośrednio (tak jak w pracy)
```powershell
# Aktywuj środowisko
conda activate gfs314

# Uruchom daemon
python gfs_downloader_daemon.py

# LUB zwykłą wersję
python gfs_downloader.py
```

---

## 🔄 Szybka instalacja (wszystko w jednym)

Jeśli chcesz zrobić wszystko szybko, możesz użyć tego skryptu:

```powershell
# 1. Utwórz środowisko
conda create -n gfs314 python=3.14.0 -y

# 2. Zainstaluj biblioteki systemowe (WAŻNE!)
conda install -n gfs314 -c conda-forge eccodes cfgrib -y

# 3. Zainstaluj pozostałe biblioteki
conda run -n gfs314 pip install -r requirements.txt

# 4. Sprawdź instalację
conda run -n gfs314 python -c "import eccodes, cfgrib, pandas, xarray; print('OK')"

# 5. Utwórz config.ini jeśli nie istnieje
if (!(Test-Path "config.ini")) { Copy-Item "config.ini.example" "config.ini" }

# 6. Gotowe! Uruchom:
conda activate gfs314
python gfs_downloader_daemon.py
```

---

## ❓ Rozwiązywanie problemów

### Problem: "Cannot find the ecCodes library"
**Rozwiązanie:**
```powershell
conda install -n gfs314 -c conda-forge eccodes -y
```

### Problem: "ModuleNotFoundError: No module named 'pandas'"
**Rozwiązanie:**
```powershell
conda run -n gfs314 pip install -r requirements.txt
```

### Problem: "znaleziono 0 datasetów" w logach
**Rozwiązanie:**
Upewnij się, że zainstalowałeś `eccodes` i `cfgrib` przez conda-forge:
```powershell
conda install -n gfs314 -c conda-forge eccodes cfgrib -y
```

### Problem: "Python 3.13" zamiast "Python 3.14.0"
**Rozwiązanie:**
Sprawdź czy środowisko jest aktywne:
```powershell
conda activate gfs314
python --version
```

### Problem: Skrypty PowerShell nie działają
**Rozwiązanie:**
Uruchom PowerShell jako administrator i wykonaj:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 📋 Checklist instalacji

Przed uruchomieniem sprawdź:

- [ ] Miniconda/Anaconda zainstalowana
- [ ] Środowisko `gfs314` utworzone
- [ ] Python 3.14.0 w środowisku (`conda run -n gfs314 python --version`)
- [ ] `eccodes` zainstalowane przez conda-forge
- [ ] `cfgrib` zainstalowane przez conda-forge
- [ ] Wszystkie biblioteki z `requirements.txt` zainstalowane
- [ ] Baza danych `dane_gfs` utworzona
- [ ] Plik `config.ini` skonfigurowany
- [ ] MySQL uruchomiony (XAMPP)

---

## 🎯 Podsumowanie - Najważniejsze kroki

1. **Utwórz środowisko:** `conda create -n gfs314 python=3.14.0 -y`
2. **Zainstaluj eccodes i cfgrib przez conda-forge** (WAŻNE!)
3. **Zainstaluj pozostałe biblioteki:** `conda run -n gfs314 pip install -r requirements.txt`
4. **Skonfiguruj bazę danych i config.ini**
5. **Uruchom:** `conda activate gfs314` → `python gfs_downloader_daemon.py`

---

## 📞 Jeśli nadal nie działa

1. Sprawdź logi w katalogu `logs/`
2. Sprawdź czy wszystkie kroki zostały wykonane
3. Porównaj wersje bibliotek z komputerem gdzie działa:
   ```powershell
   conda run -n gfs314 pip list
   ```
4. Sprawdź czy pliki GRIB2 są pobierane (katalog `temp/`)

---

**Powodzenia! 🎉**

Po wykonaniu wszystkich kroków program powinien działać identycznie jak na komputerze w pracy.

