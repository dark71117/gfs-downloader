# 🔧 Naprawa problemu z numpy na Linux

## Problem
```
ImportError: failed to map segment from shared object
```

## Rozwiązanie

### Krok 1: Usuń i przeinstaluj numpy

```bash
# Na serwerze
cd ~/domains/gfs-downloader
source venv_new/bin/activate

# Odinstaluj numpy i zależności
pip uninstall -y numpy xarray pandas

# Zainstaluj zależności systemowe (jeśli potrzebne)
sudo apt-get update
sudo apt-get install -y python3-dev gfortran libopenblas-dev liblapack-dev

# Zainstaluj numpy ponownie (użyj starszej wersji 1.x zamiast 2.x)
pip install numpy==1.26.4

# Zainstaluj pozostałe biblioteki
pip install xarray pandas
pip install -r requirements.txt
```

### Krok 2: Jeśli nadal nie działa - użyj precompiled wheels

```bash
# Wyczyść cache pip
pip cache purge

# Zainstaluj z precompiled wheels
pip install --only-binary :all: numpy==1.26.4
pip install --only-binary :all: xarray pandas
```

### Krok 3: Alternatywnie - użyj conda (jeśli dostępne)

```bash
# Jeśli masz conda na serwerze
conda install -c conda-forge numpy=1.26.4 xarray pandas
```

### Krok 4: Sprawdź czy działa

```bash
python -c "import numpy; print(numpy.__version__)"
python -c "import xarray; print('OK')"
```

---

## Szybka naprawa (jedna komenda)

```bash
cd ~/domains/gfs-downloader
source venv_new/bin/activate
pip uninstall -y numpy xarray pandas && pip install numpy==1.26.4 xarray==2024.1.0 pandas==2.2.0 && python -c "import numpy; print('OK')"
```


