# 📦 GFS Weather Data Downloader
## Instrukcja instalacji i użytkowania krok po kroku

---

## 📋 SPIS TREŚCI
1. [Wymagania](#wymagania)
2. [Instalacja Python](#instalacja-python)
3. [Instalacja XAMPP](#instalacja-xampp)
4. [Konfiguracja projektu](#konfiguracja-projektu)
5. [Uruchomienie](#uruchomienie)
6. [Rozwiązywanie problemów](#rozwiązywanie-problemów)
7. [Użycie w Laravel](#użycie-w-laravel)

---

## 🔧 WYMAGANIA

### System
- Windows 10/11
- Minimum 4 GB RAM
- Połączenie z internetem

### Oprogramowanie
- Python 3.9 lub nowszy
- XAMPP (z MySQL)
- Około 500 MB wolnego miejsca na dysku

---

## 🐍 INSTALACJA PYTHON

### Krok 1: Pobierz Pythona
1. Otwórz przeglądarkę i wejdź na: https://www.python.org/downloads/
2. Kliknij **"Download Python 3.12.x"** (najnowsza wersja)
3. Pobierz instalator (plik .exe)

### Krok 2: Zainstaluj Pythona
1. Uruchom pobrany instalator
2. **WAŻNE:** Zaznacz checkbox **"Add Python to PATH"** na dole okna
3. Kliknij **"Install Now"**
4. Poczekaj na zakończenie instalacji
5. Kliknij **"Close"**

### Krok 3: Sprawdź instalację
1. Otwórz **Wiersz polecenia** (CMD):
   - Naciśnij `Win + R`
   - Wpisz `cmd`
   - Naciśnij Enter
2. Wpisz: `python --version`
3. Powinieneś zobaczyć: `Python 3.12.x`

✅ Jeśli widzisz wersję Pythona - gotowe!  
❌ Jeśli pojawia się błąd - uruchom ponownie komputer i spróbuj jeszcze raz

---

## 🗄️ INSTALACJA XAMPP

### Krok 1: Pobierz XAMPP
1. Wejdź na: https://www.apachefriends.org/
2. Kliknij **"Download"** dla Windows
3. Pobierz wersję z PHP 8.x

### Krok 2: Zainstaluj XAMPP
1. Uruchom instalator
2. Wybierz komponenty:
   - ✅ Apache
   - ✅ MySQL
   - ✅ PHP
   - ✅ phpMyAdmin
3. Wskaż folder instalacji (np. `C:\xampp`)
4. Dokończ instalację

### Krok 3: Uruchom MySQL
1. Otwórz **XAMPP Control Panel**
2. Kliknij **"Start"** przy **MySQL**
3. Przycisk powinien zmienić kolor na zielony

---

## ⚙️ KONFIGURACJA PROJEKTU

### Krok 1: Wypakuj pliki
1. Pobierz plik `gfs_downloader.zip`
2. Wypakuj do folderu, np. `C:\gfs_downloader`
3. W folderze powinny być pliki:
   ```
   C:\gfs_downloader\
   ├── gfs_downloader.py
   ├── config.ini
   ├── requirements.txt
   ├── setup_database.sql
   ├── uruchom.bat
   └── INSTRUKCJA.md
   ```

### Krok 2: Utwórz bazę danych
1. Otwórz przeglądarkę
2. Wejdź na: http://localhost/phpmyadmin
3. Kliknij zakładkę **"SQL"** u góry
4. Otwórz plik `setup_database.sql` w Notatniku
5. Skopiuj całą zawartość
6. Wklej do pola SQL w phpMyAdmin
7. Kliknij **"Wykonaj"** (Execute)
8. Sprawdź czy po lewej stronie pojawiła się baza **dane_gfs**

✅ Baza danych utworzona!

### Krok 3: Zainstaluj biblioteki Python
1. Otwórz **Wiersz polecenia** (CMD)
2. Przejdź do folderu projektu:
   ```
   cd C:\gfs_downloader
   ```
3. Zainstaluj biblioteki (UWAGA: to zajmie kilka minut):
   ```
   pip install -r requirements.txt
   ```
4. Poczekaj na komunikat o zakończeniu

⚠️ **WAŻNE:** Instalacja `cfgrib` może wymagać dodatkowych kroków!

### Krok 4: Zainstaluj eccodes (wymagane dla GRIB2)

#### Opcja A: Przez conda (ZALECANE)
1. Pobierz Miniconda: https://docs.conda.io/en/latest/miniconda.html
2. Zainstaluj Miniconda
3. Otwórz **Anaconda Prompt**
4. Wykonaj:
   ```
   conda create -n gfs python=3.11
   conda activate gfs
   conda install -c conda-forge eccodes cfgrib
   pip install -r requirements.txt
   ```

#### Opcja B: Ręczna instalacja (dla zaawansowanych)
1. Pobierz eccodes: https://confluence.ecmwf.int/display/ECC/ecCodes+Home
2. Postępuj zgodnie z instrukcją instalacji
3. Ustaw zmienną środowiskową `ECCODES_DIR`

### Krok 5: Sprawdź konfigurację
1. Otwórz plik `config.ini` w Notatniku
2. Sprawdź ustawienia bazy danych:
   ```ini
   [database]
   user = root
   password = 
   host = localhost
   database = dane_gfs
   ```
3. Jeśli masz hasło do MySQL, wpisz je po `password = `
4. Sprawdź region (domyślnie: Polska):
   ```ini
   [region]
   lat_min = 49.0
   lat_max = 55.0
   lon_min = 14.0
   lon_max = 24.0
   ```

---

## 🚀 URUCHOMIENIE

### Metoda 1: Przez plik BAT (najprostsza)
1. Upewnij się, że XAMPP/MySQL jest uruchomiony
2. Kliknij dwukrotnie plik **`uruchom.bat`**
3. Poczekaj 1-2 minuty na pobranie danych
4. Sprawdź komunikaty w oknie

### Metoda 2: Przez wiersz polecenia
1. Otwórz CMD
2. Przejdź do folderu:
   ```
   cd C:\gfs_downloader
   ```
3. Uruchom skrypt:
   ```
   python gfs_downloader.py
   ```

### Co powinno się stać?
Po uruchomieniu zobaczysz:
```
============================================================
GFS Weather Data Downloader - Start
============================================================
✓ Konfiguracja wczytana
✓ URL przygotowany
⏳ Pobieranie danych (może zająć 1-2 minuty)...
✓ Dane pobrane (25.3 MB)
✓ Dane sparsowane
✓ Znaleziono 20 parametrów
✓ Tabela utworzona: 2450 wierszy
✓ Połączono z bazą: dane_gfs
✓ Zapisano 2450 rekordów do tabeli 'gfs_forecast'
✓✓✓ SUKCES! Dane GFS pobrane i zapisane
============================================================
```

---

## ❓ ROZWIĄZYWANIE PROBLEMÓW

### Problem: "Python nie jest rozpoznawany jako polecenie"
**Rozwiązanie:**
1. Sprawdź czy Python jest w PATH:
   - Otwórz CMD
   - Wpisz: `echo %PATH%`
   - Szukaj ścieżki typu `C:\Users\...\Python312`
2. Jeśli nie ma:
   - Przeinstaluj Pythona
   - Zaznacz **"Add Python to PATH"**

### Problem: "MySQL connection refused"
**Rozwiązanie:**
1. Otwórz XAMPP Control Panel
2. Sprawdź czy MySQL jest uruchomiony (zielony przycisk)
3. Jeśli nie - kliknij **"Start"**
4. Sprawdź port (domyślnie 3306)
5. Sprawdź hasło w `config.ini`

### Problem: "No module named 'cfgrib'"
**Rozwiązanie:**
1. Zainstaluj przez conda (patrz wyżej)
2. LUB zainstaluj ręcznie:
   ```
   pip install cfgrib
   pip install eccodes
   ```

### Problem: "Unable to find GRIB definition"
**Rozwiązanie:**
1. Pobierz eccodes przez conda:
   ```
   conda install -c conda-forge eccodes
   ```

### Problem: Dane się nie pobierają (404 error)
**Rozwiązanie:**
1. Model GFS jest publikowany co 6 godzin (00, 06, 12, 18 UTC)
2. Nowe dane są dostępne z opóźnieniem ~3-4 godziny
3. Zaczekaj 1 godzinę i spróbuj ponownie
4. Sprawdź dostępność na: https://nomads.ncep.noaa.gov/

### Problem: "Connection timeout"
**Rozwiązanie:**
1. Sprawdź połączenie internetowe
2. Wyłącz firewall/antywirus tymczasowo
3. Użyj VPN jeśli NOAA jest zablokowany

---

## 🔄 AUTOMATYZACJA (OPCJONALNIE)

### Uruchamianie co 6 godzin
1. Otwórz **Harmonogram zadań** (Task Scheduler)
2. Kliknij **"Utwórz zadanie podstawowe"**
3. Nazwa: "GFS Downloader"
4. Wyzwalacz: **"Codziennie"**
5. Akcja: **"Uruchom program"**
6. Program: `C:\gfs_downloader\uruchom.bat`
7. Zaawansowane: powtarzaj co 6 godzin

---

## 📊 UŻYCIE W LARAVEL

### Przykład zapytania w kontrolerze Laravel:

```php
<?php

namespace App\Http\Controllers;

use Illuminate\Support\Facades\DB;

class WeatherController extends Controller
{
    public function getLatestForecast($lat, $lon)
    {
        $data = DB::connection('mysql')->table('gfs_forecast')
            ->where('lat', '>=', $lat - 0.25)
            ->where('lat', '<=', $lat + 0.25)
            ->where('lon', '>=', $lon - 0.25)
            ->where('lon', '<=', $lon + 0.25)
            ->orderBy('forecast_time', 'asc')
            ->get();
        
        return response()->json($data);
    }
    
    public function getCurrentWeather()
    {
        // Pobierz najnowsze dane
        $weather = DB::table('gfs_forecast')
            ->select('*')
            ->orderBy('run_time', 'desc')
            ->limit(100)
            ->get();
        
        return view('weather.index', compact('weather'));
    }
}
```

### Konfiguracja połączenia w .env:
```
DB_CONNECTION_GFS=mysql
DB_HOST_GFS=localhost
DB_PORT_GFS=3306
DB_DATABASE_GFS=dane_gfs
DB_USERNAME_GFS=root
DB_PASSWORD_GFS=
```

### W config/database.php:
```php
'connections' => [
    'gfs' => [
        'driver' => 'mysql',
        'host' => env('DB_HOST_GFS', 'localhost'),
        'database' => env('DB_DATABASE_GFS', 'dane_gfs'),
        'username' => env('DB_USERNAME_GFS', 'root'),
        'password' => env('DB_PASSWORD_GFS', ''),
        'charset' => 'utf8mb4',
        'collation' => 'utf8mb4_unicode_ci',
    ],
],
```

---

## 📝 PARAMETRY POGODOWE W BAZIE

| Kolumna | Opis | Jednostka |
|---------|------|-----------|
| t2m | Temperatura 2m | °C |
| d2m | Punkt rosy | °C |
| rh | Wilgotność względna | % |
| u10, v10 | Składowe wiatru | m/s |
| wind_speed | Prędkość wiatru | m/s |
| wind_dir | Kierunek wiatru | stopnie |
| gust | Porywy wiatru | m/s |
| mslp | Ciśnienie | hPa |
| tp | Opady | mm |
| tcc | Zachmurzenie | % |
| vis | Widzialność | m |
| cape | CAPE (burze) | J/kg |

---

## 🆘 POMOC

### Potrzebujesz pomocy?
- GitHub Issues: [link do repo]
- Email: [twój email]
- Discord: [twój discord]

### Przydatne linki:
- NOAA GFS: https://nomads.ncep.noaa.gov/
- Python: https://www.python.org/
- XAMPP: https://www.apachefriends.org/
- Cfgrib: https://github.com/ecmwf/cfgrib

---

## 📜 LICENCJA

Ten skrypt jest dostępny na licencji MIT.
Dane GFS są własnością NOAA i są dostępne publicznie.

---

**Powodzenia! 🎉**

Jeśli wszystko działa - masz teraz automatyczny system pobierania danych pogodowych!
