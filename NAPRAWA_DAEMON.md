# 🔧 Naprawa daemona - Automatyczne wznowienie po problemach sieciowych

## Problem

Daemon przestawał działać gdy:
- Brak połączenia internetowego (NameResolutionError)
- Dysk się usypiał
- Nie wznowił automatycznie pracy po przywróceniu połączenia

## Rozwiązanie

Dodano następujące mechanizmy:

### 1. Sprawdzanie połączenia internetowego
- Daemon sprawdza połączenie co 5 minut
- Przed każdym sprawdzeniem dostępności danych
- Używa wielu serwerów testowych (Google, NOAA, DNS)

### 2. Automatyczne wznowienie
- Gdy połączenie zostanie przywrócone, daemon automatycznie wznawia pracę
- Loguje informację o przywróceniu połączenia
- Resetuje licznik błędów sieciowych

### 3. Keep-Alive dla dysku
- Zapisuje plik `logs/daemon_keep_alive.txt` co 5 minut
- Zapobiega usypianiu dysku
- Pokazuje że daemon jest aktywny

### 4. Inteligentne czekanie przy błędach
- Przy pojedynczych błędach: czeka 5 minut
- Przy wielu błędach (>10): czeka 10 minut
- Kontynuuje próby zamiast się zatrzymywać

## Jak to działa

```
1. Daemon sprawdza połączenie internetowe
   ↓
2. Jeśli brak połączenia:
   - Loguje błąd
   - Czeka 5-10 minut
   - Sprawdza ponownie
   ↓
3. Gdy połączenie wróci:
   - Loguje "Połączenie przywrócone"
   - Resetuje liczniki błędów
   - Wznawia normalną pracę
   ↓
4. Keep-alive zapisuje plik co 5 minut
   - Zapobiega usypianiu dysku
   - Pokazuje aktywność daemona
```

## Pliki

- `logs/daemon_keep_alive.txt` - plik keep-alive (aktualizowany co 5 minut)
- `logs/gfs_daemon_*.log` - główny log
- `logs/gfs_daemon_detailed_*.log` - szczegółowy log
- `logs/gfs_daemon_errors_*.log` - log błędów

## Sprawdzanie czy daemon działa

```powershell
# Sprawdź plik keep-alive
Get-Content logs\daemon_keep_alive.txt

# Sprawdź ostatnie logi
Get-Content logs\gfs_daemon_*.log -Tail 50
```

## Jeśli daemon się zatrzymał

1. Sprawdź logi błędów:
   ```powershell
   Get-Content logs\gfs_daemon_errors_*.log -Tail 20
   ```

2. Sprawdź czy daemon działa:
   ```powershell
   Get-Process python | Where-Object {$_.CommandLine -like "*gfs_downloader_daemon*"}
   ```

3. Uruchom ponownie:
   ```powershell
   conda activate gfs314
   python gfs_downloader_daemon.py
   ```

## Konfiguracja

W pliku `gfs_downloader_daemon.py`:

```python
CHECK_INTERVAL = 1200  # 20 minut - interwał sprawdzania nowych danych
NETWORK_ERROR_RETRY_INTERVAL = 300  # 5 minut - czekanie przy błędach sieciowych
MAX_NETWORK_ERRORS = 10  # Maksymalna liczba błędów przed dłuższą przerwą
KEEP_ALIVE_INTERVAL = 300  # 5 minut - zapis keep-alive
```

Możesz zmienić te wartości jeśli potrzeba.

---

**Daemon teraz automatycznie wznawia pracę po przywróceniu połączenia!** ✅

