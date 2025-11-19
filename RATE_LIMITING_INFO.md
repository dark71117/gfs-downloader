# Rate Limiting i HTTP 429 - Informacje

## Implementacja

Program automatycznie obsługuje:
- **Rate limiting**: Maksymalnie 120 zapytań/minutę (1 zapytanie co 0.5 sekundy)
- **HTTP 429**: Automatyczne wykrywanie i obsługa z retry po czasie z nagłówka `Retry-After`
- **Thread-safe**: Rate limiting działa poprawnie przy wielu wątkach

## Jak działa

### Rate Limiting
- Przed każdym zapytaniem HTTP program sprawdza liczbę zapytań w ostatniej minucie
- Jeśli jest już 120 zapytań, czeka aż najstarsze zapytanie będzie starsze niż 60 sekund
- Minimalne opóźnienie 0.5 sekundy między zapytaniami

### HTTP 429 (Too Many Requests)
- Gdy serwer zwróci kod 429, program:
  1. Loguje ostrzeżenie: `⚠️ HTTP 429 (Too Many Requests)`
  2. Odczytuje nagłówek `Retry-After` (domyślnie 60 sekund)
  3. Czeka określony czas
  4. Próbuje ponownie

## GRIB Filter - Opcjonalne ulepszenie

**Obecnie**: Program pobiera pełne pliki GRIB2 (~500MB każdy) i filtruje je lokalnie.

**GRIB Filter API NOMADS**: Pozwala na pobieranie tylko wybranych parametrów z pliku GRIB2, co:
- Zmniejsza rozmiar pobieranych danych (np. z 500MB do 50MB)
- Zmniejsza obciążenie serwera
- Zmniejsza ryzyko przekroczenia limitu 120 zapytań/min

### Jak użyć GRIB Filter (zaawansowane)

NOMADS pozwala na pobieranie tylko wybranych części pliku używając:
1. Pliku `.idx` (index) - zawiera informacje o offsetach parametrów w pliku GRIB2
2. Parametrów w URL - można określić które parametry pobrać

**Przykład URL z filtrem**:
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.20240115/00/atmos/gfs.t00z.pgrb2.0p25.f000?var=t2m&var=d2m&var=u10&var=v10
```

**Uwaga**: To wymaga:
- Parsowania pliku `.idx` do określenia offsetów
- Używania `Range` headers w HTTP do pobrania tylko wybranych części pliku
- Znacznie bardziej złożonej implementacji

**Obecna implementacja** jest prostsza i działa dobrze, ale pobiera pełne pliki.

## Monitorowanie

Program loguje wszystkie wystąpienia HTTP 429:
- W logach głównych: `⚠️ HTTP 429 (Too Many Requests)`
- W szczegółowych logach: informacje o czasie oczekiwania

Jeśli często widzisz HTTP 429:
1. Zmniejsz liczbę wątków w `config.ini` (mniej równoległych pobierań)
2. Zwiększ opóźnienia między zapytaniami (zmień `0.5` na większą wartość w kodzie)
3. Rozważ użycie GRIB Filter API (wymaga modyfikacji kodu)

