# 🚀 Szybka pomoc - Uruchamianie programu

## ⚠️ Problem: "Brak pliku config.ini"

**Rozwiązanie:**
Plik `config.ini` został automatycznie utworzony z `config.ini.example`. 
Edytuj go i ustaw hasło do MySQL (jeśli masz).

## ⚠️ Problem: "ModuleNotFoundError: No module named 'sqlalchemy'"

**Rozwiązanie:**
Używasz niewłaściwego środowiska Python! Musisz używać środowiska conda `gfs`.

### W PowerShell:
```powershell
# Metoda 1: Użyj skryptu PowerShell
.\uruchom.ps1

# Metoda 2: Użyj conda run
conda run -n gfs python gfs_downloader.py

# Metoda 3: Aktywuj środowisko najpierw
conda activate gfs
python gfs_downloader.py
```

### W CMD:
```cmd
# Kliknij dwukrotnie uruchom.bat
# LUB
uruchom.bat
```

## ⚠️ Problem: "uruchom.bat nie jest rozpoznawany w PowerShell"

**Rozwiązanie:**
W PowerShell musisz używać `.\uruchom.bat` zamiast `uruchom.bat`:

```powershell
.\uruchom.bat
```

**LUB** użyj skryptu PowerShell:
```powershell
.\uruchom.ps1
```

## 📝 Jak uruchomić program:

### Opcja 1: Przez plik BAT (CMD)
```cmd
uruchom.bat
```

### Opcja 2: Przez PowerShell
```powershell
.\uruchom.ps1
# LUB
.\uruchom.bat
```

### Opcja 3: Bezpośrednio przez conda
```powershell
conda run -n gfs python gfs_downloader.py
```

### Opcja 4: Daemon (działa w tle)
```powershell
.\uruchom_daemon.ps1
# LUB
conda run -n gfs python gfs_downloader_daemon.py
```

## ✅ Sprawdzenie czy wszystko działa:

```powershell
# 1. Sprawdź czy środowisko conda istnieje
conda env list

# 2. Sprawdź czy biblioteki są zainstalowane
conda run -n gfs python -c "import pandas, xarray, sqlalchemy; print('OK')"

# 3. Sprawdź czy config.ini istnieje
Test-Path config.ini
```

## 🔧 Jeśli nadal nie działa:

1. **Sprawdź czy środowisko conda `gfs` istnieje:**
   ```powershell
   conda env list
   ```
   Jeśli nie ma, utwórz je:
   ```powershell
   conda env create -f environment.yml
   ```

2. **Sprawdź czy biblioteki są zainstalowane:**
   ```powershell
   conda run -n gfs pip list
   ```
   Jeśli brakuje, zainstaluj:
   ```powershell
   conda run -n gfs pip install -r requirements.txt
   ```

3. **Sprawdź czy config.ini istnieje:**
   ```powershell
   if (!(Test-Path "config.ini")) { Copy-Item "config.ini.example" "config.ini" }
   ```

---

**Wszystko gotowe? Uruchom program i ciesz się danymi pogodowymi!** 🌦️

