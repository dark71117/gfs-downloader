# 🔄 Synchronizacja między komputerami (GitHub)

## ✅ Rozwiązanie problemu z bibliotekami

Projekt został skonfigurowany tak, aby **nie było problemów** z synchronizacją między komputerami:

### 📦 Co jest w repozytorium:

1. **`requirements.txt`** - z elastycznymi wersjami (`>=` zamiast `==`)
   - Działa z pip i venv
   - Automatycznie pobierze kompatybilne wersje

2. **`environment.yml`** - plik środowiska conda (ZALECANE)
   - Łatwe do zsynchronizowania
   - Zapewnia identyczne środowisko na obu komputerach

3. **`.gitignore`** - ignoruje lokalne pliki:
   - `config.ini` (z hasłami)
   - `venv/`, `__pycache__/`
   - Pliki tymczasowe

---

## 🚀 Szybka konfiguracja na nowym komputerze

**📖 ZOBACZ: `INSTALACJA_PELNA.md` - Kompletna instrukcja krok po kroku!**

### Opcja 1: Conda (ZALECANE - Windows)

```powershell
# 1. Sklonuj repozytorium
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader

# 2. Utwórz środowisko z Python 3.14.0
conda create -n gfs314 python=3.14.0 -y

# 3. ZAINSTALUJ ECCODES I CFGRIB PRZEZ CONDA-FORGE (WAŻNE!)
conda install -n gfs314 -c conda-forge eccodes cfgrib -y

# 4. Zainstaluj pozostałe biblioteki
conda run -n gfs314 pip install -r requirements.txt

# 5. Utwórz config.ini jeśli nie istnieje
if (!(Test-Path "config.ini")) { Copy-Item "config.ini.example" "config.ini" }

# 6. Skonfiguruj bazę danych MySQL (patrz INSTALACJA_PELNA.md)

# 7. Gotowe! Uruchom program
conda activate gfs314
python gfs_downloader_daemon.py
```

**⚠️ UWAGA:** `eccodes` i `cfgrib` MUSZĄ być zainstalowane przez conda-forge, inaczej parsowanie GRIB2 nie będzie działać!

### Opcja 2: Venv (Linux lub jeśli nie masz conda)

```bash
# 1. Sklonuj repozytorium
git clone https://github.com/twoj-username/gfs-downloader.git
cd gfs-downloader

# 2. Utwórz środowisko wirtualne
python3 -m venv venv

# 3. Aktywuj środowisko
source venv/bin/activate  # Linux/Mac
# LUB
venv\Scripts\activate  # Windows

# 4. Zainstaluj biblioteki
pip install -r requirements.txt

# 5. Skonfiguruj config.ini

# 6. Gotowe!
python gfs_downloader.py
```

---

## 🔄 Codzienna praca

### Pobieranie zmian z GitHub:

```bash
git pull origin main
```

**To wszystko!** Nie musisz nic więcej robić - biblioteki są już zainstalowane.

### Wysyłanie zmian:

```bash
git add .
git commit -m "Opis zmian"
git push origin main
```

---

## ⚠️ Kiedy trzeba zaktualizować biblioteki?

**Tylko wtedy, gdy:**
- Dodajesz **nową bibliotekę** do projektu
- Ktoś dodał nową bibliotekę i zaktualizował `requirements.txt` lub `environment.yml`

**Wtedy wykonaj:**

```bash
# Conda:
conda activate gfs
conda env update -f environment.yml --prune

# LUB Venv:
pip install -r requirements.txt
```

---

## 📝 Dodawanie nowej biblioteki

Jeśli dodajesz nową funkcjonalność wymagającą nowej biblioteki:

1. **Zainstaluj lokalnie:**
   ```bash
   conda activate gfs
   pip install nowa-biblioteka
   ```

2. **Zaktualizuj pliki:**
   ```bash
   # Automatycznie zaktualizuj requirements.txt:
   pip freeze > requirements_temp.txt
   # Skopiuj nową bibliotekę do requirements.txt
   
   # LUB ręcznie dodaj do requirements.txt:
   # nowa-biblioteka>=1.0.0
   ```

3. **Zaktualizuj environment.yml** (jeśli używasz conda):
   ```yaml
   - pip:
     - nowa-biblioteka>=1.0.0
   ```

4. **Commit i push:**
   ```bash
   git add requirements.txt environment.yml
   git commit -m "Dodano nowa-biblioteka"
   git push
   ```

5. **Na drugim komputerze:**
   ```bash
   git pull
   conda env update -f environment.yml --prune
   # LUB
   pip install -r requirements.txt
   ```

---

## 🎯 Podsumowanie

✅ **Nie musisz** aktualizować bibliotek przy każdym `git pull`  
✅ **Nie musisz** dodawać nic do requirements.txt przy zwykłych zmianach kodu  
✅ **Musisz** zaktualizować tylko gdy dodajesz nową bibliotekę  
✅ **Każdy komputer** ma swój `config.ini` (nie jest w repozytorium)  

**Wszystko działa automatycznie!** 🎉

