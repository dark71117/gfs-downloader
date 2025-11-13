# 🔧 SZYBKA POPRAWKA - KeyError

## Problem
```
KeyError: "['u_wind80'] not in index"
```

## Co było nie tak?

Kod próbował użyć nazwy `u_wind80`, ale po konwersji `to_dataframe()` kolumna wciąż nazywała się `u` (oryginalna nazwa z GRIB).

### ❌ Stary kod:
```python
all_data[f"{var}_{level}"] = data  # Tworzy 'u_wind80'

# Później:
tmp = da.to_dataframe()  # Ale DataFrame ma kolumnę 'u', nie 'u_wind80'!
cols = coords + [name]   # name = 'u_wind80'
tmp = tmp[cols]          # KeyError!
```

### ✅ Nowy kod (V2):
```python
# Konwertuj do DataFrame
tmp = data.to_dataframe()

# ZMIEŃ NAZWĘ kolumny PRZED użyciem
if var in ['t', 'gh', 'u', 'v']:
    new_name = f"{var}_{level}"
    tmp.rename(columns={var: new_name}, inplace=True)
else:
    new_name = var

# Teraz możemy użyć nowej nazwy
cols = coords + [new_name]
tmp = tmp[cols]  # Działa!
```

---

## Jak użyć V2?

**W PowerShell (gfs):**
```bash
cd C:\xampp\htdocs\gfs_downloader
python gfs_downloader_v2.py
```

**LUB** użyj ultimate (też naprawione):
```bash
python gfs_downloader_ultimate.py
```

---

## Co zostało naprawione?

1. ✅ Zmiana nazw kolumn PRZED użyciem
2. ✅ Poprawne mapowanie var → new_name
3. ✅ Obsługa wszystkich poziomów (2m, 10m, 80m, 850hPa, 500hPa)

---

## To powinno teraz zadziałać! 🎉

Uruchom:
```bash
python gfs_downloader_v2.py
```

I napisz co się stało!
