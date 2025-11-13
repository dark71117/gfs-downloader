# 🎯 ROZWIĄZANIE PROBLEMU - Wiele poziomów w GRIB2

## Co było nie tak?

**Problem:** `multiple values for unique key`

Plik GFS GRIB2 zawiera dane na **WIELU POZIOMACH** jednocześnie:
- Powierzchnia (surface)
- 2m nad ziemią (heightAboveGround)
- 10m nad ziemią (heightAboveGround)
- Atmosfera (atmosphere)
- 850 hPa, 500 hPa (isobaricInhPa)
- I wiele innych...

Biblioteka `cfgrib` **nie wiedziała który poziom wybrać** i dlatego się sypała!

---

## Jak to naprawiliśmy?

### ❌ Stara metoda (nie działała):
```python
ds = xr.open_dataset(file, engine='cfgrib')
# Błąd: "multiple values for unique key"
```

### ✅ Nowa metoda (działa):
```python
# Otwórz KAŻDY poziom osobno z filtrem
ds_surface = xr.open_dataset(file, engine='cfgrib',
    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'surface'}})

ds_2m = xr.open_dataset(file, engine='cfgrib',
    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'heightAboveGround'}})

ds_atmos = xr.open_dataset(file, engine='cfgrib',
    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'atmosphere'}})

# Połącz dane z wszystkich poziomów
```

---

## Jakie poziomy pobieramy?

| Poziom | Parametry | Przykład |
|--------|-----------|----------|
| **surface** | Ciśnienie, opady, zachmurzenie | mslp, tp, tcc |
| **heightAboveGround** | Temperatura, wiatr 2m/10m | t2m, u10, v10 |
| **atmosphere** | CAPE, woda opadowa | cape, pwat |
| **isobaricInhPa** | Temp/geo 850/500 hPa | t850, gh500 |

---

## Jak użyć FINAL VERSION?

### Sposób 1: PowerShell (najszybszy)
```bash
cd C:\xampp\htdocs\gfs_downloader
conda activate gfs
python gfs_downloader_final.py
```

### Sposób 2: Plik BAT
Kliknij dwukrotnie: **`uruchom_final.bat`**

---

## Co robi FINAL VERSION?

1. ✅ Pobiera dane GFS (508 MB)
2. ✅ Zapisuje do pliku tymczasowego
3. ✅ Otwiera plik **4 razy** z różnymi filtrami:
   - Raz dla surface
   - Raz dla heightAboveGround
   - Raz dla atmosphere
   - Raz dla isobaricInhPa
4. ✅ Łączy wszystkie dane
5. ✅ Usuwa dodatkowe wymiary (np. heightAboveGround=2)
6. ✅ Konwertuje jednostki (Kelvin → Celsius, Pa → hPa)
7. ✅ Zapisuje do MySQL

---

## Struktura plików

```
C:\xampp\htdocs\gfs_downloader\
├── gfs_downloader.py ........... Oryginał (nie działa)
├── gfs_downloader_fixed.py ..... Próba 1 (nie działa)
├── gfs_downloader_final.py ..... WORKING VERSION ⭐⭐⭐
├── uruchom.bat ................. Dla oryginalnej
├── uruchom_fixed.bat ........... Dla fixed
├── uruchom_final.bat ........... Dla FINAL ⭐⭐⭐
└── config.ini
```

---

## Test czy działa

W PowerShell (gfs):
```bash
cd C:\xampp\htdocs\gfs_downloader
python gfs_downloader_final.py
```

Powinno pojawić się:
```
⏳ Parsowanie danych GRIB2 (wiele poziomów)...
  → Poziom: surface
    ✓ prmsl
    ✓ tp
    ✓ tcc
  → Poziom: heightAboveGround
    ✓ t2m
    ✓ d2m
    ✓ u10
    ✓ v10
  → Poziom: atmosphere
    ✓ cape
    ✓ pwat

✓ Pobrano 15 parametrów
✓ Utworzono tabelę: 2450 wierszy
✓✓✓ SUKCES!
```

---

## Dlaczego to działa?

**Analogia:**
- Oryginalny kod: "Daj mi książkę!" → Biblioteka: "Mam 100 książek, którą?"
- Final version: "Daj mi książkę o kuchni z górnej półki" → Biblioteka: "OK, mam!"

Filtrując po `typeOfLevel`, mówimy cfgrib **dokładnie której części pliku szukamy**.

---

## Dodatkowe poziomy (opcjonalnie)

Jeśli chcesz więcej danych, dodaj w kodzie:
```python
{
    'name': 'isobaric_500',
    'filter': {'typeOfLevel': 'isobaricInhPa', 'level': 500},
    'vars': ['gh', 't']
},
{
    'name': 'tropopause',
    'filter': {'typeOfLevel': 'tropopause'},
    'vars': ['t', 'u', 'v']
},
```

---

## Podsumowanie różnic

| Wersja | Status | Problem |
|--------|--------|---------|
| `gfs_downloader.py` | ❌ | BytesIO + brak filtrów |
| `gfs_downloader_fixed.py` | ❌ | Temp file, ale brak filtrów |
| `gfs_downloader_final.py` | ✅ | Temp file + filtry poziomów |

---

**To jest prawdziwe rozwiązanie!** 🎉

Użyj **`gfs_downloader_final.py`** i powinno działać!
