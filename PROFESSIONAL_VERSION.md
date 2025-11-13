# 🌟 GFS Downloader - PROFESSIONAL VERSION

## 📋 Przegląd

**PROFESSIONAL VERSION** to zaawansowana wersja pobieracza danych pogodowych GFS, która pobiera **pełny zakres 209 prognoz** w sposób optymalny i zautomatyzowany.

## ✨ Funkcje

### ✅ Pełny zakres prognoz

- **f000-f120** (5 dni co 1h) = **121 prognoz**
- **f123-f384** (dni 6-16 co 3h) = **88 prognoz**
- **RAZEM: 209 prognoz!**

### ✅ Priorytetyzacja

Najświeższe prognozy są pobierane jako pierwsze:
- **f000** → **f001** → **f002** → ... → **f120** (co 1h)
- **f123** → **f126** → **f129** → ... → **f384** (co 3h)

### ✅ Multi-threading

Równoległe pobieranie i przetwarzanie:
- **4-8 wątków** równolegle (domyślnie 6)
- Każdy wątek pobiera i przetwarza niezależnie
- Automatyczna synchronizacja

### ✅ Resume (Kontynuacja)

- Sprawdza **co już jest w bazie**
- Kontynuuje od miejsca przerwania
- **Nie pobiera duplikatów**

### ✅ Zapis na bieżąco

- Każda prognoza jest **zapisywana od razu** do bazy
- Nie trzeba czekać do końca całego pobierania
- Bezpieczeństwo danych przy przerwaniu

### ✅ Progress Bar

- Wizualny postęp pobierania
- Statystyki na bieżąco (OK, FAIL, Rekordy)
- Informacje o błędach

### ✅ Optymalizacja

- Sprawdza dostępność przed pobraniem
- Automatyczne czyszczenie plików tymczasowych
- Efektywne wykorzystanie pamięci

## 🗂️ Struktura bazy danych

Tabela `gfs_forecast` zawiera następujące **kluczowe pola**:

| Pole | Opis | Przykład |
|------|------|----------|
| `forecast_time` | **Data/godzina prognozy** (na jaką godzinę jest prognoza) | `2025-11-03 09:00:00` |
| `run_time` | Data/godzina uruchomienia modelu GFS | `2025-11-03 06:00:00` |
| `created_at` | Data/godzina dodania do bazy | `2025-11-03 09:57:06` |
| `lat`, `lon` | Współrzędne geograficzne | `50.0`, `19.0` |

### 📌 Ważne!

**Nie trzeba dodawać dodatkowego pola** - pole `forecast_time` już przechowuje informację o tym, na jaką datę/godzinę jest prognoza!

- `forecast_time` = czas prognozy (np. f003 = run_time + 3h)
- `run_time` = czas uruchomienia modelu (np. 06:00 UTC)
- `created_at` = czas dodania do bazy

## 🚀 Instalacja

### 1. Wymagania

```bash
pip install -r requirements.txt
```

Nowe wymagania:
- `tqdm==4.66.1` (progress bar)

### 2. Konfiguracja

Upewnij się, że plik `config.ini` jest poprawnie skonfigurowany:

```ini
[database]
user = root
password = 
host = localhost
database = dane_gfs

[region]
lat_min = 49.0
lat_max = 55.0
lon_min = 14.0
lon_max = 24.0
```

### 3. Baza danych

Upewnij się, że baza danych istnieje:

```bash
mysql -u root < setup_database.sql
```

LUB ręcznie utwórz tabelę (zobacz `setup_database.sql`).

## 📖 Użycie

### Podstawowe uruchomienie

```bash
python gfs_downloader_professional.py
```

### Co się dzieje?

1. **Sprawdza dostępność** najnowszego run GFS (00, 06, 12, 18 UTC)
2. **Sprawdza bazę** - jakie prognozy już są pobrane (RESUME)
3. **Generuje listę** 209 prognoz do pobrania
4. **Uruchamia wątki** - równoległe pobieranie i przetwarzanie
5. **Zapisuje na bieżąco** - każda prognoza od razu do bazy
6. **Pokazuje postęp** - progress bar z statystykami
7. **Podsumowanie** - statystyki końcowe

### Przykładowy output

```
======================================================================
GFS Weather Data Downloader - PROFESSIONAL VERSION
======================================================================
✓ Konfiguracja OK
  Region: 49.0°-55.0°N, 14.0°-24.0°E
  Wątki: 6

⏳ Łączenie z MySQL...
✓ MySQL OK: dane_gfs

⏳ Szukam najnowszego run GFS...
✓ Run znaleziony: 2025-11-03 06:00 UTC

⏳ Sprawdzam co już jest w bazie...
✓ Znaleziono 45 istniejących prognoz w bazie
  Będę kontynuować od miejsca przerwania (RESUME)

⏳ Generowanie listy prognoz...
✓ Wygenerowano 209 prognoz do pobrania
✓ Do pobrania: 164 prognoz
✓ Już w bazie: 45 prognoz

⏳ Rozpoczynam pobieranie 164 prognoz...
  Używam 6 wątków równolegle
  Priorytet: najświeższe pierwsze (f000, f001, f002...)

Pobieranie: 100%|████████████| 164/164 [15:23<00:00, OK: 162, FAIL: 2, Rekordy: 58420]

======================================================================
✓✓✓ POBRANIE ZAKOŃCZONE!
======================================================================
Run GFS:          2025-11-03 06:00 UTC
Prognoz pobrano:   162 / 164
Prognoz błędów:    2
Rekordów w bazie:  58420
Prognoz w bazie:   207 / 209
======================================================================

✓ Końcowa liczba prognoz w bazie: 207

💡 Wszystkie dane są już zapisane w bazie!
   Tabela: gfs_forecast
   Baza: dane_gfs
```

## 🔧 Konfiguracja zaawansowana

### Liczba wątków

W pliku `gfs_downloader_professional.py` można zmienić:

```python
NUM_THREADS = 6  # Zmień na 4-8 (zalecane: 6)
```

**Zalecenia:**
- **4 wątki** - stabilniejsze, mniej obciąża serwer
- **6 wątków** - optymalne dla większości przypadków (domyślnie)
- **8 wątków** - szybsze, ale może być niestabilne przy słabym połączeniu

### Timeout

Domyślnie timeout na pobranie to 300 sekund (5 minut). Można zmienić w funkcji `download_and_process()`:

```python
response = requests.get(url, stream=True, timeout=300)  # Zmień na potrzebną wartość
```

## 📊 Struktura danych

### Przykładowe zapytanie SQL

```sql
-- Wszystkie prognozy dla danego czasu prognozy
SELECT * FROM gfs_forecast
WHERE forecast_time = '2025-11-03 12:00:00'
AND lat BETWEEN 50 AND 52
AND lon BETWEEN 19 AND 21;

-- Ostatnie prognozy dla konkretnego punktu
SELECT forecast_time, t2m, wind_speed, prmsl
FROM gfs_forecast
WHERE lat = 50.0 AND lon = 19.0
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
ORDER BY forecast_time;
```

### Różnica między `forecast_time` a `run_time`

| Parametr | Opis | Przykład dla f003 |
|----------|------|-------------------|
| `run_time` | Kiedy uruchomiono model GFS | `2025-11-03 06:00:00` |
| `forecast_time` | Dla jakiego czasu jest prognoza | `2025-11-03 09:00:00` |
| Wzór | `forecast_time = run_time + forecast_hour` | `06:00 + 3h = 09:00` |

## ⚠️ Rozwiązywanie problemów

### Problem: "Nie znaleziono dostępnego run GFS"

**Rozwiązanie:**
- Sprawdź połączenie internetowe
- GFS może być opóźniony - spróbuj za 30-60 minut
- Uruchom ponownie później

### Problem: "BŁĄD MySQL"

**Rozwiązanie:**
- Sprawdź czy MySQL/XAMPP jest uruchomiony
- Sprawdź dane w `config.ini`
- Sprawdź czy baza danych `dane_gfs` istnieje

### Problem: "FAIL: 2" (błędy pobierania)

**Rozwiązanie:**
- To normalne - niektóre prognozy mogą być niedostępne
- Uruchom ponownie - RESUME pobierze brakujące
- Sprawdź logi (będą pokazane w progress bar)

### Problem: Duplikaty w bazie

**Rozwiązanie:**
- Program automatycznie sprawdza duplikaty
- Jeśli są, można je usunąć:

```sql
-- Usuń duplikaty (zostaw najnowsze)
DELETE t1 FROM gfs_forecast t1
INNER JOIN gfs_forecast t2
WHERE t1.id < t2.id
AND t1.run_time = t2.run_time
AND t1.forecast_time = t2.forecast_time
AND t1.lat = t2.lat
AND t1.lon = t2.lon;
```

## 📈 Statystyki

### Typowy czas pobierania

- **209 prognoz** = ~15-20 minut (przy 6 wątkach)
- **Każda prognoza** = ~2-5 sekund (zależy od połączenia)
- **Rozmiar danych** = ~500 MB (suma wszystkich plików GRIB2)
- **Rekordy w bazie** = ~360 rekordów na prognozę × 209 = ~75,000 rekordów

### Zużycie zasobów

- **Pamięć RAM**: ~500 MB - 1 GB (zależy od regionu)
- **Dysk**: ~1 GB (tymczasowe pliki są usuwane)
- **Sieć**: ~10-50 Mbps (zależy od połączenia)

## 🔄 Resume (Kontynuacja)

Program automatycznie kontynuuje przerwane pobieranie:

1. Sprawdza `run_time` w bazie
2. Sprawdza `forecast_time` dla danego `run_time`
3. Pomija już pobrane prognozy
4. Kontynuuje od miejsca przerwania

**Przykład:**
- Pobrano 50/209 prognoz
- Program przerwany (błąd, restart, itp.)
- Uruchom ponownie → automatycznie kontynuuje od 51. prognozy

## 📝 Zmiany w stosunku do poprzednich wersji

| Funkcja | SMART V2 | PROFESSIONAL |
|---------|----------|--------------|
| Liczba prognoz | 1 (f003) | **209** (f000-f384) |
| Multi-threading | ❌ | ✅ (4-8 wątków) |
| Resume | ❌ | ✅ |
| Progress bar | ❌ | ✅ |
| Priorytetyzacja | ❌ | ✅ |
| Zapis na bieżąco | ❌ | ✅ |

## 🎯 Najlepsze praktyki

1. **Uruchamiaj regularnie** - najlepiej co 6h (po każdym nowym run GFS)
2. **Używaj 6 wątków** - optymalne dla większości przypadków
3. **Monitoruj postęp** - sprawdzaj progress bar
4. **Resume działa automatycznie** - możesz przerwać i wznowić
5. **Sprawdzaj bazę** - używaj SQL do weryfikacji danych

## 📞 Wsparcie

W przypadku problemów:

1. Sprawdź logi (progress bar pokazuje błędy)
2. Sprawdź bazę danych (czy są dane)
3. Sprawdź połączenie internetowe
4. Uruchom ponownie (RESUME automatycznie kontynuuje)

## ✅ Podsumowanie

**PROFESSIONAL VERSION** to kompletne rozwiązanie do pobierania pełnego zakresu prognoz GFS:

- ✅ **209 prognoz** (f000-f384)
- ✅ **Multi-threading** (4-8 wątków)
- ✅ **Resume** (automatyczna kontynuacja)
- ✅ **Progress bar** (wizualny postęp)
- ✅ **Priorytetyzacja** (najświeższe pierwsze)
- ✅ **Zapis na bieżąco** (bezpieczeństwo danych)

**Gotowe do użycia!** 🚀






