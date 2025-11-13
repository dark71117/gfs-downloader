# ❓ FAQ - Najczęściej Zadawane Pytania

## Ogólne

### Czym jest GFS?
GFS (Global Forecast System) to globalny model prognozy numerycznej pogody prowadzony przez amerykańską agencję NOAA. Jest aktualizowany co 6 godzin i dostarcza prognozy do 16 dni w przód.

### Jak często model jest aktualizowany?
GFS jest publikowany 4 razy dziennie o godzinach:
- 00:00 UTC
- 06:00 UTC
- 12:00 UTC
- 18:00 UTC

Dane są dostępne z opóźnieniem ~3-4 godziny po czasie run'u.

### Jaka jest rozdzielczość danych?
Skrypt pobiera dane w rozdzielczości 0.25° × 0.25°, co odpowiada około 28 km.

### Czy dane są darmowe?
Tak! Dane GFS z NOAA są całkowicie darmowe i dostępne publicznie.

---

## Instalacja

### Dlaczego potrzebuję conda zamiast pip?
Biblioteka `eccodes` (wymagana do odczytu plików GRIB2) wymaga binarnych zależności systemowych, które najłatwiej zainstalować przez conda.

### Czy mogę użyć pip zamiast conda?
Teoretycznie tak, ale na Windows instalacja eccodes przez pip może być problematyczna. Conda jest zalecaną metodą.

### Skrypt nie działa po instalacji pip
Jeśli zainstalowałeś przez `pip install -r requirements.txt` i masz błędy z cfgrib:
1. Odinstaluj: `pip uninstall cfgrib eccodes`
2. Zainstaluj conda
3. Zainstaluj przez conda: `conda install -c conda-forge cfgrib eccodes`

### Jak długo trwa pierwsza instalacja?
- Python: 5-10 minut
- XAMPP: 5-10 minut
- Biblioteki Python (pip): 5-15 minut
- Biblioteki przez conda: 10-20 minut
Łącznie: 30-60 minut

---

## Konfiguracja

### Jak zmienić region pobierania danych?
Edytuj plik `config.ini`:
```ini
[region]
lat_min = 49.0  # Minimalna szerokość
lat_max = 55.0  # Maksymalna szerokość
lon_min = 14.0  # Minimalna długość
lon_max = 24.0  # Maksymalna długość
```

Przykłady:
- Polska: lat_min=49, lat_max=54.9, lon_min=14.1, lon_max=24.2
- Europa: lat_min=35, lat_max=70, lon_min=-10, lon_max=40
- Świat: lat_min=-90, lat_max=90, lon_min=-180, lon_max=180

**UWAGA:** Im większy region, tym dłużej trwa pobieranie!

### Jak zmienić hasło do MySQL?
1. Ustaw hasło w XAMPP
2. Edytuj `config.ini`:
```ini
[database]
password = twoje_haslo
```

### Czy mogę zmienić nazwę bazy danych?
Tak, w `config.ini`:
```ini
[database]
database = moja_baza
```
Pamiętaj aby utworzyć tę bazę w MySQL!

---

## Użytkowanie

### Jak często uruchamiać skrypt?
Zalecane: co 6 godzin (synchronicznie z publikacją GFS)

Możesz ustawić w Harmonogramie zadań Windows:
- 04:00, 10:00, 16:00, 22:00 (czasu lokalnego dla UTC+2)

### Ile danych jest pobieranych?
- Rozmiar pobrania: ~20-50 MB (zależnie od regionu)
- Liczba rekordów: 2000-5000 (dla Polski)
- Rozmiar w bazie: ~5-15 MB

### Czy mogę pobrać więcej prognoz do przodu?
Tak! W pliku `gfs_downloader.py` zmień linię:
```python
FILE_URL = BASE_URL + f"gfs.t{RUN_HOUR}z.pgrb2.0p25.f003"
```

Gdzie `f003` to godziny do przodu:
- `f000` - analiza (czas aktualny)
- `f003` - prognoza +3h
- `f006` - prognoza +6h
- `f024` - prognoza +24h
- `f120` - prognoza +5 dni
- `f384` - prognoza +16 dni

**UWAGA:** Możesz pobrać wiele plików w pętli!

### Czy mogę pobrać dane historyczne?
Tak, zmień zmienną `RUN_DATE` na konkretną datę:
```python
RUN_DATE = "20241101"  # 1 listopada 2024
RUN_HOUR = "00"
```

Dane historyczne są dostępne na NOAA przez ~10 dni.

---

## Baza danych

### Jak duża będzie baza danych?
Dla Polski, przy codziennym uruchamianiu:
- 1 dzień: ~10 MB
- 1 tydzień: ~70 MB
- 1 miesiąc: ~300 MB
- 1 rok: ~3.6 GB

### Jak często czyścić stare dane?
Skrypt automatycznie usuwa prognozy starsze niż 12 godzin. Możesz zmienić to w kodzie:
```python
DELETE FROM gfs_forecast 
WHERE run_time < DATE_SUB(NOW(), INTERVAL 12 HOUR)
```

### Czy mogę użyć PostgreSQL zamiast MySQL?
Tak! Zmień w kodzie:
```python
MYSQL_URL = f"postgresql://{user}:{password}@{host}/{database}"
```
I zainstaluj: `pip install psycopg2`

### Jak eksportować dane z MySQL?
W phpMyAdmin:
1. Wybierz tabelę `gfs_forecast`
2. Kliknij "Eksportuj"
3. Wybierz format (CSV, SQL, JSON)
4. Pobierz plik

---

## Błędy

### "Connection refused" przy łączeniu z MySQL
**Przyczyny:**
1. MySQL nie jest uruchomiony
2. Nieprawidłowe hasło
3. Baza danych nie istnieje

**Rozwiązanie:**
1. Uruchom MySQL w XAMPP
2. Sprawdź hasło w config.ini
3. Utwórz bazę `dane_gfs` w phpMyAdmin

### "No module named 'cfgrib'"
**Rozwiązanie:**
```bash
conda install -c conda-forge cfgrib
```

### "Unable to find GRIB definition"
**Rozwiązanie:**
```bash
conda install -c conda-forge eccodes
```

### "404 Not Found" przy pobieraniu
**Przyczyny:**
1. Dane jeszcze nie są dostępne (zbyt świeży run)
2. Błędna data/godzina
3. Problem z serwerem NOAA

**Rozwiązanie:**
- Zaczekaj 30-60 minut i spróbuj ponownie
- Sprawdź dostępność: https://nomads.ncep.noaa.gov/

### "Memory Error" przy dużych regionach
**Rozwiązanie:**
- Zmniejsz region w config.ini
- Zwiększ RAM
- Pobieraj dane w częściach

### Skrypt działa bardzo wolno
**Przyczyny:**
1. Wolne połączenie internetowe
2. Zbyt duży region
3. Słaby komputer

**Rozwiązanie:**
- Zmniejsz region
- Użyj szybszego internetu
- Pobieraj dane w nocy

---

## Laravel

### Jak połączyć Laravel z bazą GFS?
Zobacz plik `laravel_examples.php` - zawiera gotowe przykłady!

### Jak wyświetlić pogodę na stronie?
```php
// Kontroler
public function weather() {
    $data = DB::table('gfs_forecast')
        ->orderBy('forecast_time')
        ->limit(24)
        ->get();
    return view('weather', compact('data'));
}

// Blade
@foreach($data as $forecast)
    <p>{{ $forecast->forecast_time }}: {{ $forecast->t2m }}°C</p>
@endforeach
```

### Jak zoptymalizować zapytania?
1. Dodaj indeksy:
```sql
CREATE INDEX idx_lat_lon ON gfs_forecast(lat, lon);
CREATE INDEX idx_time ON gfs_forecast(forecast_time);
```

2. Użyj cache:
```php
$weather = Cache::remember('weather', 3600, function() {
    return DB::table('gfs_forecast')->get();
});
```

---

## Zaawansowane

### Jak pobrać wiele prognoz (f000 do f120)?
Dodaj pętlę w skrypcie:
```python
for forecast_hour in range(0, 121, 3):  # 0, 3, 6, ..., 120
    FILE_URL = BASE_URL + f"gfs.t{RUN_HOUR}z.pgrb2.0p25.f{forecast_hour:03d}"
    # ... pobierz i zapisz
```

### Jak dodać więcej parametrów pogodowych?
W pliku `gfs_downloader.py` dodaj do słownika `variables`:
```python
variables = {
    # ... istniejące ...
    "soilm": safe_get("soilm", None),  # Wilgotność gleby
    "snow": safe_get("snow", None),    # Śnieg
}
```

Pełna lista dostępnych parametrów: https://www.nco.ncep.noaa.gov/pmb/products/gfs/

### Jak uruchomić w Docker?
1. Stwórz Dockerfile:
```dockerfile
FROM python:3.11
RUN pip install -r requirements.txt
CMD ["python", "gfs_downloader.py"]
```

2. Zbuduj: `docker build -t gfs .`
3. Uruchom: `docker run gfs`

### Jak zrobić API z danymi?
Użyj Flask:
```python
from flask import Flask, jsonify
import pymysql

app = Flask(__name__)

@app.route('/weather/<lat>/<lon>')
def weather(lat, lon):
    # Pobierz z bazy
    return jsonify(data)
```

---

## Wsparcie

### Gdzie szukać pomocy?
1. Przeczytaj INSTRUKCJA.md
2. Sprawdź ten FAQ
3. Przeszukaj błędy w Google
4. Zapytaj na forum Python/Laravel

### Jak zgłosić błąd?
1. Sprawdź czy błąd nie został już zgłoszony
2. Przygotuj:
   - Opis problemu
   - Komunikat błędu
   - Kroki do odtworzenia
3. Utwórz Issue na GitHub

### Czy mogę modyfikować kod?
Tak! Kod jest otwarty. Możesz go dowolnie modyfikować dla swoich potrzeb.

---

## Dodatkowe Zasoby

- NOAA GFS: https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast-system
- Dokumentacja cfgrib: https://github.com/ecmwf/cfgrib
- Parametry GFS: https://www.nco.ncep.noaa.gov/pmb/products/gfs/
- Forum meteo: https://forum.meteo.edu.pl

---

**Nie znalazłeś odpowiedzi?**  
Otwórz Issue na GitHub lub napisz na forum!
